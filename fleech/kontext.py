"""Projekt-Gedaechtnis: gelerntes Fachvokabular je App und Fenster.

Zweck ist die ERKENNUNG, nicht die Formulierung. Fleech merkt sich die
Fachbegriffe, Eigennamen und Schreibweisen, die in einem Zusammenhang vorkommen,
und gibt sie beim naechsten Diktat als Whisper-Priming mit — denselben Weg, den
das handgepflegte Woerterbuch schon nimmt (`vocab_initial_prompt`). Wirkung:
„MCP-Server" statt „MCP Server", „Cauchy-Schwarz-Ungleichung" statt Kauderwelsch.

BEWUSST KEIN INHALT INS SPRACHMODELL. Eine mitgegebene Projekt-Zusammenfassung
waere maechtiger, kostete aber bei JEDEM Diktat Zeit und gaebe dem Modell
Material, aus dem es ergaenzen kann — genau die Halluzinationen, gegen die vier
Filter in der Pipeline stehen. Vokabular kann nichts erfinden: Es verschiebt nur
die Wahrscheinlichkeit, ein tatsaechlich gesprochenes Wort richtig zu schreiben.

## Woran ein Kontext haengt

Am Fenstertitel — aber nicht am ganzen. Titel sind zusammengesetzt:

    „pipeline.py - Fleech - Visual Studio Code"

Der ganze Titel als Schluessel waere wertlos (jede Datei ein eigener Kontext),
der Prozessname allein zu grob (alles in VS Code ein Topf). Deshalb wird der
Titel in SEGMENTE zerlegt und der Begriff unter jedem gespeichert. Was stabil
bleibt (das Projekt „Fleech"), sammelt ueber viele Diktate viel; was wechselt
(der Dateiname), sammelt wenig und faellt im Ranking von selbst hinten runter.
Kein Raten, welches Segment das Projekt ist — die Nutzung entscheidet.

Dazu kommt der App-weite Bestand als Grundstock (der „Haupt-Kontext"): Was in
dieser Anwendung ueberall gilt, steht auch dann zur Verfuegung, wenn das Fenster
neu ist.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path

from . import tresor
from .platformpaths import user_data_dir

log = logging.getLogger(__name__)

DB_PATH = user_data_dir() / "kontext.db"

# Wie viele Begriffe hoechstens zurueckgegeben werden. Das Whisper-Kontextfenster
# teilt sich der Priming-Satz mit Woerterbuch und Signalwort — mehr
# Begriffe verdraengen dort die handgepflegten, die praeziser sind.
MAX_BEGRIFFE = 25

# Ab wie vielen Treffern ein Begriff ueberhaupt geprimt wird. Einmal-Treffer sind
# ueberwiegend Erkennungsfehler („Willkommens-Rueck-Finn-Haar" — echt aus dem
# Verlauf). Die wieder einzuspeisen wuerde den Fehler verfestigen.
MIN_TREFFER = 2

# Nach dieser Zeit ohne neuen Treffer zaehlt ein Begriff nicht mehr. Projekte
# enden; ein Vokabular, das nie vergisst, primt irgendwann auf Vergangenes.
VERFALL_TAGE = 90

_MAX_SEGMENTE = 4          # laengere Titel tragen nur noch Rauschen bei
_MIN_SEGMENT_LEN = 3
_MAX_BEGRIFF_LEN = 40

# Titel-Trenner, wie Anwendungen sie real verwenden.
_TRENNER = re.compile(r"\s+[-–—|·:]\s+")

# Segmente, die nichts ueber den Inhalt sagen. Der Anwendungsname selbst ist
# bereits der App-weite Schluessel — ihn zusaetzlich als Segment zu fuehren waere
# derselbe Topf unter zwei Namen.
_GENERISCH = {
    "visual studio code", "google chrome", "chrome", "mozilla firefox", "firefox",
    "microsoft edge", "edge", "obsidian", "discord", "claude", "microsoft word",
    "word", "explorer", "neuer tab", "new tab", "startseite", "home",
    "einstellungen", "settings", "unbenannt", "untitled", "posteingang", "inbox",
}

_WORT = re.compile(r"[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß.\-]{2,}")


def _ist_fachbegriff(wort: str) -> bool:
    """Traegt das Wort ein hartes Signal, das es von normaler Sprache abhebt?

    Drei Signale, an 1189 echten Diktaten geprueft: Binnenversalien (PySide6,
    MCP-Server), eine Ziffer im Wort (gemma3, x_3) und ein Punkt im Wortinneren
    (share.finland.xyz, Cloud.md).

    Getestet und VERWORFEN wurde „kommt nur in dieser App vor": Das lieferte
    „Wahrscheinlichkeit", „Waffe", „Abend" — gewoehnliche Woerter, die zufaellig
    nur in einem Fenster fielen. Solche zu primen verschlechtert die Erkennung,
    weil es Whisper in ihre Richtung zieht.
    """
    kern = wort.strip(".-")
    if not (3 <= len(kern) <= _MAX_BEGRIFF_LEN):
        return False
    if kern.isdigit():
        return False
    binnenversal = any(c.isupper() for c in kern[1:])
    ziffer = any(c.isdigit() for c in kern)
    punkt_innen = "." in kern.strip(".")
    return binnenversal or ziffer or punkt_innen


def begriffe_aus_text(text: str) -> list[str]:
    """Fachbegriffe eines Diktats, Reihenfolge stabil, ohne Doubletten."""
    gesehen: set[str] = set()
    treffer = []
    for roh in _WORT.findall(text or ""):
        kern = roh.strip(".-")
        if not _ist_fachbegriff(kern):
            continue
        if kern.lower() in gesehen:
            continue
        gesehen.add(kern.lower())
        treffer.append(kern)
    return treffer


def titel_segmente(titel: str) -> list[str]:
    """Fenstertitel → Schluessel-Segmente (klein, ohne generische Anteile)."""
    segmente = []
    for teil in _TRENNER.split(titel or ""):
        teil = teil.strip().strip("*").strip()
        klein = teil.lower()
        if len(teil) < _MIN_SEGMENT_LEN or klein in _GENERISCH:
            continue
        if klein not in segmente:
            segmente.append(klein)
    return segmente[:_MAX_SEGMENTE]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS begriffe (
    app      TEXT NOT NULL,
    segment  TEXT NOT NULL,          -- "" = app-weiter Grundstock (Haupt-Kontext)
    begriff  TEXT NOT NULL,
    klein    TEXT NOT NULL,
    treffer  INTEGER NOT NULL DEFAULT 1,
    zuletzt  REAL NOT NULL,
    PRIMARY KEY (app, segment, klein)
);
CREATE INDEX IF NOT EXISTS idx_begriffe_app ON begriffe(app, segment);
"""


