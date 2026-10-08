"""SQLite-Dateien des Tresors: SQLCipher (AES-256, HMAC-SHA512 je Seite).

SQLCipher verschluesselt die GANZE Datei, Seite fuer Seite — nicht nur einzelne
Spalten. Auch Zeitstempel, App-Namen, Fenstertitel und das Schema sind damit
unlesbar, ebenso Journal und WAL. Der Schluessel geht als Rohschluessel hinein
(`x'…'`): Er ist ohnehin zufaellig, die Passwort-Ableitung (PBKDF2) waere nur
Wartezeit bei jeder Verbindung.

Zwei Einstellungen je Verbindung:
* `secure_delete` — geloeschte Eintraege werden genullt, statt als freie Seiten
  liegen zu bleiben (Verlauf loeschen, Aufbewahrungsfrist).
* `temp_store = MEMORY` — Zwischendateien grosser Sortierungen entstehen im
  Speicher, nicht als unverschluesselte Temp-Datei.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .loeschen import sicher_loeschen

log = logging.getLogger(__name__)

SQLITE_KOPF = b"SQLite format 3\x00"
_NEBENDATEIEN = ("-wal", "-shm", "-journal")


def _kopf(pfad: Path) -> bytes | None:
    try:
        with open(pfad, "rb") as f:
            return f.read(len(SQLITE_KOPF))
    except (FileNotFoundError, IsADirectoryError):
        return None


def ist_klartext(pfad: Path) -> bool:
    """Eine gewoehnliche, unverschluesselte SQLite-Datei?"""
    return _kopf(Path(pfad)) == SQLITE_KOPF


def ist_verschluesselt(pfad: Path) -> bool:
    """Eine nicht leere Datei ohne SQLite-Kopf — bei uns: SQLCipher."""
    kopf = _kopf(Path(pfad))
    return bool(kopf) and kopf != SQLITE_KOPF


def _schluessel_pragma(schluessel: bytes) -> str:
    return f"PRAGMA key = \"x'{schluessel.hex()}'\""


def verbinde(pfad: Path, schluessel: bytes, *, nur_lesen: bool = False,
             timeout: float = 5.0):
    """Verbindung zur verschluesselten Datei (neu = wird verschluesselt angelegt).

    Ein falscher Schluessel faellt erst bei der ersten Abfrage auf
    (`DatabaseError: file is not a database`) — so verhaelt sich SQLCipher.

    Liegt die Datei (noch) im Klartext, weil die Umstellung beim Start
    gescheitert ist, wird sie ohne Schluessel geoeffnet: Ein Verlauf, der
    weiterlaeuft, ist besser als einer, der bei jedem Diktat einen Fehler wirft.
    Die Umstellung versucht es beim naechsten Start erneut, und das Protokoll
    sagt es bei jeder solchen Verbindung.
    """
    from sqlcipher3 import dbapi2

    pfad = Path(pfad)
    if nur_lesen:
        con = dbapi2.connect(pfad.resolve().as_uri() + "?mode=ro", uri=True,
                             timeout=timeout)
    else:
        con = dbapi2.connect(str(pfad), timeout=timeout)
    # Ohne das schreibt SQLCipher bei falschem Schluessel ERROR-Zeilen auf stderr
    # — in der EXE also in fleech-cli.log. Der Fehler kommt ohnehin als Ausnahme.
    con.execute("PRAGMA cipher_log_level = NONE")
    if ist_klartext(pfad):
        log.warning("%s liegt noch unverschluesselt vor — Umstellung beim naechsten "
                    "Start.", pfad.name)
    else:
        con.execute(_schluessel_pragma(schluessel))
    con.execute("PRAGMA secure_delete = ON")
    con.execute("PRAGMA temp_store = MEMORY")
    return con


def oeffnet_mit(pfad: Path, schluessel: bytes) -> bool:
    """Laesst sich die Datei mit diesem Schluessel lesen?"""
    try:
        con = verbinde(pfad, schluessel, nur_lesen=True)
        try:
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
            return True
        finally:
            con.close()
    except Exception:
        return False


def _zaehle(con) -> dict:
    tabellen = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")]
    return {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
            for t in tabellen}


def _raeume_abbruch_auf(pfad: Path, schluessel: bytes) -> None:
    """Reste einer unterbrochenen Umstellung aufloesen (Reihenfolge in `umstellen`)."""
    neu = pfad.with_name(pfad.name + ".neu")
    alt = pfad.with_name(pfad.name + ".klartext")
    if neu.exists():
        # Unfertig und ungeprueft — verschluesselt, also ohne Ueberschreiben weg.
        neu.unlink()
    if alt.exists():
        if not pfad.exists():
            os.replace(alt, pfad)     # vor dem Tausch abgebrochen: zurueck an Ort
        elif ist_verschluesselt(pfad) and oeffnet_mit(pfad, schluessel):
            sicher_loeschen(alt)      # nach dem Tausch abgebrochen: Rest tilgen
        else:
            log.warning("%s und %s liegen beide vor — unklar, welche gilt; beide "
                        "bleiben unangetastet.", pfad.name, alt.name)


def umstellen(pfad: Path, schluessel: bytes) -> dict | None:
    """Klartext-Datenbank verschluesseln. Rueckgabe: {Tabelle: Zeilen} oder None
    (nichts zu tun).

    Reihenfolge, damit ein Abbruch an JEDER Stelle nichts verliert:
    1. Verschluesselte Kopie `.neu` anlegen und gegenpruefen (Integritaet und
       Zeilenzahl je Tabelle) — scheitert das, bleibt alles, wie es war.
    2. Original → `.klartext`, Kopie → Original.
    3. `.klartext` und die Nebendateien des Originals ueberschreiben und loeschen.
    """
    from sqlcipher3 import dbapi2

    pfad = Path(pfad)
    _raeume_abbruch_auf(pfad, schluessel)
    if not ist_klartext(pfad):
        return None
    neu = pfad.with_name(pfad.name + ".neu")
    alt = pfad.with_name(pfad.name + ".klartext")

    quelle = dbapi2.connect(str(pfad), timeout=10.0)
    try:
        # WAL zurueck in die Hauptdatei, sonst fehlten die letzten Eintraege.
        quelle.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        zaehlung = _zaehle(quelle)
        ziel = str(neu).replace("'", "''")
        quelle.execute(f"ATTACH DATABASE '{ziel}' AS tresor KEY "
                       f"\"x'{schluessel.hex()}'\"")
        quelle.execute("SELECT sqlcipher_export('tresor')").fetchall()
        quelle.execute("DETACH DATABASE tresor")
    finally:
        quelle.close()

    pruefung = verbinde(neu, schluessel)
    try:
        intakt = pruefung.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        gleich = _zaehle(pruefung) == zaehlung
    finally:
        pruefung.close()
    if not (intakt and gleich):
        neu.unlink()
        raise RuntimeError(f"Verschluesselte Kopie von {pfad.name} weicht ab — "
                           "Original bleibt unveraendert.")

    # Die Nebendateien gehoeren zum KLARTEXT. Bleibt eine -wal neben der neuen
    # Datei liegen, versuchte SQLite sie auf die verschluesselte anzuwenden.
    for endung in _NEBENDATEIEN:
        sicher_loeschen(pfad.with_name(pfad.name + endung))
    os.replace(pfad, alt)
    os.replace(neu, pfad)
    sicher_loeschen(alt)
    return zaehlung
