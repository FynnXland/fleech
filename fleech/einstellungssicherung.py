"""Datierte Sicherungen der Einstellungen — vor jedem Update, vor jedem Build.

Warum es das gibt: Am 2026-08-20 hat ein Testlauf `settings.json` mit den
Vorgabewerten ueberschrieben. Hotkeys, Mikrofon, App-Zuordnungen, Woerterbuch und
der Lizenzschluessel waren weg. Die Ursache ist behoben (der Testlauf schreibt
jetzt in ein Wegwerf-Verzeichnis), aber die Lehre bleibt: Es gab nichts, worauf
man haette zurueckgreifen koennen. Die eine `settings.json.bak`, die `save()`
anlegt, war laengst mitueberschrieben — sie schuetzt gegen einen Schreibabbruch,
nicht gegen einen erfolgreichen Schreibvorgang mit falschem Inhalt.

Zwei Ausloeser, beide an Stellen, an denen erfahrungsgemaess etwas passiert:

* **Versionswechsel** — die App merkt beim Start, dass sie eine andere Version ist
  als die, die zuletzt gespeichert hat, und sichert VOR dem ersten Schreiben.
* **Build** — `packaging/build.py` sichert, bevor irgendetwas laeuft.

Dieses Modul kennt weder Qt noch die Einstellungsklasse: Es bekommt Pfade und
kopiert Bytes. Damit ist es aus jedem Zusammenhang heraus aufrufbar — aus der
App, aus dem Build-Skript, aus einem Wegwerf-Skript in der Konsole.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Wie viele Sicherungen aufgehoben werden. Zwoelf, weil eine Sicherung nur dann
# entsteht, wenn sich der Inhalt geaendert hat — zwoelf verschiedene Staende
# reichen weit zurueck und kosten zusammen keine 100 KB.
BEHALTEN = 12

ORDNERNAME = "sicherungen"

# settings-20260820-101530-update.json
_MUSTER = re.compile(r"^settings-\d{8}-\d{6}-[a-z]+\.json$")


def ordner_fuer(einstellungen: Path) -> Path:
    """Die Sicherungen liegen in einem Unterordner neben den Einstellungen.

    Bewusst nicht daneben in dasselbe Verzeichnis: Dort liegen bereits
    `settings.json.bak` und diverse Handablagen, und eine wachsende Reihe
    datierter Dateien macht den Ordner unlesbar."""
    return einstellungen.parent / ORDNERNAME


def vorhandene(ordner: Path) -> list[Path]:
    """Bekannte Sicherungen, aelteste zuerst. Fremde Dateien bleiben unangetastet.

    Der Namensfilter ist kein Schoenheitsfehler, sondern der Grund, warum
    `raeume_auf` gefahrlos loeschen darf: Was nicht nach unserem Muster heisst,
    hat jemand von Hand dorthin gelegt."""
    if not ordner.is_dir():
        return []
    treffer = [p for p in ordner.iterdir() if p.is_file() and _MUSTER.match(p.name)]
    return sorted(treffer, key=lambda p: p.name)


def raeume_auf(ordner: Path, behalten: int = BEHALTEN) -> int:
    """Aelteste Sicherungen entfernen. Rueckgabe: wie viele geloescht wurden."""
    alle = vorhandene(ordner)
    weg = alle[:-behalten] if behalten > 0 else alle
    anzahl = 0
    for p in weg:
        try:
            p.unlink()
            anzahl += 1
        except OSError:
            log.debug("Alte Sicherung %s liess sich nicht entfernen.", p.name,
                      exc_info=True)
    return anzahl


def sichere(einstellungen: Path, grund: str, jetzt: datetime | None = None,
            behalten: int = BEHALTEN) -> Path | None:
    """Eine Sicherung anlegen. Rueckgabe: die neue Datei, oder None.

    None bedeutet eines von dreien, und keines davon ist ein Fehler: Es gibt noch
    keine Einstellungen, der Inhalt ist gegenueber der neuesten Sicherung
    unveraendert, oder das Schreiben ging schief. Der letzte Fall wird
    protokolliert — aber er darf niemals den Aufrufer aufhalten. Eine App, die
    nicht startet, weil eine Sicherung misslang, waere schlimmer als das Problem.
    """
    grund = re.sub(r"[^a-z]", "", grund.lower()) or "unbekannt"
    try:
        if not einstellungen.is_file():
            return None
        inhalt = einstellungen.read_bytes()
        ordner = ordner_fuer(einstellungen)
        alle = vorhandene(ordner)
        if alle and alle[-1].read_bytes() == inhalt:
            # Unveraendert — eine zweite gleiche Kopie verdraengt nur eine
            # aeltere, die noch etwas anderes wusste.
            return None
        ordner.mkdir(parents=True, exist_ok=True)
        stempel = (jetzt or datetime.now()).strftime("%Y%m%d-%H%M%S")
        ziel = ordner / f"settings-{stempel}-{grund}.json"
        ziel.write_bytes(inhalt)
        raeume_auf(ordner, behalten)
        log.info("Einstellungen gesichert (%s): %s", grund, ziel.name)
        return ziel
    except OSError:
        log.warning("Einstellungen liessen sich nicht sichern (%s).", grund,
                    exc_info=True)
        return None


def neueste(einstellungen: Path) -> Path | None:
    """Die jüngste Sicherung — für „stell den Stand von vorhin wieder her"."""
    alle = vorhandene(ordner_fuer(einstellungen))
    return alle[-1] if alle else None


def stelle_wieder_her(einstellungen: Path, sicherung: Path) -> None:
    """Eine Sicherung zurueckspielen — und den aktuellen Stand vorher wegsichern.

    Ohne diese Vorsicht waere das Zurueckspielen selbst der naechste Datenverlust:
    Wer die falsche Sicherung erwischt, haette danach keinen Weg zurueck.
    """
    sichere(einstellungen, "vorruecksicherung")
    shutil.copy2(sicherung, einstellungen)
    log.info("Einstellungen aus %s wiederhergestellt.", sicherung.name)
