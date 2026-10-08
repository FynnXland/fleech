"""Zwischenablage plattformuebergreifend — EINE Nahtstelle fuer die Injection.

Windows: pyperclip (Bestand, stabil, keine Zusatztools).
Linux:   copykitten (arboard-basiert) — funktioniert auf X11 UND Wayland ohne
         xclip/xsel-Systemabhaengigkeit. pyperclip bleibt Fallback (greift z. B.,
         wenn ein Clipboard-Manager wie Klipper via qdbus erreichbar ist).

Alle Funktionen sind Best-Effort: Lesen liefert None statt Exception, Schreiben
wirft nur, wenn KEIN Backend funktioniert (dann waere die Injection wirkungslos
und der Fehler muss sichtbar werden).

Seit 6.3.0 schreibt Fleech unter Windows selbst (`_kopiere_privat`): Text plus
die drei Formate, mit denen Windows Inhalte aus dem Zwischenablageverlauf (Win+V)
und der Cloud-Zwischenablage heraushaelt — wie Passwort-Manager. Vorher landete
jedes Diktat dort, weil die Injection ueber die Zwischenablage einfuegt, und blieb
nach dem Diktat im Verlauf stehen, auf Wunsch sogar auf anderen Geraeten.
"""

from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

_CF_UNICODETEXT = 13   # Win32-Standardformat "Unicode-Text"


def _use_copykitten() -> bool:
    return sys.platform != "win32"


def paste_text() -> str | None:
    """Aktueller Text-Inhalt der Zwischenablage; None = leer/nicht lesbar."""
    if _use_copykitten():
        try:
            import copykitten

            return copykitten.paste()
        except Exception:
            # Leer, Nicht-Text-Inhalt oder Backend-Problem → pyperclip probieren.
            pass
    try:
        import pyperclip

        return pyperclip.paste()
    except Exception:
        return None


def has_text() -> bool:
    """Liegt ueberhaupt TEXT in der Zwischenablage?

    Befund B-10: Gesichert und zurueckgeschrieben wird nur Text. Lag ein Bild oder
    eine kopierte Datei darin, lieferte `paste_text()` einen leeren String — und
    nach dem Diktat schrieb Fleech genau diesen leeren String zurueck. Der eben
    kopierte Screenshot war damit weg. Ist kein Text da, wird nach dem Einfuegen
    nichts wiederhergestellt: Der Diktat-Text bleibt in der Ablage, das Bild ist
    ohnehin schon vom System verdraengt worden — aber es wird nicht zusaetzlich
    ein leerer Text darueber geschrieben.

    Windows fragt `IsClipboardFormatAvailable(CF_UNICODETEXT)`; das ist die einzige
    Auskunft, die ohne Oeffnen der Ablage funktioniert. Keine Auskunft moeglich →
    True, also wie bisher verfahren (fail-open).
    """
    if sys.platform != "win32":
        return bool(paste_text())
    try:
        import ctypes

        return bool(ctypes.windll.user32.IsClipboardFormatAvailable(_CF_UNICODETEXT))
    except Exception:
        log.debug("Zwischenablage-Format nicht abfragbar.", exc_info=True)
        return True


def copy_text(text: str) -> None:
    if not _use_copykitten():   # Windows
        try:
            _kopiere_privat(text)
            return
        except Exception:
            log.debug("Private Zwischenablage fehlgeschlagen — pyperclip.", exc_info=True)
    if _use_copykitten():
        try:
            import copykitten

            copykitten.copy(text)
            return
        except Exception:
            log.debug("copykitten.copy fehlgeschlagen — versuche pyperclip.", exc_info=True)
    import pyperclip

    pyperclip.copy(text)


# -- Windows: Text ohne Zwischenablageverlauf und Cloud-Sync --------------------------

# Microsoft, „Cloud Clipboard and Clipboard History Formats": Liegt das erste Format
# mit beliebigem Inhalt vor, ignorieren Verlauf, Cloud und Ablage-Ueberwacher den
# ganzen Inhalt; die beiden anderen (DWORD 0) sagen dasselbe einzeln.
_PRIVAT_FORMATE = ("ExcludeClipboardContentFromMonitorProcessing",
                   "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard")


def _kopiere_privat(text: str) -> None:
    import ctypes
    import time
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

    def setze(format_id: int, daten: bytes) -> None:
        speicher = kernel32.GlobalAlloc(0x0002, len(daten))   # GMEM_MOVEABLE
        if not speicher:
            raise OSError(ctypes.get_last_error(), "GlobalAlloc")
        ziel = kernel32.GlobalLock(speicher)
        ctypes.memmove(ziel, daten, len(daten))
        kernel32.GlobalUnlock(speicher)
        if not user32.SetClipboardData(format_id, speicher):
            kernel32.GlobalFree(speicher)
            raise OSError(ctypes.get_last_error(), "SetClipboardData")

    # Ein eigenes (unsichtbares) Fenster als Besitzer: Mit OpenClipboard(NULL)
    # setzt EmptyClipboard keinen Besitzer, und SetClipboardData darf scheitern.
    fenster = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0,
                                     None, None, None, None)
    try:
        for _ in range(20):   # die Ablage kann kurz von einem anderen Programm belegt sein
            if user32.OpenClipboard(fenster):
                break
            time.sleep(0.01)
        else:
            raise OSError(ctypes.get_last_error(), "OpenClipboard")
        try:
            user32.EmptyClipboard()
            setze(_CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))
            for name in _PRIVAT_FORMATE:
                setze(user32.RegisterClipboardFormatW(name), (0).to_bytes(4, "little"))
        finally:
            user32.CloseClipboard()
    finally:
        if fenster:
            user32.DestroyWindow(fenster)
