"""Der Tresor: Fleechs persoenliche Daten liegen nur verschluesselt auf der Platte.

Was geschuetzt ist, und womit:
* `history.db` (Verlauf) und `kontext.db` (Gedaechtnis) — SQLCipher, die ganze
  Datei samt Zeitstempeln, App-Namen und Fenstertiteln (`datenbank`).
* `settings.json`, ihre `.bak` und die Sicherungen — AES-256-GCM (`datei`).
* Der Schluessel dazu liegt beim System, nie im Klartext neben den Daten
  (`schluessel`, `ablage`: DPAPI unter Windows, Secret Service unter Linux).

Wogegen das hilft: gestohlene, verkaufte oder ausgebaute Platte, andere
Benutzerkonten, Backups, Cloud-Kopien, ein kopierter oder verschickter Ordner.
Wogegen nicht: Schadsoftware, die unter DEINEM Konto laeuft, waehrend Fleech
offen ist — Fleech muss seine Daten selbst lesen koennen, also kann es alles,
was als du laeuft. Das gilt fuer jede Anwendung, mit oder ohne Passwort.

Dazu gehoert, was gar nicht erst gespeichert wird: kein Diktattext im
Protokoll (`protokolltext`), kein Diktat im Zwischenablageverlauf von Windows
(`clipboard`), eine Aufbewahrungsfrist fuer den Verlauf (`history`).

Diese Fassade ist der einzige Weg hinein: Aufrufer nennen einen Zweck, nie
einen Schluessel.
"""

from __future__ import annotations

from pathlib import Path

from sqlcipher3.dbapi2 import Row  # noqa: F401  (row_factory fuer die Aufrufer)

from . import datei, datenbank, schluessel
from .datei import Unlesbar, ist_umschlag  # noqa: F401
from .schluessel import SchluesselFehlt  # noqa: F401

EINSTELLUNGEN = "einstellungen"
VERLAUF = "verlauf"
KONTEXT = "kontext"


def schuetze(daten: bytes, zweck: str) -> bytes:
    """Klartext → Umschlag (AES-256-GCM mit dem Teilschluessel des Zwecks)."""
    return datei.verschluessele(daten, schluessel.teilschluessel(zweck), zweck)


def oeffne(roh: bytes, zweck: str) -> bytes:
    """Umschlag → Klartext. Klartext (Datei von vor der Umstellung, eine von Hand
    zurueckgelegte Sicherung) geht unveraendert durch; beim naechsten Schreiben
    wird er verschluesselt. `Unlesbar` bei manipuliertem oder fremdem Umschlag."""
    if not ist_umschlag(roh):
        return roh
    return datei.entschluessele(roh, schluessel.teilschluessel(zweck), zweck)


def verbinde(pfad: Path, zweck: str, *, nur_lesen: bool = False, timeout: float = 5.0):
    """SQLCipher-Verbindung mit dem Teilschluessel des Zwecks."""
    return datenbank.verbinde(pfad, schluessel.teilschluessel(zweck),
                              nur_lesen=nur_lesen, timeout=timeout)
