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

Dazu kamen mit 5.12.2 zwei weitere Netze gegen denselben Schaden: die Meldung
schrumpfender Schreibvorgaenge und die Spiegelung des Lizenzschluessels.

Dieses Modul kennt weder Qt noch die Einstellungsklasse: Es bekommt Pfade,
Zahlen und Zeichenketten. Damit ist es aus jedem Zusammenhang heraus aufrufbar —
aus der App, aus dem Build-Skript, aus einem Wegwerf-Skript in der Konsole.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from .settingsheilung import schrumpfung

log = logging.getLogger(__name__)

# Umfang des zuletzt geschriebenen Standes, je Pfad. Prozessweit und absichtlich
# hier statt an den Einstellungen: Es beschreibt die DATEI, nicht die Werte.
_LETZTER_UMFANG: dict = {}

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


# -- Der Lizenzschluessel, getrennt von allem anderen -----------------------------------

# Eigene Datei neben den Einstellungen. Der Grund ist unangenehm einfach: Der
# Schluessel steckte bisher NUR in `settings.json`, und die ist zweimal
# verlorengegangen (2026-08-20 durch einen Testlauf, 2026-09-05 durch etwas, das
# sich bis heute nicht benennen laesst). Jedes Mal stand Fleech danach als nicht
# freigeschaltet da und der Schluessel musste von Hand neu eingetragen werden.
#
# Alles andere in den Einstellungen kann man in einer Minute neu klicken. Den
# Schluessel nicht — den muss man SUCHEN. Deshalb liegt er zusaetzlich hier.
SCHLUESSELDATEI = "lizenz.key"


def schluesselpfad(einstellungen: Path) -> Path:
    return einstellungen.parent / SCHLUESSELDATEI


def merke_schluessel(einstellungen: Path, schluessel: str) -> None:
    """Den Schluessel spiegeln. Ein LEERER Schluessel loescht die Spiegelung NICHT.

    Das ist Absicht und der Kern des Schutzes: Genau der Zustand „die Einstellungen
    haben plötzlich keinen Schluessel mehr" ist der Schaden, gegen den hier
    gesichert wird. Wuerde er die Sicherung mitnehmen, waere sie wertlos. Wer den
    Schluessel wirklich loswerden will, nimmt `vergiss_schluessel()` — den Weg
    geht nur, wer das Feld bewusst leert.
    """
    schluessel = (schluessel or "").strip()
    if not schluessel:
        return
    ziel = schluesselpfad(einstellungen)
    try:
        if ziel.is_file() and ziel.read_text(encoding="utf-8").strip() == schluessel:
            return
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(schluessel + "\n", encoding="utf-8")
        log.info("Lizenzschluessel gespiegelt (%s).", ziel.name)
    except OSError:
        log.debug("Lizenzschluessel liess sich nicht spiegeln.", exc_info=True)


def gemerkter_schluessel(einstellungen: Path) -> str:
    try:
        return schluesselpfad(einstellungen).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def vergiss_schluessel(einstellungen: Path) -> None:
    """Die Spiegelung entfernen — nur fuer das bewusste Loeschen des Schluessels."""
    try:
        schluesselpfad(einstellungen).unlink()
        log.info("Gespiegelter Lizenzschluessel entfernt.")
    except OSError:
        pass


# -- Wer schreibt, sagt was er schreibt -------------------------------------------------


def melde_schreibvorgang(pfad: Path, jetzt: dict, schluessel: str = "") -> None:
    """Nach jedem erfolgreichen Schreiben: hat sich der Umfang veraendert?

    `save()` lief bisher lautlos. Zweimal sind dadurch Zuordnungen, Woerterbuch und
    der Lizenzschluessel verschwunden, ohne dass sich hinterher sagen liess, welcher
    Schreibvorgang es war — zwischen „geladen: 4 Zuordnungen" und „geladen: 0
    Zuordnungen" stand im Protokoll schlicht nichts.

    Gemeldet wird NUR die Veraenderung: `save()` laeuft auch bei jeder
    Fensterbewegung, und ein Protokoll, das bei jedem Pixel eine Zeile schreibt,
    liest niemand. Schrumpfen ist eine WARNUNG — das ist der Fall, der zweimal
    unbemerkt geblieben ist.

    Fehler hier duerfen den Schreibvorgang nie nachtraeglich scheitern lassen: Die
    Einstellungen stehen zu diesem Zeitpunkt bereits auf der Platte.
    """
    try:
        merke_schluessel(pfad, schluessel)
        vorher = _LETZTER_UMFANG.get(str(pfad))
        _LETZTER_UMFANG[str(pfad)] = dict(jetzt)
        if vorher is None or jetzt == vorher:
            return
        verlust = schrumpfung(vorher, jetzt)
        if verlust:
            log.warning("Einstellungen geschrieben — WENIGER als zuvor: %s (%s).",
                        verlust, pfad.name)
            return
        log.info("Einstellungen geschrieben: %d Profile, %d App-Zuordnungen, "
                 "%d Schnellwechsel-Eintraege, %d Woerterbuchzeilen, Lizenz %s.",
                 jetzt.get("profile", 0), jetzt.get("zuordnungen", 0),
                 jetzt.get("schnellwechsel", 0), jetzt.get("woerter", 0),
                 "vorhanden" if jetzt.get("lizenz") else "FEHLT")
    except Exception:
        log.debug("Umfangsmeldung fehlgeschlagen.", exc_info=True)


def sichere_bei_versionswechsel(pfad: Path, gespeichert: str, laufend: str) -> bool:
    """Hat zuletzt eine ANDERE Version geschrieben? Dann sichern. True = gesichert.

    Der Zeitpunkt ist der Kern: Gesichert wird die Datei so, wie sie auf der Platte
    liegt — vor jeder Migration, vor jedem `save()`. Das ist der einzige Moment, in
    dem der alte Stand noch vollstaendig existiert.
    """
    if (gespeichert or "") == (laufend or ""):
        return False
    sichere(pfad, "update")
    # True auch dann, wenn `sichere` nichts anzulegen hatte (unveraenderter Inhalt,
    # keine Datei): Der Aufrufer soll die laufende Version trotzdem vermerken,
    # sonst sichert der naechste Start erneut.
    return True


def hole_schluessel_zurueck(pfad: Path, vorhanden: str) -> str:
    """Fehlt der Lizenzschluessel, aber die Spiegelung hat ihn: zurueckgeben.

    Alles andere in den Einstellungen klickt man in einer Minute neu. Den
    Schluessel muss man SUCHEN — und ohne ihn diktiert Fleech nicht.

    Bewusst nur in DIESE Richtung: Ein vorhandener Schluessel wird nie durch die
    Spiegelung ersetzt. Der Spiegel ist die Rueckfallebene, nicht die Wahrheit.
    """
    if str(vorhanden or "").strip():
        return vorhanden
    gemerkt = gemerkter_schluessel(pfad)
    if not gemerkt:
        return vorhanden
    log.warning("Lizenzschluessel fehlte in den Einstellungen und wurde aus %s "
                "zurueckgeholt.", SCHLUESSELDATEI)
    return gemerkt
