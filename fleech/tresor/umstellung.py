"""Einmalige Umstellung beim Start: alles, was bis 6.2 im Klartext lag, in den Tresor.

Laeuft in `run_desktop`, bevor irgendetwas die Dateien oeffnet. Jeder Schritt ist
fuer sich wiederholbar: Bricht der Start mittendrin ab, macht der naechste dort
weiter, wo noch Klartext liegt (`noetig`).

Die Protokolle werden nicht umgeschrieben, sondern getilgt: Bis 6.2 stand dort
jedes Diktat im Volltext, und ab 6.3 kommt keins mehr hinein — es gibt nichts,
was sich zu verschluesseln lohnte.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import EINSTELLUNGEN, KONTEXT, VERLAUF, datenbank, schluessel, schuetze
from .datei import ist_umschlag
from .loeschen import sicher_loeschen, ueberschreibe

log = logging.getLogger(__name__)

DATENBANKEN = (("history.db", VERLAUF), ("kontext.db", KONTEXT))
_EINSTELLUNGEN = ("settings.json", "settings.json.bak", "settings.json.kaputt",
                  "settings.json.zurueckgesetzt")


@dataclass
class Bericht:
    zeilen: dict = field(default_factory=dict)   # {"history.db": Zeilen, …}
    dateien: int = 0                             # verschluesselte Einstellungsdateien
    protokolle: int = 0                          # getilgte Protokolldateien
    fehlgeschlagen: bool = False                 # Ausnahme — Rest bleibt Klartext

    @property
    def etwas_getan(self) -> bool:
        return bool(self.zeilen or self.dateien)


def einstellungsdateien(ordner: Path) -> list[Path]:
    ordner = Path(ordner)
    dateien = [ordner / n for n in _EINSTELLUNGEN]
    sicherungen = ordner / "sicherungen"
    if sicherungen.is_dir():
        dateien += sorted(sicherungen.glob("settings-*.json"))
    return [p for p in dateien if p.is_file()]


def _ist_klartext_datei(pfad: Path) -> bool:
    try:
        with open(pfad, "rb") as f:
            kopf = f.read(16)
    except OSError:
        return False
    return bool(kopf) and not ist_umschlag(kopf)


def noetig(ordner: Path) -> bool:
    ordner = Path(ordner)
    for name, _ in DATENBANKEN:
        pfad = ordner / name
        if datenbank.ist_klartext(pfad) or pfad.with_name(name + ".klartext").exists():
            return True
    return any(_ist_klartext_datei(p) for p in einstellungsdateien(ordner))


def _ersetze(pfad: Path, neu: bytes) -> None:
    """Klartext-Datei durch ihren Umschlag ersetzen; der alte Inhalt wird vorher
    ueberschrieben, damit er nicht in freien Bloecken liegen bleibt."""
    tmp = pfad.with_name(pfad.name + ".tresor.tmp")
    with open(tmp, "wb") as f:
        f.write(neu)
        f.flush()
        os.fsync(f.fileno())
    ueberschreibe(pfad)
    os.replace(tmp, pfad)


def protokolle_tilgen(ordner: Path) -> int:
    """`fleech.log*` und `fleech-cli.log` ueberschreiben und loeschen.

    Die eigenen Datei-Handler werden dafuer kurz geschlossen und gesperrt; die
    naechste Log-Zeile oeffnet die Datei neu (so verhaelt sich `FileHandler`).
    Das Ersatz-stderr der EXE (`fleech-cli.log`) bleibt offen — es wird nur
    geleert, nicht geloescht.
    """
    ordner = Path(ordner).resolve()
    dateien = sorted(ordner.glob("fleech.log*")) + [ordner / "fleech-cli.log"]
    handler = [h for h in logging.getLogger().handlers
               if isinstance(h, logging.FileHandler)
               and Path(h.baseFilename).resolve().parent == ordner]
    for h in handler:
        h.acquire()
    try:
        for h in handler:
            if h.stream is not None:
                h.stream.close()
                h.stream = None
        getilgt = 0
        for pfad in dateien:
            if pfad.is_file():
                sicher_loeschen(pfad)
                getilgt += 1
    finally:
        for h in handler:
            h.release()
    return getilgt


def fuehre_aus(ordner: Path) -> Bericht:
    ordner = Path(ordner)
    bericht = Bericht()
    for name, zweck in DATENBANKEN:
        zaehlung = datenbank.umstellen(ordner / name, schluessel.teilschluessel(zweck))
        if zaehlung is not None:
            bericht.zeilen[name] = sum(v for k, v in zaehlung.items()
                                       if k != "sqlite_sequence")
    for pfad in einstellungsdateien(ordner):
        roh = pfad.read_bytes()
        if roh and not ist_umschlag(roh):
            _ersetze(pfad, schuetze(roh, EINSTELLUNGEN))
            bericht.dateien += 1
    if bericht.etwas_getan:
        bericht.protokolle = protokolle_tilgen(ordner)
        log.info("Tresor: Daten verschluesselt (%s; %d Einstellungsdateien); %d alte "
                 "Protokolldateien mit Diktattext getilgt.",
                 ", ".join(f"{n}: {z} Zeilen" for n, z in bericht.zeilen.items())
                 or "keine Datenbank", bericht.dateien, bericht.protokolle)
    return bericht


def beiseitelegen(ordner: Path) -> Path:
    """„Neu beginnen" ohne Schluessel: die verschluesselten Daten in einen Unterordner
    schieben — nicht loeschen. Taucht der Code spaeter auf, lassen sie sich
    zuruecklegen. Danach entsteht beim ersten Zugriff ein neuer Schluessel."""
    from .ablage import DATEINAME_DPAPI, DATEINAME_ROH

    ordner = Path(ordner)
    ziel = ordner / time.strftime("gesperrt-%Y%m%d-%H%M%S")
    ziel.mkdir(parents=True, exist_ok=True)
    namen = [n for n, _ in DATENBANKEN] + list(_EINSTELLUNGEN) + [
        DATEINAME_DPAPI, DATEINAME_ROH]
    for name in namen:
        for endung in ("", "-wal", "-shm", "-journal"):
            pfad = ordner / (name + endung)
            if pfad.exists():
                shutil.move(str(pfad), str(ziel / pfad.name))
    if (ordner / "sicherungen").is_dir():
        shutil.move(str(ordner / "sicherungen"), str(ziel / "sicherungen"))
    schluessel.vergiss()
    log.warning("Verschluesselte Daten ohne Schluessel nach %s beiseitegelegt — "
                "Fleech beginnt mit frischen Daten.", ziel.name)
    return ziel
