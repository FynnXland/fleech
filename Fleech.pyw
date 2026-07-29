"""Fleech ohne Konsole starten (Doppelklick).

Startet die Desktop-App ueber das pythonw der Projekt-venv — es erscheint kein
Terminal-Fenster. Log: %APPDATA%/Fleech/fleech.log
"""

import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
PYTHONW = PROJECT / ".venv" / "Scripts" / "pythonw.exe"

if not PYTHONW.exists():
    import ctypes

    ctypes.windll.user32.MessageBoxW(
        0, "Projekt-venv fehlt. Bitte zuerst das Setup aus der README ausfuehren.",
        "Fleech", 0x10,
    )
    sys.exit(1)

subprocess.Popen(
    [str(PYTHONW), "-m", "fleech", "--gui", "--cwd", str(PROJECT)],
    cwd=str(PROJECT),
    creationflags=subprocess.CREATE_NO_WINDOW,
)