class KontextSpeicher:
    """Gelerntes Vokabular, dauerhaft in einer eigenen, verschluesselten SQLite-Datei
    (SQLCipher, `fleech/tresor` — Begriffe je Fenstertitel verraten viel).

    Eigene Datei statt einer Tabelle in `history.db`: Der Verlauf laesst sich in
    den Einstellungen loeschen, ohne dass das Gelernte mitverschwindet — und
    umgekehrt. Zwei Lebensdauern, zwei Dateien.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or DB_PATH
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)

    def _connect(self):
        con = tresor.verbinde(self.path, tresor.KONTEXT)
        con.execute("PRAGMA journal_mode=WAL")
        return con

    # -- Lernen ---------------------------------------------------------------------

    def lerne(self, app: str, titel: str, text: str) -> int:
        """Begriffe eines Diktats aufnehmen. Rueckgabe: Anzahl gelernter Begriffe.

        Gespeichert wird unter jedem Titel-Segment UND app-weit — dieselbe
        Beobachtung, in zwei Aufloesungen. Fehler sind hier kein Ereignis: Ein
        nicht gelerntes Diktat ist ein verpasster Vorteil, kein Schaden.
        """
        app = (app or "").strip().lower()
        begriffe = begriffe_aus_text(text)
        if not app or not begriffe:
            return 0
        jetzt = time.time()
        schluessel = [""] + titel_segmente(titel)
        try:
            with self._lock, self._connect() as con:
                for segment in schluessel:
                    for begriff in begriffe:
                        con.execute(
                            "INSERT INTO begriffe (app, segment, begriff, klein,"
                            " treffer, zuletzt) VALUES (?,?,?,?,1,?)"
                            " ON CONFLICT(app, segment, klein) DO UPDATE SET"
                            "   treffer = treffer + 1, zuletzt = excluded.zuletzt,"
                            # Schreibweise nachziehen: Spaetere Nennungen sind
                            # meist die korrigierten (Woerterbuch/LLM haben
                            # gewirkt), und geprimt werden soll die richtige.
                            "   begriff = excluded.begriff",
                            (app, segment, begriff, begriff.lower(), jetzt),
                        )
        except Exception:
            log.debug("Kontext-Lernen fehlgeschlagen.", exc_info=True)
            return 0
        return len(begriffe)

    # -- Abrufen --------------------------------------------------------------------

    def priming_begriffe(self, app: str, titel: str = "",
                         limit: int = MAX_BEGRIFFE) -> list[str]:
        """Begriffe fuer das naechste Diktat in dieser App/diesem Fenster.

        Reihenfolge: erst die des konkreten Fensters (spezifisch), dann der
        app-weite Grundstock. Genau die zwei Ebenen aus dem Wunsch — ein
        Haupt-Kontext, aus dem heraus in den passenden Unterkontext gewechselt
        wird, nur ohne dass jemand sie von Hand pflegen muss.
        """
        app = (app or "").strip().lower()
        if not app:
            return []
        grenze = time.time() - VERFALL_TAGE * 86400
        segmente = titel_segmente(titel)
        gesehen: set[str] = set()
        ergebnis: list[str] = []
        try:
            with self._lock, self._connect() as con:
                for stufe in (segmente, [""]):
                    if not stufe:
                        continue
                    platzhalter = ",".join("?" * len(stufe))
                    rows = con.execute(
                        f"SELECT begriff, klein, SUM(treffer) AS n FROM begriffe"
                        f" WHERE app = ? AND segment IN ({platzhalter})"
                        f"   AND zuletzt >= ? GROUP BY klein"
                        f" HAVING n >= ? ORDER BY n DESC, MAX(zuletzt) DESC",
                        (app, *stufe, grenze, MIN_TREFFER),
                    ).fetchall()
                    for begriff, klein, _n in rows:
                        if klein in gesehen:
                            continue
                        gesehen.add(klein)
                        ergebnis.append(begriff)
                        if len(ergebnis) >= limit:
                            return ergebnis
        except Exception:
            log.debug("Kontext-Abruf fehlgeschlagen.", exc_info=True)
        return ergebnis

    # -- Einsicht und Pflege ----------------------------------------------------------

    def kontexte(self, app: str = "") -> list[tuple[str, str, int]]:
        """[(app, segment, anzahl_begriffe)] — fuer die Anzeige in der Oberflaeche.

        Ohne Einsicht waere das Gelernte eine Blackbox: Man saehe nie, warum ein
        Wort plotzlich anders geschrieben wird.
        """
        grenze = time.time() - VERFALL_TAGE * 86400
        sql = ("SELECT app, segment, COUNT(*) FROM begriffe WHERE zuletzt >= ?"
               " AND treffer >= ?")
        args: list = [grenze, MIN_TREFFER]
        if app:
            sql += " AND app = ?"
            args.append(app.strip().lower())
        sql += " GROUP BY app, segment ORDER BY COUNT(*) DESC"
        try:
            with self._lock, self._connect() as con:
                return [tuple(r) for r in con.execute(sql, args).fetchall()]
        except Exception:
            log.debug("Kontext-Uebersicht fehlgeschlagen.", exc_info=True)
            return []

    def alle_begriffe(self, app: str = "") -> list[tuple[str, int]]:
        """[(begriff, treffer)] — die Rohliste des Gelernten, haeufigste zuerst.

        Nur das app-weite Segment (`segment = ''`): `lerne` legt jeden Begriff
        zusaetzlich unter jedem Titel-Segment ab, ueber alles summiert waere jeder
        Begriff also mehrfach gezaehlt — und zwar unterschiedlich oft, je nachdem
        wie viele Fenstertitel er gesehen hat. Fuer die Frage „welche Schreibweise
        ist haeufiger?" (V-14) waere das eine verzerrte Zahl.

        Bewusst OHNE Verfalls- und Trefferfilter (anders als `priming_begriffe`):
        Hier geht es ums Zeigen und Aufraeumen, nicht ums Primen — was der Nutzer
        loeschen koennen soll, muss er auch sehen.
        """
        sql = ("SELECT begriff, SUM(treffer) FROM begriffe WHERE segment = ''")
        args: list = []
        if app:
            sql += " AND app = ?"
            args.append(app.strip().lower())
        sql += " GROUP BY klein ORDER BY SUM(treffer) DESC, begriff"
        try:
            with self._lock, self._connect() as con:
                return [(str(b), int(n)) for b, n in con.execute(sql, args).fetchall()]
        except Exception:
            log.debug("Kontext-Begriffe nicht lesbar.", exc_info=True)
            return []

    def vergiss(self, app: str = "", segment: str | None = None,
                begriff: str | None = None) -> int:
        """Gelerntes loeschen. Ohne Argumente: alles. Rueckgabe: Anzahl Zeilen.

        `begriff` loescht EINEN Begriff (in allen Segmenten, sonst primt ihn das
        Titel-Segment weiter). Genau das fehlte bisher: Die Oberflaeche konnte nur
        alles vergessen, obwohl in `kontext.db` einzelne Hoerfehler stehen
        (`Cloud-Code`, `FLEACH`) — wer die loswerden wollte, verlor das ganze
        gelernte Vokabular mit (Befund H-B3).
        """
        sql, args = "DELETE FROM begriffe", []
        bedingungen = []
        if app:
            bedingungen.append("app = ?")
            args.append(app.strip().lower())
        if segment is not None:
            bedingungen.append("segment = ?")
            args.append(segment.strip().lower())
        if begriff:
            bedingungen.append("klein = ?")
            args.append(begriff.strip().lower())
        if bedingungen:
            sql += " WHERE " + " AND ".join(bedingungen)
        try:
            with self._lock, self._connect() as con:
                return con.execute(sql, args).rowcount
        except Exception:
            log.debug("Kontext-Loeschen fehlgeschlagen.", exc_info=True)
            return 0

    def aufraeumen(self) -> int:
        """Verfallene Eintraege entfernen. Rueckgabe: Anzahl geloeschter Zeilen."""
        grenze = time.time() - VERFALL_TAGE * 86400
        try:
            with self._lock, self._connect() as con:
                return con.execute("DELETE FROM begriffe WHERE zuletzt < ?",
                                   (grenze,)).rowcount
        except Exception:
            log.debug("Kontext-Aufraeumen fehlgeschlagen.", exc_info=True)
            return 0


def oeffne(aktiv: bool = True) -> "KontextSpeicher | None":
    """Eine eigene Verbindung fuer die Oberflaeche — `None`, wenn es nicht geht.

    Eigene Verbindung und nicht die der Pipeline: Die laeuft in einem anderen
    Thread, und SQLite-Verbindungen gehoeren dem, der sie oeffnet. `aktiv=False`
    (Gedaechtnis abgeschaltet) liefert bewusst `None`, damit die aufrufende Stelle
    nicht zusaetzlich die Einstellung pruefen muss.
    """
    if not aktiv:
        return None
    try:
        return KontextSpeicher()
    except Exception:
        log.debug("Gedaechtnis nicht lesbar.", exc_info=True)
        return None


def erstbefuellung(speicher: "KontextSpeicher", history_db: Path | None = None,
                   max_diktate: int = 3000) -> int:
    """Einmalig aus dem vorhandenen Diktat-Verlauf lernen.

    Ohne das faengt das Gedaechtnis bei null an und braucht Wochen, bis es
    traegt — obwohl der Verlauf die Antwort laengst enthaelt. Gemessen an 1189
    echten Diktaten: 3,7 s, danach stehen die richtigen Begriffe je App bereit.

    Laeuft nur, wenn noch NICHTS gelernt wurde: Ein zweiter Durchlauf wuerde die
    Trefferzahlen verdoppeln und damit die Rangfolge verfaelschen. Der Verlauf
    kennt keinen Fenstertitel — gelernt wird deshalb app-weit, als Grundstock.
    """
    from .history import DB_PATH as HISTORY_DB

    pfad = history_db or HISTORY_DB
    if not Path(pfad).is_file():
        return 0
    try:
        with speicher._lock, speicher._connect() as con:
            vorhanden = con.execute("SELECT 1 FROM begriffe LIMIT 1").fetchone()
        if vorhanden:
            return 0
    except Exception:
        log.debug("Erstbefuellung: Bestandspruefung fehlgeschlagen.", exc_info=True)
        return 0

    try:
        con = tresor.verbinde(Path(pfad), tresor.VERLAUF, nur_lesen=True)
        rows = con.execute(
            "SELECT app, cleaned FROM dictations WHERE cleaned != '' AND app != ''"
            " ORDER BY ts DESC LIMIT ?", (max_diktate,)).fetchall()
        con.close()
    except Exception:
        log.debug("Erstbefuellung: Verlauf nicht lesbar.", exc_info=True)
        return 0

    gelernt = 0
    for app, text in rows:
        gelernt += speicher.lerne(app, "", text)
    if gelernt:
        log.info("Projekt-Gedaechtnis aus dem Verlauf gefuellt: %d Nennungen "
                 "aus %d Diktaten.", gelernt, len(rows))
    return gelernt
