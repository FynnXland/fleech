"""Laufendes Fleech ORDENTLICH beenden — fuer Update/Deployment.

    .venv\\Scripts\\python packaging\\stop_fleech.py

Warum ein eigenes Skript: Vor jedem robocopy-Sync muss Fleech weg, sonst haengt
robocopy an der laufenden Fleech.exe. Der bequeme Weg war bisher `Stop-Process
-Force` — ein hartes Kill. Fleech speichert seine Einstellungen an ueber einem
Dutzend Stellen (Fensterposition, Profilwechsel, Hotkeys …); trifft das Kill
ausgerechnet einen laufenden Schreibvorgang, blieb frueher eine leere
settings.json zurueck und beim naechsten Start standen alle Werte auf Vorgabe.
Genau das ist mehrfach passiert.

Seit dem atomaren Schreiben (`UserSettings.save`) ueberlebt die Datei auch ein
hartes Kill. Dieses Skript ist die zweite Sicherung: Es bittet die laufende
Instanz ueber denselben IPC-Kanal, den auch der Zweitstart nutzt, sich selbst zu
beenden — mit Speichern zu Ende, Mutex- und Hotkey-Freigabe.

Es klopft IMMER zuerst an — nicht erst, wenn eine Fleech.exe zu sehen ist. Am
2026-10-08 lief Fleech aus dem Quellcode (`pythonw.exe -m fleech --gui`); die
alte Pruefung kannte nur Fleech.exe, meldete „laeuft nicht", und die frisch
installierte EXE klopfte danach bloss bei der alten Instanz an („Fleech laeuft
bereits"). Getestet wurde der alte Stand. Deshalb zaehlt als „laeuft": eine
Fleech.exe, ein Prozess mit `-m fleech` in der Kommandozeile ODER eine Instanz,
die auf dem IPC-Kanal antwortet.

Exit 0 = kein Fleech mehr da (auch wenn vorher keins lief).
Exit 1 = laeuft noch; dann ist ein hartes Kill die Notbremse des Aufrufers
         (die gemeldeten PIDs sind die Kandidaten).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WARTEN_S = 12.0


def _ist_fleech(name: str, cmdline: list[str]) -> bool:
    """Gepackte App (Fleech.exe / Linux-Binary „Fleech") oder Quellcode-Instanz.

    Die Quellcode-Instanz erkennt man nur an der Kommandozeile: `python(w) -m
    fleech …` — der Prozessname ist ein beliebiges python.exe. Verglichen wird
    Argument fuer Argument, nicht als Teilstring: Shells und Werkzeuge, die
    „-m fleech" irgendwo in einem langen Skript-Argument tragen, sind kein Fleech.
    """
    if name.lower() in ("fleech.exe", "fleech"):
        return True
    for i, arg in enumerate(cmdline):
        if arg == "-mfleech" or (arg == "-m" and cmdline[i + 1:i + 2] == ["fleech"]):
            return True
    return False


def fleech_prozesse() -> list[tuple[int, str]]:
    """Alle laufenden Fleech-Prozesse als (PID, Beschreibung).

    Ueber psutil (ohnehin Laufzeit-Abhaengigkeit) statt tasklist: tasklist kennt
    keine Kommandozeilen, und wmic fehlt auf aktuellen Windows-11-Staenden. Eine
    venv-Quellcode-Instanz taucht dabei zweimal auf — der Starter in
    `.venv/Scripts` und der echte Interpreter; beide enden mit der App.
    """
    import psutil

    eigene = os.getpid()
    gefunden = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        info = proc.info
        if info["pid"] == eigene:
            continue
        name = info.get("name") or ""
        cmdline = info.get("cmdline") or []
        if _ist_fleech(name, cmdline):
            gefunden.append((info["pid"], " ".join(cmdline) or name))
    return gefunden


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


def _melde(prozesse: list[tuple[int, str]]) -> None:
    for pid, beschreibung in prozesse:
        print(f"[stop]   PID {pid}: {beschreibung}")


def main() -> int:
    # Erst anklopfen, dann schauen: Eine Instanz, die zuhoert, ist der sicherste
    # Beweis fuer „laeuft" — egal, wie sie gestartet wurde.
    try:
        angeklopft = bitte_beenden()
    except Exception as exc:
        print(f"[stop] IPC nicht erreichbar ({exc}).")
        angeklopft = False
    if angeklopft:
        print("[stop] Beenden ueber den IPC-Kanal angefordert.")

    prozesse = fleech_prozesse()
    if not prozesse:
        if angeklopft:
            # Entweder schon weg, oder weder Fleech.exe noch `-m fleech` (Start
            # auf anderem Weg). Das „quit" ist angekommen; mehr laesst sich
            # nicht pruefen.
            print("[stop] Beenden angefordert; kein Fleech-Prozess (mehr) zu sehen.")
        else:
            print("[stop] Fleech laeuft nicht.")
        return 0
    if not angeklopft:
        print("[stop] Fleech laeuft, antwortet aber nicht auf dem IPC-Kanal "
              "(aeltere Version oder haengt):")
        _melde(prozesse)
        return 1

    ende = time.monotonic() + WARTEN_S
    while time.monotonic() < ende:
        time.sleep(0.3)
        prozesse = fleech_prozesse()
        if not prozesse:
            print("[stop] Fleech ordentlich beendet.")
            return 0
    print(f"[stop] Laeuft nach {WARTEN_S:.0f}s noch:")
    _melde(prozesse)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
