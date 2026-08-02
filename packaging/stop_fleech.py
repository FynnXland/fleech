"""Laufendes Fleech ORDENTLICH beenden — fuer Update/Deployment.

    .venv\\Scripts\\python packaging\\stop_fleech.py

Warum ein eigenes Skript: Vor jedem robocopy-Sync muss Fleech weg, sonst haengt
robocopy an der laufenden Fleech.exe. Der bequeme Weg war bisher `Stop-Process
-Force` — ein hartes Kill. Fleech speichert seine Einstellungen an ueber einem
Dutzend Stellen (Fensterposition, Profilwechsel, Hotkeys …); trifft das Kill
ausgerechnet einen laufenden Schreibvorgang, blieb frueher eine leere
settings.json zurueck und beim naechsten Start standen alle Werte auf Vorgabe —
Lizenzschluessel eingeschlossen. Genau das ist mehrfach passiert.

Seit dem atomaren Schreiben (`UserSettings.save`) ueberlebt die Datei auch ein
hartes Kill. Dieses Skript ist die zweite Sicherung: Es bittet die laufende
Instanz ueber denselben IPC-Kanal, den auch der Zweitstart nutzt, sich selbst zu
beenden — mit Speichern zu Ende, Mutex- und Hotkey-Freigabe.

Exit 0 = kein Fleech mehr da (auch wenn vorher keins lief).
Exit 1 = laeuft noch; dann ist ein hartes Kill die Notbremse des Aufrufers.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WARTEN_S = 12.0


def laeuft() -> bool:
    if sys.platform != "win32":
        return subprocess.run(["pgrep", "-x", "Fleech"],
                              capture_output=True).returncode == 0
    aus = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Fleech.exe", "/NH"],
        capture_output=True, text=True, errors="ignore").stdout
    return "Fleech.exe" in aus


def bitte_beenden() -> bool:
    """„quit" ueber den IPC-Kanal schicken. False = niemand hat zugehoert."""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtNetwork import QLocalSocket

    from fleech.ui.desktop import IPC_NAME

    QCoreApplication.instance() or QCoreApplication(sys.argv)
    sock = QLocalSocket()
    sock.connectToServer(IPC_NAME)
    if not sock.waitForConnected(1500):
        return False
    sock.write(b"quit")
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def main() -> int:
    if not laeuft():
        print("[stop] Fleech laeuft nicht.")
        return 0
    try:
        angeklopft = bitte_beenden()
    except Exception as exc:
        print(f"[stop] IPC nicht erreichbar ({exc}).")
        angeklopft = False
    if not angeklopft:
        print("[stop] Keine Antwort auf dem IPC-Kanal (aeltere Version?).")
        return 1

    ende = time.monotonic() + WARTEN_S
    while time.monotonic() < ende:
        if not laeuft():
            print("[stop] Fleech ordentlich beendet.")
            return 0
        time.sleep(0.3)
    print(f"[stop] Laeuft nach {WARTEN_S:.0f}s noch.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
