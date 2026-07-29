"""Autostart — funktioniert fuer die installierte App UND im Dev-Modus.

Windows (HKCU\\...\\Run):
- Installiert (frozen): startet direkt die Fleech.exe mit --gui (kein Python sichtbar).
- Dev: pythonw -m fleech --gui --cwd <projekt>.
Die Deinstallation entfernt den Eintrag ueber den Inno-Uninstaller (reg delete).

Linux (XDG): ~/.config/autostart/fleech.desktop mit demselben Kommando-Schema.

Bei verschobener/neu installierter App wird ein veralteter Eintrag beim Start
automatisch auf den aktuellen Pfad korrigiert (reconcile_autostart).
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Windows' eigene Freigabe-Liste (Task-Manager → Autostart). Sie kann einen
# vorhandenen Run-Eintrag stillschweigend ausser Kraft setzen.
_APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
_VALUE_NAME = "Fleech"


def _command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --gui'
    exe = Path(sys.executable)
    if sys.platform == "win32":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            exe = pythonw
    project = Path(__file__).resolve().parent.parent.parent
    return f'"{exe}" -m fleech --gui --cwd "{project}"'


# -- Linux: XDG-Autostart ----------------------------------------------------------------


def _xdg_autostart_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "autostart" / "fleech.desktop"


def _write_desktop_entry(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Fleech\n"
        "Comment=Lokale Diktat-App\n"
        f"Exec={_command()}\n"
        "Icon=fleech\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )


def _read_desktop_exec(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("Exec="):
                return line[len("Exec="):].strip()
    except OSError:
        return None
    return None


def _set_autostart_linux(enabled: bool) -> bool:
    path = _xdg_autostart_file()
    try:
        if enabled:
            _write_desktop_entry(path)
        else:
            path.unlink(missing_ok=True)
        log.info("Autostart %s.", "aktiviert" if enabled else "deaktiviert")
        return True
    except Exception:
        log.exception("Autostart-Desktop-Datei konnte nicht geschrieben werden.")
        return False


# -- Windows: HKCU-Run -------------------------------------------------------------------


def _set_autostart_windows(enabled: bool) -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(key, _VALUE_NAME)
                except FileNotFoundError:
                    pass
        log.info("Autostart %s.", "aktiviert" if enabled else "deaktiviert")
        return True
    except Exception:
        log.exception("Autostart-Eintrag konnte nicht geschrieben werden.")
        return False


def _current_autostart_command_windows() -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _type = winreg.QueryValueEx(key, _VALUE_NAME)
            return value
    except OSError:
        return None


def _blocked_by_windows() -> bool:
    """Hat der Nutzer den Eintrag im Task-Manager (Autostart-Tab) deaktiviert?

    Windows fuehrt darueber eine EIGENE Liste (`StartupApproved\\Run`). Ist dort das
    erste Byte ungerade, startet Windows die App NICHT — der Run-Eintrag bleibt aber
    unveraendert stehen. Ohne diese Pruefung meldet Fleech „Autostart ist an",
    waehrend Windows ihn stillschweigend ignoriert: genau die Situation, in der man
    ewig nach dem Fehler in der App sucht.
    """
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _APPROVED_KEY) as key:
            value, _type = winreg.QueryValueEx(key, _VALUE_NAME)
            return bool(value) and value[0] % 2 == 1
    except OSError:
        return False  # kein Eintrag = nie deaktiviert worden


# -- Oeffentliche API (plattformneutral) --------------------------------------------------


def set_autostart(enabled: bool) -> bool:
    if sys.platform == "win32":
        return _set_autostart_windows(enabled)
    if sys.platform.startswith("linux"):
        return _set_autostart_linux(enabled)
    return False


def current_autostart_command() -> str | None:
    if sys.platform == "win32":
        return _current_autostart_command_windows()
    if sys.platform.startswith("linux"):
        return _read_desktop_exec(_xdg_autostart_file())
    return None


def is_autostart_enabled() -> bool:
    return current_autostart_command() is not None


def blocked_by_system() -> bool:
    """True = Eintrag existiert, wird vom Betriebssystem aber ignoriert."""
    if sys.platform != "win32":
        return False
    return is_autostart_enabled() and _blocked_by_windows()


def refresh_autostart_if_stale() -> None:
    """App verschoben/neu installiert → veralteten Autostart-Pfad korrigieren."""
    existing = current_autostart_command()
    if existing is not None and existing != _command():
        log.info("Autostart-Pfad veraltet — aktualisiere auf aktuelle App.")
        set_autostart(True)


def reconcile_autostart(desired: bool) -> None:
    """Autostart-Eintrag mit dem gespeicherten Nutzerwunsch abgleichen.

    Ein Update kann den Eintrag entfernen (Windows: Inno-Uninstaller loescht
    HKCU\\Run); die settings.json ueberlebt das Update aber. Beim Start also:
    - Wunsch = an, Eintrag fehlt  → wiederherstellen (Autostart ueberlebt Updates),
    - Wunsch = an, Eintrag veraltet → auf aktuellen Pfad aktualisieren,
    - Wunsch = aus, Eintrag da     → entfernen (Nutzer hat es abgeschaltet).
    """
    existing = current_autostart_command()
    if desired:
        if existing is None:
            log.info("Autostart laut Einstellungen gewuenscht, aber kein Eintrag — stelle her.")
            set_autostart(True)
        elif existing != _command():
            log.info("Autostart-Pfad veraltet — aktualisiere auf aktuellen Pfad.")
            set_autostart(True)
    elif existing is not None:
        log.info("Autostart laut Einstellungen aus, aber Eintrag vorhanden — entferne.")
        set_autostart(False)
