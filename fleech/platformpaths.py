"""Benutzer-Datenordner plattformuebergreifend.

Windows: %APPDATA%\\Fleech (unveraendert zum Bestand — Settings/History/Logs
ueberleben ein Update der installierten App).
Linux:   $XDG_CONFIG_HOME/Fleech (Default ~/.config/Fleech). Bewusst EIN Ordner
fuer alles (settings.json, history.db, fleech.log, config.yaml-Override), damit
sich die Doku und der Support-Pfad nicht pro Plattform verzweigen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "Fleech"


def session_kind() -> str:
    """Sitzungsart: "windows" | "x11" | "wayland" | "unknown".

    Unter Wayland fallen mehrere Funktionen aus, die auf X11/EWMH beruhen (Caret-
    Rueckkehr, Vollbild-Erkennung, Unterdrueckung gebundener Maustasten). Das soll
    die App benennen koennen, statt es stillschweigend hinzunehmen."""
    if sys.platform == "win32":
        return "windows"
    if os.environ.get("WAYLAND_DISPLAY") or \
            os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


# Was unter Wayland (ohne Portal-Unterstuetzung) nicht funktioniert — einmal zentral
# formuliert, damit UI und Log dieselbe Aussage treffen.
WAYLAND_LIMITS = (
    "Cursor-Rückkehr springt nur zum Fenster, nicht ins genaue Textfeld",
    "Vollbild-/Spiel-Erkennung greift nicht (Overlay- und RAM-Automatik entfallen)",
    "gebundene Maustasten lösen zusätzlich ihre normale Funktion aus",
)


def user_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / APP_DIR_NAME
