"""Stresstest D-2 als eigener Prozess: zwei Threads speichern, einer liest mit.

Aufgerufen von `test_settings_haltbarkeit.py`, nicht von pytest gesammelt (kein
`test_`-Name). Grund fuer den eigenen Prozess: Im pytest-Prozess brach dieser
Test auf dem GitHub-Runner sporadisch mit „Fatal Python error: Aborted“ ab
(Oktober 2026, ab b06a7be in 3 von 5 vollen Laeufen, lokal nie). Nur mit der
vollen Testsammlung und pytests Ausgabe-Capture auf Dateiebene, ohne dass sich
eine Ursache im Fleech-Code fand. Der Abbruch riss die ganze Suite mit. Hier
laeuft der Test mit frischem Zustand; scheitert er doch, scheitert nur er.

Abschottung wie in `conftest.tresor_ablage`: Schluessel im Speicher, Datenordner
im Wegwerf-Verzeichnis. Nichts hier fasst den echten Datenschluessel an.

Ausgabe: eine JSON-Zeile mit den Befunden.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path


class _AblageImSpeicher:
    wert = None

    def lies(self):
        return self.wert

    def speichere(self, schluessel: bytes) -> None:
        self.wert = schluessel


def main(ordner: Path) -> dict:
    from fleech.tresor import schluessel

    ablage = _AblageImSpeicher()
    schluessel.ablage = lambda: ablage
    schluessel.DATENORDNER = ordner / "appdata"
    schluessel.vergiss()

    from fleech import tresor
    from fleech.usersettings import UserSettings

    pfad = ordner / "settings.json"
    kaputt: list[str] = []

    def lies_text() -> str:
        return tresor.oeffne(pfad.read_bytes(), tresor.EINSTELLUNGEN).decode("utf-8")

    def schreiber(name: str) -> None:
        s = UserSettings()
        s.general.display_name = name
        for _ in range(200):
            s.save(pfad)

    def leser(stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                roh = lies_text()
            except OSError:
                continue                     # Datei gerade ersetzt — kein Fehler
            except Exception as fehler:      # Umschlag unlesbar = halb geschrieben
                kaputt.append(f"{fehler}")
                continue
            if not roh.strip():
                continue
            try:
                json.loads(roh)
            except ValueError as fehler:
                kaputt.append(f"{fehler} — {len(roh)} Zeichen")

    stop = threading.Event()
    beobachter = threading.Thread(target=leser, args=(stop,), daemon=True)
    beobachter.start()
    threads = [threading.Thread(target=schreiber, args=(f"Name-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()
    beobachter.join(timeout=5)

    return {
        "kaputt": kaputt,
        "name": json.loads(lies_text())["general"]["display_name"],
        "reste": [p.name for p in ordner.glob(pfad.name + "*.tmp")],
    }


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]))), flush=True)
