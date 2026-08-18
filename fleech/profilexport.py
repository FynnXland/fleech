"""Profile sichern und zurueckholen — eine JSON-Datei, nur Profile.

Vorschlag G-6 (Befund G-B10): Die einzige App-Konfiguration, die je angelegt
wurde (`app_quick` fuer claude.exe), ist zweimal spurlos verschwunden. Profile und
Zuordnungen leben nur in der `settings.json`, und es gab keinen Weg, sie einzeln
zu sichern.

BEWUSST NUR Profile und Schnellwechsel. Ein Gesamt-Backup schleppt den
Lizenzschluessel und den Mikrofonpfad mit — beides will man nicht weitergeben, und
die Weitergabe eines eingerichteten Setups ist der zweite Zweck dieser Datei.

Der Import ist ADDITIV: gleichnamige Profile werden nur nach Rueckfrage ersetzt,
unbekannte ergaenzt, nichts geloescht. Ein Import darf nie mehr wegnehmen, als der
Nutzer sieht — sonst ist die Sicherung selbst die naechste Verlustquelle.

Kein Qt: Der Datei-Dialog gehoert zur Seite, das Zusammensetzen und Zusammenfuehren
nicht. Deshalb laesst sich beides ohne Fenster pruefen.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .profiles import ensure_default_profile

log = logging.getLogger(__name__)

# Kennung in der Datei. Sie ist der einzige Schutz davor, dass jemand eine
# beliebige JSON-Datei auswaehlt und sich seine Profile damit zerlegt.
FORMAT = "fleech-profile"
VERSION = 1


@dataclass
class Bericht:
    """Was ein Import tatsaechlich getan hat — Grundlage der Rueckmeldung."""

    ergaenzt: list = field(default_factory=list)
    ersetzt: list = field(default_factory=list)
    uebersprungen: list = field(default_factory=list)
    schnellwechsel: int = 0

    def satz(self) -> str:
        teile = []
        if self.ergaenzt:
            teile.append(f"{len(self.ergaenzt)} ergänzt ({', '.join(self.ergaenzt)})")
        if self.ersetzt:
            teile.append(f"{len(self.ersetzt)} ersetzt ({', '.join(self.ersetzt)})")
        if self.uebersprungen:
            teile.append(f"{len(self.uebersprungen)} unverändert gelassen "
                         f"({', '.join(self.uebersprungen)})")
        if self.schnellwechsel:
            teile.append(f"{self.schnellwechsel} Schnellwechsel-Einträge")
        return "  ·  ".join(teile) or "Nichts zu übernehmen — alles war schon da."


def export_daten(settings) -> dict:
    """Die Profile des Nutzers als reine Daten — Kopien, nie die Originale.

    Ohne Kopie haenge die geschriebene Datei an denselben Listen wie die laufende
    App; ein spaeterer Umbau am Rueckgabewert aendert dann die Einstellungen mit.
    """
    prof = getattr(settings, "profiles", None)
    items = [copy.deepcopy(i) for i in (getattr(prof, "items", None) or [])
             if isinstance(i, dict)]
    quick = {}
    for schluessel, namen in (getattr(prof, "app_quick", None) or {}).items():
        if isinstance(namen, list) and namen:
            quick[str(schluessel).lower()] = [str(n) for n in namen]
    return {"format": FORMAT, "version": VERSION, "items": items, "app_quick": quick}


def schreibe(pfad, daten: dict) -> None:
    """Datei schreiben, lesbar eingerueckt — sie soll sich von Hand ansehen lassen."""
    Path(pfad).write_text(json.dumps(daten, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def lies(pfad) -> dict:
    """Datei lesen und pruefen. Wirft `ValueError`, wenn es keine Profildatei ist."""
    try:
        daten = json.loads(Path(pfad).read_text(encoding="utf-8"))
    except Exception as fehler:
        raise ValueError(f"Datei nicht lesbar: {fehler}") from fehler
    if not isinstance(daten, dict) or not isinstance(daten.get("items"), list):
        raise ValueError("Das ist keine Fleech-Profildatei.")
    return daten


def _namen(items) -> dict:
    """{name_klein: index} der vorhandenen Profile."""
    return {str(i.get("name", "")).strip().lower(): pos
            for pos, i in enumerate(items) if isinstance(i, dict)
            and str(i.get("name", "")).strip()}


def namenskonflikte(settings, daten: dict) -> list[str]:
    """Namen, die es schon gibt — die Liste fuer die Rueckfrage vor dem Import."""
    vorhanden = _namen(getattr(settings.profiles, "items", None) or [])
    treffer = []
    for eintrag in daten.get("items", []):
        if not isinstance(eintrag, dict):
            continue
        name = str(eintrag.get("name", "")).strip()
        if name and name.lower() in vorhanden and name not in treffer:
            treffer.append(name)
    return treffer


def importiere(settings, daten: dict, ersetzen: bool = False) -> Bericht:
    """Profile additiv uebernehmen. `ersetzen` gilt nur fuer gleichnamige Profile.

    Das Standardprofil bleibt in jedem Fall das Standardprofil: Die Flagge
    `default` kommt aus der laufenden Installation, nie aus der Datei. Sonst haette
    man nach einem Import entweder zwei Fallbacks oder keinen — und das faellt erst
    beim naechsten Diktat auf.
    """
    bericht = Bericht()
    items = settings.profiles.items
    if items is None:
        items = settings.profiles.items = []
    vorhanden = _namen(items)

    for eintrag in daten.get("items", []):
        if not isinstance(eintrag, dict):
            continue
        name = str(eintrag.get("name", "")).strip()
        if not name:
            continue
        neu = copy.deepcopy(eintrag)
        neu["name"] = name
        pos = vorhanden.get(name.lower())
        if pos is None:
            # Ein importiertes Profil wird nie zum Standardprofil (siehe Docstring).
            neu.pop("default", None)
            items.append(neu)
            vorhanden[name.lower()] = len(items) - 1
            bericht.ergaenzt.append(name)
        elif ersetzen:
            war_standard = bool(items[pos].get("default"))
            if war_standard:
                neu["default"] = True
            else:
                neu.pop("default", None)
            items[pos] = neu
            bericht.ersetzt.append(name)
        else:
            bericht.uebersprungen.append(name)

    quick = getattr(settings.profiles, "app_quick", None)
    if not isinstance(quick, dict):
        quick = settings.profiles.app_quick = {}
    for schluessel, namen in (daten.get("app_quick") or {}).items():
        if not isinstance(namen, list) or not namen:
            continue
        schluessel = str(schluessel).lower()
        # Ein bestehender Eintrag ist eine bewusste Einschraenkung dieser
        # Installation — die ueberschreibt nur, wer dem Ersetzen zugestimmt hat.
        if schluessel in quick and not ersetzen:
            continue
        quick[schluessel] = [str(n) for n in namen]
        bericht.schnellwechsel += 1

    ensure_default_profile(items)
    log.info("Profile importiert: %s", bericht.satz())
    return bericht
