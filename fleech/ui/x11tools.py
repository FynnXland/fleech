"""X11-Helfer (EWMH): aktives Fenster, Aktivierung, Fullscreen, Fensterliste.

Genutzt von focusrestore (Cursor-Rueckkehr) und windowsfocus (Gaming-/Fullscreen-
Erkennung, App-Liste der Profile-Seite) unter Linux. Alles Best-Effort: jede
Funktion faengt ihre Fehler und liefert neutrale Werte — ein X11-Problem darf
nie ein Diktat stoeren. Unter Wayland (kein DISPLAY-/XWayland-Root-Zugriff auf
fremde Fenster) liefern die Funktionen schlicht None/False/[].

python-xlib ist als pynput-Abhaengigkeit ohnehin installiert.
"""

from __future__ import annotations

import logging
import os
import sys
import threading

log = logging.getLogger(__name__)

# Xlib-Display-Verbindungen sind nicht threadsicher; Aufrufe kommen aus dem
# UI-Poll UND aus Pipeline-Worker-Threads → global serialisieren (alle Abfragen
# sind µs–ms-billig).
_LOCK = threading.Lock()
_display = None


def available() -> bool:
    return sys.platform.startswith("linux") and bool(os.environ.get("DISPLAY"))


def _get_display():
    global _display
    if _display is None:
        from Xlib import display

        _display = display.Display()
    return _display


def _reset_display() -> None:
    global _display
    try:
        if _display is not None:
            _display.close()
    except Exception:
        pass
    _display = None


def _atom(d, name: str):
    return d.intern_atom(name)


def _window_property(d, window, name: str):
    prop = window.get_full_property(_atom(d, name), 0)  # 0 = AnyPropertyType
    return None if prop is None else prop.value


def active_window_id() -> int | None:
    """Fenster-ID des aktuell aktiven Top-Level-Fensters (EWMH), None bei Fehler."""
    if not available():
        return None
    with _LOCK:
        try:
            d = _get_display()
            root = d.screen().root
            value = _window_property(d, root, "_NET_ACTIVE_WINDOW")
            if value is None or len(value) == 0 or not value[0]:
                return None
            return int(value[0])
        except Exception:
            _reset_display()
            log.debug("Aktives X11-Fenster nicht ermittelbar.", exc_info=True)
            return None


def activate_window(window_id: int) -> bool:
    """Bringt ein Fenster per _NET_ACTIVE_WINDOW-ClientMessage nach vorn.

    Quelle 2 (= Pager) — Fenstermanager wie KWin behandeln solche Anfragen als
    legitime, nutzerinitiierte Aktivierung (kein Fokus-Diebstahl-Schutz).
    True = das Fenster ist danach tatsaechlich aktiv.
    """
    if not available() or not window_id:
        return False
    with _LOCK:
        try:
            from Xlib import X
            from Xlib.protocol import event as xevent

            d = _get_display()
            root = d.screen().root
            win = d.create_resource_object("window", window_id)
            msg = xevent.ClientMessage(
                window=win,
                client_type=_atom(d, "_NET_ACTIVE_WINDOW"),
                data=(32, [2, X.CurrentTime, 0, 0, 0]),
            )
            root.send_event(msg, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            d.flush()
        except Exception:
            _reset_display()
            log.debug("X11-Fensteraktivierung fehlgeschlagen.", exc_info=True)
            return False
    import time

    time.sleep(0.06)  # dem WM einen Moment geben, die Aktivierung umzusetzen
    return active_window_id() == int(window_id)


def _window_pid(d, win) -> int | None:
    try:
        value = _window_property(d, win, "_NET_WM_PID")
        if value is not None and len(value):
            return int(value[0])
    except Exception:
        pass
    return None


def _window_title(d, win) -> str:
    """Fenstertitel: bevorzugt _NET_WM_NAME (UTF-8), sonst das aeltere WM_NAME."""
    try:
        value = win.get_full_property(_atom(d, "_NET_WM_NAME"), 0)
        if value is not None and value.value:
            raw = value.value
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            if text.strip():
                return text.strip()[:300]
    except Exception:
        pass
    try:
        return (win.get_wm_name() or "").strip()[:300]
    except Exception:
        return ""


def active_window_state() -> tuple[bool, str, str]:
    """(fullscreen, prozessname, fenstertitel) des aktiven Fensters.

    Fullscreen traegt die Gaming-Erkennung, der Titel das Zweitkriterium der
    Profil-Zuordnung."""
    if not available():
        return False, "", ""
    with _LOCK:
        try:
            d = _get_display()
            root = d.screen().root
            value = _window_property(d, root, "_NET_ACTIVE_WINDOW")
            if value is None or len(value) == 0 or not value[0]:
                return False, "", ""
            win = d.create_resource_object("window", int(value[0]))
            state = _window_property(d, win, "_NET_WM_STATE")
            fullscreen = bool(state) and _atom(d, "_NET_WM_STATE_FULLSCREEN") in list(state)
            name = ""
            pid = _window_pid(d, win)
            if pid:
                try:
                    import psutil

                    name = psutil.Process(pid).name()
                except Exception:
                    name = ""
            return fullscreen, name, _window_title(d, win)
        except Exception:
            _reset_display()
            log.debug("X11-Fensterstatus nicht ermittelbar.", exc_info=True)
            return False, "", ""


def visible_window_processes() -> list[str]:
    """Prozessnamen aller Top-Level-Fenster (EWMH-Clientliste, dedupliziert)."""
    if not available():
        return []
    names: list[str] = []
    seen: set[str] = set()
    with _LOCK:
        try:
            import psutil

            d = _get_display()
            root = d.screen().root
            value = _window_property(d, root, "_NET_CLIENT_LIST")
            for wid in list(value or []):
                try:
                    win = d.create_resource_object("window", int(wid))
                    pid = _window_pid(d, win)
                    if not pid:
                        continue
                    name = psutil.Process(pid).name()
                except Exception:
                    continue
                if name and name.lower() not in seen:
                    seen.add(name.lower())
                    names.append(name)
        except Exception:
            _reset_display()
            log.debug("X11-Fensterliste nicht ermittelbar.", exc_info=True)
    return names
