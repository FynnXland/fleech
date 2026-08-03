"""Lokale Diktat-Historie + Statistiken (SQLite in %APPDATA%/Fleech/history.db).

Grundlage fuer Home (Verlauf) und Insights (Kennzahlen) — komplett lokal, keine
Cloud, kein Login. Alle Flow-artigen Kennzahlen sind aus den Rohdaten ableitbar:
Woerter/Minute (Woerter / Sprechdauer), Korrekturen (Diff roh↔bereinigt),
App-Nutzung (Ziel-App pro Diktat), Serie (Tage mit >= 1 Diktat).

Datenschutz: abschaltbar (Einstellungen → Allgemein) und jederzeit loeschbar.
Schreibzugriffe kommen aus dem Pipeline-Worker-Thread — jede Operation nutzt ihre
eigene kurzlebige Verbindung (sqlite3 ist dafuer sicher, Volumen ist winzig).
"""

from __future__ import annotations

import datetime as _dt
import difflib
import logging
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .usersettings import SETTINGS_DIR

log = logging.getLogger(__name__)

DB_PATH = SETTINGS_DIR / "history.db"

# Deutsche Funktions-/Fuellwoerter — fuer "Haeufigste Woerter" ausgeblendet, sonst
# dominieren Artikel/Pronomen jede Rangliste bedeutungslos (bewusst eigenstaendig
# von den Korrektur-Markern in textutils.py, andere Aufgabe: Frequenz statt Erkennung).
STOPWORDS_DE = frozenset("""
der die das den dem des ein eine einen einem einer eines
und oder aber doch dass daß wenn weil also wie was wer wo wann warum
ist sind war waren sein hat haben hatte hatten wird werden wurde wurden
kann können könnte muss müssen musste soll sollen sollte will wollen wollte würde würden
ich du er sie es wir ihr mich dich sich uns euch mir dir ihm ihnen
mein meine dein deine seine ihre unser unsere euer eure
auf in im an am aus bei bis durch für gegen mit nach ohne seit über um
unter von vor während wegen zu zum zur zwischen
nicht kein keine auch noch nur schon so sehr mehr dann ja nein halt mal
man ganz immer jetzt hier da dort als alle alles etwas
diese dieser dieses diesen diesem jede jeder jedes
""".split())

_WORD_RE = re.compile(r"[a-zA-ZäöüÄÖÜß]+")


def _tokenize_words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


# Tageszeit-Buckets fuer die "Deine Muster"-Karte — grob genug, um mit wenigen
# Diktaten schon ein stabiles Muster zu ergeben (einzelne Stunden waeren bei
# kleiner Historie reines Zufallsrauschen).
def _daypart_for_hour(hour: int) -> str:
    if 5 <= hour < 11:
        return "morgens"
    if 11 <= hour < 14:
        return "mittags"
    if 14 <= hour < 18:
        return "nachmittags"
    if 18 <= hour < 23:
        return "abends"
    return "nachts"


_WEEKDAY_NAMES_DE = {
    "0": "Sonntag", "1": "Montag", "2": "Dienstag", "3": "Mittwoch",
    "4": "Donnerstag", "5": "Freitag", "6": "Samstag",
}

# Unter dieser Gesamtzahl an Diktaten wird kein Muster ausgewiesen — bei zu wenig
# Daten waere jede Aussage ("du bist morgens am produktivsten") nur Zufallsrauschen.
MIN_DICTATIONS_FOR_PATTERN = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dictations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    raw TEXT NOT NULL,
    cleaned TEXT NOT NULL,
    words INTEGER NOT NULL,
    corrected INTEGER NOT NULL DEFAULT 0,
    audio_seconds REAL NOT NULL,
    app TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'cleanup',
    tier TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ok',
    stt_ms INTEGER NOT NULL DEFAULT 0,
    llm_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_dictations_ts ON dictations(ts);
