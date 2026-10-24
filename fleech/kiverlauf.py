"""Der KI-Austausch je Diktat im Verlauf: Eingabe, System-Prompt, Antwort.

Liegt in derselben verschluesselten `history.db` wie die Diktate (`history.py`) und
lebt genauso lange: Geht ein Diktat (Einzelloeschung, Aufbewahrungsfrist, „Verlauf
loeschen"), gehen seine Aufrufe mit — `aufraeumen()` laeuft nach jedem Loeschen.

Der System-Prompt steht nur EINMAL in der Datei (`ki_prompts`, Schluessel ist sein
Hash): Allein `prompts/cleanup.md` hat mehrere KB, je Diktat abgelegt waere er
der Grossteil der Datenbank, obwohl er sich fast nie aendert. Profil-Vorgaben
und Formel-Zusaetze machen daraus eine Handvoll Varianten, nicht mehr.

Kennt weder Pfade noch die Verbindung — `history.py` reicht sie herein.
"""

from __future__ import annotations

import hashlib

SCHEMA = """
CREATE TABLE IF NOT EXISTS ki_prompts (
    hash TEXT PRIMARY KEY,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ki_aufrufe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diktat INTEGER NOT NULL,
    nr INTEGER NOT NULL,
    anbieter TEXT NOT NULL DEFAULT '',
    modell TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL DEFAULT '',
    eingabe TEXT NOT NULL,
    antwort TEXT NOT NULL DEFAULT '',
    fehler TEXT NOT NULL DEFAULT '',
    ms INTEGER NOT NULL DEFAULT 0,
    abgeschnitten INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_ki_aufrufe_diktat ON ki_aufrufe(diktat);
"""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def speichere(con, diktat: int, aufrufe) -> None:
    """Die Aufrufe eines Diktats ablegen (in der offenen Transaktion des Eintrags)."""
    for nr, a in enumerate(aufrufe or (), start=1):
        prompt = _hash(a.system) if a.system else ""
        if prompt:
            con.execute("INSERT OR IGNORE INTO ki_prompts (hash, text) VALUES (?, ?)",
                        (prompt, a.system))
        con.execute(
            "INSERT INTO ki_aufrufe (diktat, nr, anbieter, modell, prompt, eingabe, "
            "antwort, fehler, ms, abgeschnitten) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (diktat, nr, a.anbieter, a.modell, prompt, a.eingabe, a.antwort,
             a.fehler, int(a.ms), int(bool(a.abgeschnitten))))


def aufraeumen(con) -> None:
    """Aufrufe ohne Diktat und Prompts ohne Aufruf entfernen."""
    con.execute("DELETE FROM ki_aufrufe WHERE diktat NOT IN (SELECT id FROM dictations)")
    con.execute("DELETE FROM ki_prompts WHERE hash NOT IN "
                "(SELECT DISTINCT prompt FROM ki_aufrufe)")


def fuer_diktat(con, diktat: int) -> list[dict]:
    """Die Aufrufe eines Diktats in ihrer Reihenfolge, der System-Prompt ausgeschrieben."""
    zeilen = con.execute(
        "SELECT a.nr, a.anbieter, a.modell, COALESCE(p.text, ''), a.eingabe, a.antwort, "
        "a.fehler, a.ms, a.abgeschnitten FROM ki_aufrufe a "
        "LEFT JOIN ki_prompts p ON p.hash = a.prompt WHERE a.diktat = ? ORDER BY a.nr",
        (diktat,)).fetchall()
    felder = ("nr", "anbieter", "modell", "system", "eingabe", "antwort", "fehler",
              "ms", "abgeschnitten")
    return [dict(zip(felder, z)) for z in zeilen]


def anzahl(con) -> int:
    return con.execute("SELECT COUNT(*) FROM ki_aufrufe").fetchone()[0]
