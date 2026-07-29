"""Asset-/Ressourcen-Pfade — funktioniert im Dev-Modus UND in der gepackten EXE.

PyInstaller entpackt gebundelte Daten nach sys._MEIPASS; im Dev-Modus liegen sie im
Projektordner. resource_dir() abstrahiert das, sodass Code, Prompts und Assets in
beiden Faellen ueber denselben Aufruf gefunden werden.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def asset(name: str) -> Path:
    return resource_dir() / "assets" / name


def prompts_dir() -> Path:
    return resource_dir() / "prompts"


def app_icon_path() -> Path:
    # Windows: Multi-Res-ICO (Taskbar/Alt-Tab). Linux: PNG — Qt laedt .ico zwar
    # meist auch, aber PNG ist dort der verlaessliche Standardweg.
    if sys.platform == "win32":
        return asset("fleech.ico")
    return asset("logo_256.png")
