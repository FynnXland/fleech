"""Fokus-Wiederherstellung: Ziel-Textfeld vom Aufnahme-Start vor dem Einfuegen zuruecksetzen.

Anwendungsfall: Der Nutzer startet ein Diktat mit dem Cursor in einem Textfeld, klickt
oder tabbt waehrend des Sprechens aber woanders hin — in ein anderes Fenster ODER in
ein anderes Feld derselben App. Ohne Gegenmassnahme landet der eingefuegte Text an der
falschen Stelle.

Zwei Ebenen, weil ein reines Fenster-nach-vorn nur den App-Wechsel abdeckt:

1. Fenster: ``SetForegroundWindow`` holt das urspruengliche Fenster in den Vordergrund
   (deckt den Wechsel in eine ANDERE App ab).
2. Textfeld/Caret: Ueber ``GetGUIThreadInfo`` wird die Bildschirm-Position des
   Text-Cursors (``rcCaret`` — NICHT die Mausposition!) beim Aufnahme-Start erfasst.
   Vor dem Einfuegen klickt Fleech genau dorthin zurueck und setzt den Text-Cursor so
   wieder ins urspruengliche Feld. Danach wird die Maus an ihren alten Platz gesetzt.
   Das funktioniert auch dort, wo die interne Caret-Position nicht auslesbar ist
   (Electron/Web-Apps), solange das Feld sichtbar an derselben Stelle blieb.

Fallback: Existiert das Fenster nicht mehr oder blockiert Windows die Aktion, passiert
nichts — der Text geht an den aktuellen Fokus (nie ein Crash, nie Datenverlust).
HWND-Werte sind unter Windows garantiert 32-bit-gross (sign-extended), daher ist das
ctypes-Handling ueber ``wintypes.HWND`` sicher.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt  # reine Typ-Aliase, auf allen Plattformen importierbar
import logging
import sys
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

SW_RESTORE = 9


@dataclass
class FocusTarget:
    """Momentaufnahme des Ziel-Feldes beim Aufnahme-Start."""

    hwnd: int                       # Top-Level-Fenster (fuer den App-Wechsel)
    caret_screen: tuple[int, int] | None = None  # Bildschirm-Pos des Text-Cursors


def _user32():
    u = ctypes.windll.user32
    # Handles korrekt typisieren, damit sie auf 64-Bit nicht auf c_int gekuerzt werden.
    u.GetForegroundWindow.restype = wt.HWND
    u.GetWindowThreadProcessId.restype = wt.DWORD
    u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.c_void_p]
    u.SetForegroundWindow.argtypes = [wt.HWND]
    u.BringWindowToTop.argtypes = [wt.HWND]
    u.IsWindow.argtypes = [wt.HWND]
    u.IsIconic.argtypes = [wt.HWND]
    u.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    u.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, ctypes.c_bool]
    u.GetWindowRect.argtypes = [wt.HWND, ctypes.c_void_p]
    u.ClientToScreen.argtypes = [wt.HWND, ctypes.c_void_p]
    u.GetGUIThreadInfo.argtypes = [wt.DWORD, ctypes.c_void_p]
    return u


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD), ("flags", wt.DWORD),
        ("hwndActive", wt.HWND), ("hwndFocus", wt.HWND),
        ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND),
        ("hwndMoveSize", wt.HWND), ("hwndCaret", wt.HWND),
        ("rcCaret", wt.RECT),
    ]


def capture_focus_target() -> FocusTarget | None:
    """Fenster + Bildschirm-Position des Text-Cursors beim Aufnahme-Start erfassen.

    Windows: GetGUIThreadInfo.rcCaret (das AKTIVE Textfeld-Insert, nicht die Maus).
    Linux/X11: nur das aktive Fenster (EWMH) — eine Caret-Position ist dort nicht
    generisch auslesbar, ``caret_screen`` bleibt None → es wird spaeter nur das
    Fenster zurueckgeholt."""
    if sys.platform != "win32":
        from . import x11tools

        wid = x11tools.active_window_id()
        return FocusTarget(hwnd=wid) if wid else None
    try:
        u = _user32()
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return None
        tid = u.GetWindowThreadProcessId(hwnd, None)
        gti = _GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(_GUITHREADINFO)
        caret_screen = None
        if tid and u.GetGUIThreadInfo(tid, ctypes.byref(gti)):
            caret_hwnd = gti.hwndCaret or gti.hwndFocus or hwnd
            r = gti.rcCaret
            # Leeres rcCaret (0/0/0/0) = App meldet keine Caret-Geometrie → kein Klick.
            if caret_hwnd and (r.left or r.top or r.right or r.bottom):
                pt = wt.POINT(r.left, (r.top + r.bottom) // 2)  # linke Kante, vertikal mittig
                if u.ClientToScreen(caret_hwnd, ctypes.byref(pt)):
                    caret_screen = (int(pt.x), int(pt.y))
        return FocusTarget(hwnd=int(hwnd), caret_screen=caret_screen)
    except Exception:
        log.debug("Fokus-Ziel nicht ermittelbar.", exc_info=True)
        return None


def restore_foreground(hwnd: int | None) -> bool:
    """Bringt ``hwnd`` wieder in den Vordergrund. True, wenn es danach vorn ist.

    Nutzt den AttachThreadInput-Trick: Windows erlaubt SetForegroundWindow aus einem
    Hintergrund-Thread nur, wenn dessen Input-Queue an die des aktuellen
    Vordergrundfensters angehaengt ist (Fokus-Diebstahl-Schutz)."""
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        u = _user32()
        if not u.IsWindow(hwnd):
            return False  # Fenster existiert nicht mehr → Fallback: aktueller Fokus
        current = u.GetForegroundWindow()
        if current and int(current) == int(hwnd):
            return True

        kernel32 = ctypes.windll.kernel32
        this_tid = kernel32.GetCurrentThreadId()
        fg_tid = u.GetWindowThreadProcessId(current, None) if current else 0

        attached = False
        if fg_tid and fg_tid != this_tid:
            attached = bool(u.AttachThreadInput(this_tid, fg_tid, True))
        try:
            if u.IsIconic(hwnd):
                u.ShowWindow(hwnd, SW_RESTORE)  # minimiertes Fenster wiederherstellen
            u.BringWindowToTop(hwnd)
            u.SetForegroundWindow(hwnd)
        finally:
            if attached:
                u.AttachThreadInput(this_tid, fg_tid, False)

        time.sleep(0.06)  # dem Fenster einen Moment geben, tatsaechlich vorn zu sein
        result = u.GetForegroundWindow()
        return bool(result) and int(result) == int(hwnd)
    except Exception:
        log.debug("Fokus-Wiederherstellung fehlgeschlagen.", exc_info=True)
        return False


def _point_in_window(hwnd: int, x: int, y: int) -> bool:
    """Liegt der Bildschirmpunkt im aktuellen Rechteck des Zielfensters?

    Schutz gegen Fehlklicks: hat sich das Fenster verschoben/geschlossen oder war der
    Caret ausserhalb, wird NICHT geklickt (der Text geht an den aktuellen Fokus)."""
    try:
        u = _user32()
        if not u.IsWindow(hwnd):
            return False
        rect = wt.RECT()
        if not u.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        return rect.left <= x <= rect.right and rect.top <= y <= rect.bottom
    except Exception:
        return False


def _click_at(x: int, y: int) -> None:
    """Linksklick an Bildschirm-(x,y); Maus danach an ihre alte Position zurueck.

    Setzt den Text-Cursor ins Zielfeld, ohne die Maus des Nutzers dauerhaft zu versetzen."""
    from pynput.mouse import Button, Controller

    m = Controller()
    old = m.position
    try:
        m.position = (x, y)
        time.sleep(0.02)
        m.click(Button.left)
        time.sleep(0.02)
    finally:
        m.position = old  # Maus zurueck an ihren Platz


def restore_focus_target(target) -> bool:
    """Ziel-Feld vor dem Einfuegen wiederherstellen: Fenster nach vorn + an die
    gemerkte Caret-Position zuruecklicken. Robust gegen fehlende Daten/Fehler."""
    if target is None:
        return False
    if sys.platform != "win32":
        from . import x11tools

        wid = getattr(target, "hwnd", None)
        return x11tools.activate_window(wid) if wid else False
    hwnd = getattr(target, "hwnd", None)
    caret = getattr(target, "caret_screen", None)
    ok = restore_foreground(hwnd) if hwnd else False
    if caret is not None:
        x, y = caret
        if hwnd and _point_in_window(hwnd, x, y):
            try:
                _click_at(x, y)
                ok = True
            except Exception:
                log.debug("Caret-Ruecklick fehlgeschlagen.", exc_info=True)
    return ok