"""

# Additive Migrationen fuer Bestands-Datenbanken (CREATE TABLE IF NOT EXISTS greift
# nur bei neuen DBs): fehlende Spalten werden beim Start nachgezogen.
_MIGRATION_COLUMNS = {
    "stt_ms": "INTEGER NOT NULL DEFAULT 0",
    "llm_ms": "INTEGER NOT NULL DEFAULT 0",
}


def corrected_word_count(raw: str, cleaned: str) -> int:
    """Wie viele Woerter des Roh-Transkripts wurden veraendert/entfernt (Fuellwoerter,
    Selbstkorrekturen, Erkennungsfehler)? Wort-Diff, case-insensitiv."""
    a = raw.lower().split()
    b = cleaned.lower().split()
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    return sum(
        i2 - i1 for tag, i1, i2, _j1, _j2 in matcher.get_opcodes()
        if tag in ("replace", "delete")
    )


@dataclass
class DictationRecord:
    ts: float
    raw: str
    cleaned: str
    audio_seconds: float
    app: str = ""
    mode: str = "cleanup"
    tier: str = ""
    status: str = "ok"
    stt_ms: int = 0
    llm_ms: int = 0


@dataclass
class Stats:
    total_dictations: int = 0
    total_words: int = 0
    total_audio_seconds: float = 0.0
    corrected_words: int = 0
    wpm: float = 0.0                     # Sprechtempo: Woerter / Sprechminute
    app_usage: list = None               # [(app, words, anteil 0..1)]
    top_words: list = None               # [(wort, anzahl, anteil am haeufigsten 0..1)]
    daily_counts: dict = None            # {"YYYY-MM-DD": anzahl}
    streak: int = 0                      # aktuelle Serie (Tage, bis heute/gestern)
    longest_streak: int = 0
    # "Deine Muster": leer ("") solange < MIN_DICTATIONS_FOR_PATTERN Diktate vorliegen.
    productive_daypart: str = ""         # morgens | mittags | nachmittags | abends | nachts
    productive_weekday: str = ""         # "Montag".."Sonntag"
    # Verarbeitungs-Telemetrie (lokal): Durchschnittslatenzen + Routing-/Fallback-Bild.
    avg_stt_ms: int = 0
    avg_llm_ms: int = 0
    tier_shares: dict = None             # {"trivial"|"simple"|"complex": anteil 0..1}
    fallback_rate: float = 0.0           # Anteil Diktate mit status "fallback"


class HistoryStore:
    def __init__(self, path: Path | None = None):
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)
            existing = {row[1] for row in con.execute("PRAGMA table_info(dictations)")}
            for column, decl in _MIGRATION_COLUMNS.items():
                if column not in existing:
                    con.execute(f"ALTER TABLE dictations ADD COLUMN {column} {decl}")
                    log.info("Historie: Spalte %s nachgezogen (Migration).", column)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    # -- Schreiben -----------------------------------------------------------------

    def add(self, record: DictationRecord) -> None:
        try:
            with self._connect() as con:
                con.execute(
                    "INSERT INTO dictations (ts, raw, cleaned, words, corrected, "
                    "audio_seconds, app, mode, tier, status, stt_ms, llm_ms) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        record.ts, record.raw, record.cleaned,
                        len(record.cleaned.split()),
                        corrected_word_count(record.raw, record.cleaned),
                        record.audio_seconds, record.app, record.mode,
                        record.tier, record.status,
                        int(record.stt_ms), int(record.llm_ms),
                    ),
                )
        except Exception:
            log.exception("Historie: Eintrag konnte nicht gespeichert werden.")

    def clear(self) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM dictations")

    def delete(self, entry_id: int) -> None:
        """Einzelnen Verlaufseintrag entfernen (Home-Timeline)."""
        try:
            with self._connect() as con:
                con.execute("DELETE FROM dictations WHERE id = ?", (entry_id,))
        except Exception:
            log.exception("Historie: Eintrag %s konnte nicht geloescht werden.", entry_id)

    # -- Lesen ----------------------------------------------------------------------

    def recent(self, limit: int = 50) -> list[dict]:
        with self._connect() as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                # Bewusst OHNE `raw`: Die Liste zeigt 50 Eintraege, der Rohtext
                # wird nur fuer den Einzelfall gebraucht (Detailansicht,
                # Nachbearbeitung) — dafuer gibt es `raw_text(id)`.
                "SELECT id, ts, cleaned, app, mode, words FROM dictations "
                "ORDER BY ts DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- Aktionable Auswertungen (Insights-Vorschlaege) --------------------------------
    #
    # Kennzahlen allein sagen dem Nutzer nicht, was er TUN kann. Diese drei Abfragen
    # liefern Beobachtungen, aus denen eine konkrete Handlung folgt.

    def top_corrections(self, limit: int = 5, scan: int = 300,
                        min_count: int = 2) -> list[tuple[str, str, int]]:
        """Haeufigste Ein-Wort-Korrekturen (roh → bereinigt) der letzten `scan` Diktate.

        Systematisch falsch erkannte Fachbegriffe tauchen hier oben auf und lassen
        sich mit einem Klick als Woerterbuch-Regel uebernehmen. Einmal-Treffer
        (`min_count`) bleiben draussen — die sind Rauschen, keine Systematik.
        """
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT raw, cleaned FROM dictations ORDER BY ts DESC LIMIT ?",
                    (max(1, scan),),
                ).fetchall()
        except Exception:
            log.exception("Historie: Korrektur-Auswertung fehlgeschlagen.")
            return []
        pairs: Counter = Counter()
        for raw, cleaned in rows:
            before_words, after_words = (raw or "").split(), (cleaned or "").split()
            matcher = difflib.SequenceMatcher(
                a=[w.lower() for w in before_words],
                b=[w.lower() for w in after_words],
                autojunk=False,
            )
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                # Nur GLEICH LANGE Ersetzungsbloecke: dann lassen sich die Woerter
                # positionsweise sicher zuordnen (haeufig, weil neben dem falschen
                # Begriff oft auch das Nachbarwort korrigiert wird). Bloecke
                # unterschiedlicher Laenge sind umgebaute Passagen — daraus eine
                # Wort-Regel zu raten waere gefaehrlich, sie wuerde ja kuenftig
                # automatisch angewendet.
                if tag != "replace" or (i2 - i1) != (j2 - j1):
                    continue
                for offset in range(i2 - i1):
                    wrong = before_words[i1 + offset].strip(".,;:!?\"'„“()")
                    right = after_words[j1 + offset].strip(".,;:!?\"'„“()")
                    if len(wrong) < 4 or len(right) < 4 \
                            or wrong.lower() == right.lower():
                        continue
                    pairs[(wrong.lower(), right)] += 1
        return [(wrong, right, count)
                for (wrong, right), count in pairs.most_common(limit)
                if count >= min_count]

    def fallback_trend(self, days: int = 3) -> tuple[float, float, int]:
        """(Quote aktuell, Quote davor, Diktate im aktuellen Fenster).

        Steigt die Fallback-Quote ueber mehrere Tage, stimmt meist etwas mit der
        Modell-Anbindung nicht (Ollama aus, Modell entladen, Endpoint umgestellt)."""
        window = max(1, days) * 86400
        now = _dt.datetime.now().timestamp()
        try:
            with self._connect() as con:
                def quote(since: float, until: float) -> tuple[float, int]:
                    total, bad = con.execute(
                        "SELECT COUNT(*), COALESCE(SUM(status = 'fallback'), 0) "
                        "FROM dictations WHERE ts >= ? AND ts < ?", (since, until),
                    ).fetchone()
                    return ((bad / total) if total else 0.0), int(total or 0)

                recent, count = quote(now - window, now + 1)
                previous, _ = quote(now - 2 * window, now - window)
        except Exception:
            log.exception("Historie: Fallback-Trend nicht ermittelbar.")
            return 0.0, 0.0, 0
        return recent, previous, count

    def latency_by_day(self, days: int = 14) -> list[tuple[str, int]]:
        """[(Datum, Ø KI-Latenz in ms)] — macht Modell-Kaltstarts sichtbar."""
        since = _dt.datetime.now().timestamp() - max(1, days) * 86400
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT date(ts, 'unixepoch', 'localtime') d, AVG(llm_ms) "
                    "FROM dictations WHERE ts >= ? AND llm_ms > 0 "
                    "GROUP BY d ORDER BY d", (since,),
                ).fetchall()
        except Exception:
            log.exception("Historie: Latenz-Verlauf nicht ermittelbar.")
            return []
        return [(day, int(avg or 0)) for day, avg in rows]

    # Modi, die den einzigen Cloud-Pfad von Fleech benutzen: das multimodale
    # Formel-Modell. Alles andere laeuft vollstaendig auf diesem Rechner.
    CLOUD_MODES = ("math", "math_mix", "prompt_math_mix")

    def privacy_split(self) -> tuple[int, int]:
        """(Diktate gesamt, davon ueber den Formel-Cloud-Pfad).

        Fleechs Kernversprechen ist „laeuft lokal" — dann muss auch nachpruefbar
        sein, wie oft das NICHT galt. Die Zahl ehrlich zu zeigen ist mehr wert als
        ein Werbe-Siegel."""
        try:
            with self._connect() as con:
                placeholders = ",".join("?" * len(self.CLOUD_MODES))
                total = con.execute("SELECT COUNT(*) FROM dictations").fetchone()[0]
                cloud = con.execute(
                    f"SELECT COUNT(*) FROM dictations WHERE mode IN ({placeholders})",
                    self.CLOUD_MODES,
                ).fetchone()[0]
        except Exception:
            log.exception("Historie: Privacy-Verteilung nicht ermittelbar.")
            return 0, 0
        return int(total or 0), int(cloud or 0)

    def command_kinds(self, limit: int = 4) -> list[tuple[str, int]]:
        """[(Befehlsart, Anzahl)] — welche Befehle nutzt du wirklich?

        Klassifiziert wird das ROH-Transkript (die gesprochene Anweisung), nicht
        das Ergebnis: nur dort steht, was verlangt wurde."""
        from .commands import classify_command

        counts: Counter = Counter()
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT raw FROM dictations WHERE mode = 'command' AND raw != ''"
                ).fetchall()
        except Exception:
            log.exception("Historie: Befehlsarten nicht ermittelbar.")
            return []
        for (raw,) in rows:
            counts[classify_command(raw)] += 1
        return counts.most_common(limit)

    def last_seen_apps(self) -> dict:
        """{prozessname_klein: letzter Zeitstempel} — wann wurde zuletzt in diese
        App diktiert? Grundlage fuer den „lange nicht gesehen"-Hinweis auf der
        Profilseite."""
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT LOWER(app), MAX(ts) FROM dictations WHERE app != '' "
                    "GROUP BY LOWER(app)"
                ).fetchall()
        except Exception:
            log.exception("Historie: Letzte App-Sichtungen nicht ermittelbar.")
            return {}
        return {app: float(ts or 0) for app, ts in rows}

    def raw_text(self, entry_id: int) -> str:
        """Roh-Transkript eines Eintrags (Detail-Dialog: „Roh"-Abschnitt)."""
        try:
            with self._connect() as con:
                row = con.execute(
                    "SELECT raw FROM dictations WHERE id = ?", (entry_id,)
                ).fetchone()
            return row[0] if row else ""
        except Exception:
            log.exception("Historie: Rohtext zu Eintrag %s nicht lesbar.", entry_id)
            return ""

    def stats(self, calendar_days: int = 98, since: float | None = None) -> Stats:
        """Kennzahlen, wahlweise auf einen Zeitraum begrenzt.

        `since` = Unix-Zeit; None = gesamte Historie. Der Zeitraum ist kein
        Zierrat: Ohne ihn rechnet jede Zahl ueber ALLE Diktate, und nach einigen
        hundert bewegt ein einzelnes neues den Schnitt rechnerisch nicht mehr —
        die Karten sehen dann eingefroren aus, obwohl sie korrekt sind.

        Die SERIE (daily_counts/streak) bleibt bewusst UNGEFILTERT: Eine Strähne
        ueber die letzten 24 Stunden waere sinnlos, sie lebt vom langen Verlauf.
        """
        where = " WHERE ts >= ?" if since else ""
        p: tuple = (since,) if since else ()

        def und(bedingung: str) -> str:
            return (where + " AND " + bedingung) if where else " WHERE " + bedingung

        with self._connect() as con:
            total, words, seconds, corrected = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(words),0), COALESCE(SUM(audio_seconds),0),"
                " COALESCE(SUM(corrected),0) FROM dictations" + where, p
            ).fetchone()
            usage_rows = con.execute(
                "SELECT app, SUM(words) w FROM dictations" + und("app != ''") +
                " GROUP BY app ORDER BY w DESC", p
            ).fetchall()
            # Ungefiltert — siehe Docstring.
            daily_rows = con.execute(
                "SELECT date(ts, 'unixepoch', 'localtime') d, COUNT(*) c "
                "FROM dictations GROUP BY d ORDER BY d"
            ).fetchall()
            hour_rows = con.execute(
                "SELECT strftime('%H', ts, 'unixepoch', 'localtime') h, "
                "COALESCE(SUM(words),0) w FROM dictations" + where + " GROUP BY h", p
            ).fetchall()
            weekday_rows = con.execute(
                "SELECT strftime('%w', ts, 'unixepoch', 'localtime') wd, "
                "COALESCE(SUM(words),0) w FROM dictations" + where + " GROUP BY wd", p
            ).fetchall()
            latency_row = con.execute(
                "SELECT AVG(stt_ms), AVG(llm_ms) FROM dictations" + und("stt_ms > 0"), p
            ).fetchone()
            tier_rows = con.execute(
                "SELECT tier, COUNT(*) FROM dictations" + und("tier != ''") +
                " GROUP BY tier", p
            ).fetchall()
            fallback_count = con.execute(
                "SELECT COUNT(*) FROM dictations" + und("status = 'fallback'"), p
            ).fetchone()[0]

        stats = Stats(
            total_dictations=total, total_words=words,
            total_audio_seconds=seconds, corrected_words=corrected,
            wpm=(words / (seconds / 60.0)) if seconds > 0 else 0.0,
            app_usage=[], top_words=[], daily_counts={}, tier_shares={},
        )
        stats.avg_stt_ms = int(latency_row[0] or 0)
        stats.avg_llm_ms = int(latency_row[1] or 0)
        tier_total = sum(c for _t, c in tier_rows) or 1
        stats.tier_shares = {t: c / tier_total for t, c in tier_rows}
        stats.fallback_rate = (fallback_count / total) if total else 0.0
        usage_total = sum(w for _a, w in usage_rows) or 1
        stats.app_usage = [(a, w, w / usage_total) for a, w in usage_rows]
        stats.top_words = self.top_words(limit=8, since=since)
        stats.daily_counts = {d: c for d, c in daily_rows}
        stats.streak, stats.longest_streak = self._streaks(set(stats.daily_counts))

        if total >= MIN_DICTATIONS_FOR_PATTERN:
            daypart_words = Counter()
            for h, w in hour_rows:
                daypart_words[_daypart_for_hour(int(h))] += w
            if daypart_words:
                stats.productive_daypart = max(daypart_words, key=daypart_words.get)
            if weekday_rows:
                best_wd, _w = max(weekday_rows, key=lambda row: row[1])
                stats.productive_weekday = _WEEKDAY_NAMES_DE[best_wd]
        return stats

    def top_words(self, limit: int = 8, since: float | None = None) -> list[tuple[str, int, float]]:
        """Haeufigste Woerter ueber die gesamte Historie (ohne Fuellwoerter). Anteil
        ist relativ zum haeufigsten Wort (fuer eine Balken-Rangliste wie App-Nutzung),
        NICHT ein Anteil an der Gesamtwortzahl — bei freiem Text waere Letzteres
        fuer jedes Wort winzig und optisch uninteressant. `limit` hoeher gesetzt fuer
        die Detail-Ansicht (Insights-Karte selbst zeigt nur die ersten 5)."""
        with self._connect() as con:
            if since:
                cleaned_texts = con.execute(
                    "SELECT cleaned FROM dictations WHERE ts >= ?", (since,)).fetchall()
            else:
                cleaned_texts = con.execute("SELECT cleaned FROM dictations").fetchall()
        counter = Counter()
        for (text,) in cleaned_texts:
            for w in _tokenize_words(text):
                if len(w) >= 2 and w not in STOPWORDS_DE:
                    counter[w] += 1
        top = counter.most_common(limit)
        if not top:
            return []
        max_count = top[0][1]
        return [(w, c, c / max_count) for w, c in top]

    @staticmethod
    def _streaks(days: set[str]) -> tuple[int, int]:
        """(aktuelle Serie, laengste Serie). Aktuell = endet heute oder gestern
        (heute noch nichts diktiert bricht die Serie nicht sofort)."""
        if not days:
            return 0, 0
        parsed = sorted(_dt.date.fromisoformat(d) for d in days)
        longest = run = 1
        for prev, cur in zip(parsed, parsed[1:]):
            run = run + 1 if (cur - prev).days == 1 else 1
            longest = max(longest, run)
        today = _dt.date.today()
        current = 0
        probe = today if today in parsed else today - _dt.timedelta(days=1)
        while probe in parsed:
            current += 1
            probe -= _dt.timedelta(days=1)
        return current, longest
