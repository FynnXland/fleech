"""Windows-Fokus-Signale: DND/Focus Assist, Fullscreen, Gaming — ehrlich & defensiv.

Drei Quellen, klar nach Verlaesslichkeit getrennt:

1. SHQueryUserNotificationState (shell32, DOKUMENTIERT): Busy / Presentation /
   D3D-Fullscreen / AcceptsNotifications. Primaersignal fuer "darf ich stoeren?".
2. Focus Assist / "Bitte nicht stoeren" (Win 10/11): NUR ueber die undokumentierte
   WNF-Abfrage lesbar (NtQueryWnfStateData). Best-Effort: liefert True/False oder
   None = unbekannt. Ein Fehler hier darf nie Folgen haben.
3. Fullscreen-Heuristik: Vordergrundfenster deckt seinen Monitor exakt ab und ist
   nicht Desktop/Shell. Ergaenzt das D3D-Signal um randlose Fullscreen-Apps.

Alle Abfragen sind billig (µs-Bereich) und werden von der App im Sekundentakt gepollt.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import sys
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# SHQueryUserNotificationState — Rueckgabewerte (QUERY_USER_NOTIFICATION_STATE)
QUNS_NOT_PRESENT = 1
QUNS_BUSY = 2
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4
QUNS_ACCEPTS_NOTIFICATIONS = 5
QUNS_QUIET_TIME = 6
QUNS_APP = 7

_SUPPRESSING_STATES = {QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE}

# WNF-Statename fuer Focus Assist (undokumentiert, stabil seit Win10 1709):
# WNF_SHEL_QUIETHOURS_ACTIVE_PROFILE_CHANGED
_WNF_QUIET_HOURS = (ctypes.c_ulonglong * 1)(0xD83063EA3BF1C75)

_SHELL_WINDOW_CLASSES = {"Progman", "WorkerW"}

# Fenstertitel koennen sehr lang werden (ganze Dateipfade). Fuer den Zweck
# (Teilstring-Vergleich in Profil-Regeln) reicht ein Ausschnitt; die Grenze haelt
# zugleich Log-Zeilen und die Historie lesbar.
_MAX_TITLE_LEN = 300


def _window_title(hwnd) -> str:
    """Titel eines Fensters ("" bei Fehler/leer). Best-Effort — ein fehlender Titel
    darf nie die Fokus-Abfrage reissen."""
    try:
        user32 = ctypes.windll.user32
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(min(length, _MAX_TITLE_LEN) + 1)
        user32.GetWindowTextW(hwnd, buf, len(buf))
        return buf.value.strip()
    except Exception:
        return ""


@dataclass
class FocusContext:
    """Momentaufnahme der Fokus-Situation. dnd=None heisst: nicht ermittelbar."""

    dnd: bool | None = None
    fullscreen: bool = False
    d3d_fullscreen: bool = False
    presentation_or_busy: bool = False
    foreground_process: str = ""
    # Titel des Vordergrundfensters ("" = nicht ermittelbar). Zweitkriterium fuer die
    # Profil-Zuordnung: derselbe Prozess kann sehr verschiedene Kontexte tragen
    # (ein Editor-Fenster mit Code vs. eines mit Notizen).
    foreground_title: str = ""

    @property
    def gaming_or_fullscreen(self) -> bool:
        return self.fullscreen or self.d3d_fullscreen or self.presentation_or_busy


def list_visible_window_processes() -> list[str]:
    """Prozessnamen aller sichtbaren Top-Level-Fenster (dedupliziert, Best-Effort).

    Fuer die Profile-Seite: "welche Apps laufen gerade?". Kein Poll — wird nur
    beim Anzeigen/Refresh der Seite aufgerufen.
    """
    if sys.platform != "win32":
        from . import x11tools

        return x11tools.visible_window_processes()
    names: list[str] = []
    seen: set[str] = set()
    try:
        import psutil

        user32 = ctypes.windll.user32
        pids: list[int] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
        def _collect(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
                pid = wt.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    pids.append(pid.value)
            return True

        user32.EnumWindows(_collect, 0)
        for pid in pids:
            try:
                name = psutil.Process(pid).name()
            except Exception:
                continue
            if name and name.lower() not in seen:
                seen.add(name.lower())
                names.append(name)
    except Exception:
        log.debug("Fensterliste nicht ermittelbar.", exc_info=True)
    return names


class FocusProbe:
    """Fragt die drei Signale ab. Jede Teil-Abfrage ist einzeln gegen Fehler isoliert."""

    def __init__(self):
        # Prozessname-Cache: der 3-s-Poll trifft meist dasselbe Vordergrundfenster —
        # psutil.Process(...).name() (Syscalls) nur bei (hwnd, pid)-Wechsel neu holen.
        self._proc_cache: tuple[int, int, str] | None = None

    def query(self) -> FocusContext:
        ctx = FocusContext()
        if sys.platform != "win32":
            # Linux/X11: Fullscreen + Prozessname des aktiven Fensters (EWMH) —
            # traegt die Gaming-Erkennung. DND ist nicht generisch abfragbar
            # (dnd=None = unbekannt, die Policy behandelt das bereits defensiv).
            try:
                from . import x11tools

                (ctx.fullscreen, ctx.foreground_process,
                 ctx.foreground_title) = x11tools.active_window_state()
            except Exception:
                log.debug("X11-Fokus-Abfrage fehlgeschlagen.", exc_info=True)
            return ctx
        try:
            state = self._notification_state()
            ctx.d3d_fullscreen = state == QUNS_RUNNING_D3D_FULL_SCREEN
            ctx.presentation_or_busy = state in (QUNS_BUSY, QUNS_PRESENTATION_MODE)
        except Exception:
            log.debug("SHQueryUserNotificationState fehlgeschlagen.", exc_info=True)
        try:
            ctx.dnd = self._focus_assist_active()
        except Exception:
            log.debug("Focus-Assist-Abfrage fehlgeschlagen.", exc_info=True)
            ctx.dnd = None
        try:
            (ctx.fullscreen, ctx.foreground_process,
             ctx.foreground_title) = self._foreground_fullscreen()
        except Exception:
            log.debug("Fullscreen-Heuristik fehlgeschlagen.", exc_info=True)
        return ctx

    # -- 1: dokumentiert -------------------------------------------------------------

    @staticmethod
    def _notification_state() -> int:
        state = ctypes.c_int(0)
        result = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
        if result != 0:  # S_OK == 0
            raise OSError(f"HRESULT 0x{result & 0xFFFFFFFF:08x}")
        return state.value

    # -- 2: undokumentiert (Best-Effort) ----------------------------------------------

    @staticmethod
    def _focus_assist_active() -> bool | None:
        """True/False = Focus Assist an/aus; None = Abfrage nicht moeglich."""
        ntdll = ctypes.windll.ntdll
        change_stamp = ctypes.c_ulong(0)
        buffer = ctypes.c_ulong(0)
        size = ctypes.c_ulong(ctypes.sizeof(buffer))
        status = ntdll.NtQueryWnfStateData(
            ctypes.byref(_WNF_QUIET_HOURS), None, None,
            ctypes.byref(change_stamp), ctypes.byref(buffer), ctypes.byref(size),
        )
        if status != 0:
            return None
        # 0 = aus; 1 = nur Prioritaet; 2 = nur Wecker — beides gilt als "DND aktiv".
        return buffer.value != 0

    # -- 3: Heuristik -----------------------------------------------------------------

    def _foreground_fullscreen(self) -> tuple[bool, str, str]:
        """(deckt den Monitor ab?, Prozessname, Fenstertitel)."""
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False, "", ""

        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)
        if class_buf.value in _SHELL_WINDOW_CLASSES:
            return False, "", ""

        title = _window_title(hwnd)

        rect = wt.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False, "", title

        monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                        ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False, "", title
        m = info.rcMonitor
        covers_monitor = (
            rect.left <= m.left and rect.top <= m.top
            and rect.right >= m.right and rect.bottom >= m.bottom
        )

        name = ""
        try:
            pid = wt.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                # Nur der PROZESSNAME wird gecacht — der Titel wechselt staendig
                # innerhalb desselben Fensters (anderer Tab, andere Datei) und waere
                # aus dem Cache sofort veraltet.
                cached = self._proc_cache
                if cached is not None and cached[0] == hwnd and cached[1] == pid.value:
                    name = cached[2]
                else:
                    import psutil

                    name = psutil.Process(pid.value).name()
                    self._proc_cache = (hwnd, pid.value, name)
        except Exception:
            pass
        return covers_monitor, name, title


# Prozessname-Cache fuer die Sofort-Abfrage unten. Getrennt vom Cache der
# FocusProbe: Die eine laeuft im 3-s-Poll, die andere im Hotkey-Pfad — ein
# gemeinsamer Zustand waere eine Kopplung ohne Nutzen.
_JETZT_CACHE: tuple = ()


def foreground_now() -> tuple[str, str]:
    """(Prozessname, Fenstertitel) des Vordergrundfensters — JETZT, ohne Poll.

    Der 3-Sekunden-Poll (`FocusProbe`) ist fuer Ducking und Gaming-Erkennung
    gedacht: Dort ist eine Sekunde Verzug egal. Fuer alles, was an einem
    Tastendruck haengt, ist er zu traege — wer in eine App tabbt und sofort den
    Hotkey nimmt, bekaeme das Profil der VORIGEN App. Genau so gemeldet: „wenn ich
    nach Chrome tabbe, kann ich zwischen allen Chrome-Profilen wechseln, und wenn
    ich wieder in Claude bin, immer noch die vier."

    Fehler sind hier kein Ereignis: Wer den Vordergrund nicht kennt, faellt auf
    „keine App" zurueck und damit auf die globale Profilauswahl.
    """
    global _JETZT_CACHE
    if sys.platform != "win32":
        try:
            from . import x11tools

            _voll, prozess, titel = x11tools.active_window_state()
            return prozess or "", titel or ""
        except Exception:
            log.debug("X11-Sofortabfrage fehlgeschlagen.", exc_info=True)
            return "", ""
    try:
        import ctypes
        from ctypes import wintypes as wt

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "", ""
        titel = _window_title(hwnd)
        pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return "", titel
        # psutil.Process(...).name() kostet Syscalls; im Hotkey-Pfad wird die
        # Abfrage in schneller Folge gestellt (Halten oeffnet die Liste, Loslassen
        # schaltet weiter) und trifft dabei fast immer dasselbe Fenster.
        if _JETZT_CACHE and _JETZT_CACHE[0] == hwnd and _JETZT_CACHE[1] == pid.value:
            return _JETZT_CACHE[2], titel
        import psutil

        name = psutil.Process(pid.value).name()
        _JETZT_CACHE = (hwnd, pid.value, name)
        return name, titel
    except Exception:
        log.debug("Vordergrund-Sofortabfrage fehlgeschlagen.", exc_info=True)
        return "", ""
