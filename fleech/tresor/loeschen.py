"""Klartext-Dateien so loeschen, dass ihr Inhalt nicht im Papierkorb der Platte liegt.

Ein blankes `unlink` gibt nur den Platz frei — der Inhalt steht weiter auf der
Platte, bis zufaellig etwas darueber geschrieben wird, und jedes
Wiederherstellungswerkzeug findet ihn. Deshalb erst den ganzen Inhalt mit
Zufallsbytes ueberschreiben, auf die Platte zwingen, dann kuerzen und loeschen.

Ehrliche Grenze: Auf einer SSD landet ein Ueberschreiben wegen der internen
Blockverwaltung nicht zwingend auf denselben Zellen. Wirklich weg sind alte
Reste dort erst mit einer verschluesselten Platte (BitLocker/LUKS) — das sagt
auch der Changelog. Ein Durchgang reicht: Mehrfaches Ueberschreiben ist ein
Mythos aus der Zeit der Magnetbaender.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_BLOCK = 1024 * 1024


def ueberschreibe(pfad: Path) -> None:
    """Inhalt mit Zufall ueberschreiben und auf 0 Byte kuerzen (Datei bleibt)."""
    groesse = pfad.stat().st_size
    with open(pfad, "r+b") as f:
        rest = groesse
        while rest > 0:
            n = min(_BLOCK, rest)
            f.write(os.urandom(n))
            rest -= n
        f.flush()
        os.fsync(f.fileno())
        f.seek(0)
        f.truncate()
        f.flush()
        os.fsync(f.fileno())


def sicher_loeschen(pfad: Path) -> bool:
    """Ueberschreiben, dann loeschen. True = die Datei ist weg oder war nie da.

    Laesst sich eine Datei zwar ueberschreiben, aber nicht loeschen (unter Windows:
    vom eigenen Prozess noch offen, z. B. das Ersatz-stderr `fleech-cli.log`),
    bleibt sie leer stehen — der Inhalt ist trotzdem fort, und genau darum geht es.
    """
    pfad = Path(pfad)
    if not pfad.exists():
        return True
    try:
        ueberschreibe(pfad)
    except Exception:
        log.warning("%s liess sich nicht ueberschreiben — wird nur geloescht.",
                    pfad.name, exc_info=True)
    try:
        pfad.unlink()
        return True
    except Exception:
        log.debug("%s nicht loeschbar (noch geoeffnet?) — bleibt leer stehen.",
                  pfad.name, exc_info=True)
        return False
