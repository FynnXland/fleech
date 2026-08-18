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
import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .usersettings import SETTINGS_DIR

log = logging.getLogger(__name__)

DB_PATH = SETTINGS_DIR / "history.db"

# Deutsche Funktions-/Fuellwoerter — fuer "Haeufigste Woerter" ausgeblendet, sonst
# dominieren Artikel/Pronomen jede Rangliste bedeutungslos (bewusst eigenstaendig
# von den Korrektur-Markern in textfilter.py, andere Aufgabe: Frequenz statt Erkennung).
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


# Stundenbreite je Tageszeit-Fach — die Faecher sind unterschiedlich breit
# (6/3/4/5/6 h). Verglichen wird in `stats()` NICHT die Summe, sondern die Summe
# JE STUNDE, sonst gewinnt strukturell das breiteste Fach, selbst wenn es je
# Stunde weniger traegt (F-B8, aus Bahn F an der echten Historie belegt: "nachts"
# gewann als Summe, obwohl 16 Uhr die staerkste Einzelstunde war).
_DAYPART_HOURS = {"morgens": 6, "mittags": 3, "nachmittags": 4, "abends": 5, "nachts": 6}


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
    llm_ms INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    profile TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    dropped TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_dictations_ts ON dictations(ts);
"""

# Additive Migrationen fuer Bestands-Datenbanken (CREATE TABLE IF NOT EXISTS greift
# nur bei neuen DBs): fehlende Spalten werden beim Start nachgezogen.
_MIGRATION_COLUMNS = {
    "stt_ms": "INTEGER NOT NULL DEFAULT 0",
    "llm_ms": "INTEGER NOT NULL DEFAULT 0",
    # Warum lief es nicht glatt, welches Profil galt, in welchem Fenster, und was
    # haben die Roh-Guards weggeschnitten (H-2/F-9/G-5/C-6). Altzeilen bleiben leer
    # — jede Auswertung muss das aushalten, wie bei `tier`.
    "reason": "TEXT NOT NULL DEFAULT ''",
    "profile": "TEXT NOT NULL DEFAULT ''",
    "title": "TEXT NOT NULL DEFAULT ''",
    "dropped": "TEXT NOT NULL DEFAULT ''",
}


def _percentile(sorted_values: list[int], q: float) -> int:
    """Perzentil per Index (nearest-rank) auf einer BEREITS sortierten Liste —
    kein numpy/scipy noetig, bei ein paar tausend Zeilen unkritisch (Bahn F: rund
    5 ms fuer 1399 Zeilen, gemessen). Ersetzt AVG(): Ein Mittelwert ueberzeichnet
    kurze, haeufige Faelle durch seltene Ausreisser (Kaltstarts) — Median/p90
    zeigen stattdessen, was die Haelfte bzw. neun von zehn Diktaten wirklich
    erlebt haben (F-B4)."""
    if not sorted_values:
        return 0
    idx = max(0, min(len(sorted_values) - 1, math.ceil(q * len(sorted_values)) - 1))
    return int(sorted_values[idx])


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


def treffer_als_markdown(eintraege: list[dict]) -> str:
    """Trefferliste der Verlaufssuche als Markdown (V-12/H-4).

    Je Eintrag eine Ueberschrift „Datum · Uhrzeit · Anwendung" und darunter der
    bereinigte Text — das ist die Form, die sich in Obsidian oder einer Notiz
    weiterverwenden laesst. Bewusst nur die ANGEZEIGTEN Treffer, nicht der ganze
    Bestand: Ein Abzug von tausend Eintraegen beantwortet keine Frage.

    Der Text geht damit unverschluesselt aus der Anwendung heraus — der Hinweis
    dazu steht am Knopf, der diese Funktion aufruft.
    """
    zeilen = [f"# Fleech-Verlauf — {len(eintraege)} Einträge", ""]
    for eintrag in eintraege:
        zeit = _dt.datetime.fromtimestamp(eintrag.get("ts", 0.0))
        app = str(eintrag.get("app", "") or "").strip() or "unbekannte Anwendung"
        zeilen.append(f"## {zeit.strftime('%d.%m.%Y %H:%M')} · {app}")
        zeilen.append("")
        zeilen.append(str(eintrag.get("cleaned", "") or "").strip())
        zeilen.append("")
    return "\n".join(zeilen)


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
    # Der erklaerende Teil: Grund des Rueckfalls/der Kuerzung (leer = lief glatt),
    # wirksames Profil, gekuerzter Fenstertitel und der von den Roh-Guards
    # verworfene Transkript-Schwanz (damit ein Fehlgriff heilbar ist, C-6).
    reason: str = ""
    profile: str = ""
    title: str = ""
    dropped: str = ""


@dataclass
class AppNutzung:
    """Wie in EINER Anwendung diktiert wurde — Grundlage der Zuordnungsvorschlaege.

    `modi` und `profile` sind {Wert: Anzahl}. Beide sind bei Altzeilen leer: die
    Profil-Spalte gibt es erst seit 5.10.4, `mode` traegt nur bei umformulierenden
    Formaten etwas anderes als „cleanup". Jede Auswertung muss das aushalten.
    """

    app: str
    diktate: int = 0
    modi: dict = field(default_factory=dict)
    profile: dict = field(default_factory=dict)


@dataclass
class Stats:
    total_dictations: int = 0
    total_words: int = 0
    total_audio_seconds: float = 0.0
    corrected_words: int = 0             # NUR mode='cleanup' (F-B11 — Umformulieren
                                          # zaehlt separat, siehe non_cleanup_dictations)
    non_cleanup_dictations: int = 0      # Diktate im Zeitraum mit mode != 'cleanup'
    wpm: float = 0.0                     # Sprechtempo: Woerter / Sprechminute
    app_usage: list = None               # [(app, words, anteil 0..1)]
    top_words: list = None               # [(wort, anzahl, anteil am haeufigsten 0..1)]
    daily_counts: dict = None            # {"YYYY-MM-DD": anzahl}
    streak: int = 0                      # aktuelle Serie (Tage, bis heute/gestern)
    longest_streak: int = 0
    # Ungefiltert wie die Serie (F-B2/F-B3) — die Meilenstein-Karte vergleicht immer
    # gegen ALLES je Diktierte, nicht gegen den gewaehlten Zeitraum.
    lifetime_words: int = 0
    # "Deine Muster": leer ("") solange < MIN_DICTATIONS_FOR_PATTERN Diktate vorliegen.
    productive_daypart: str = ""         # morgens | mittags | nachmittags | abends | nachts
    productive_weekday: str = ""         # "Montag".."Sonntag"
    # Verarbeitungs-Telemetrie (lokal): Median/p90 statt Mittelwert (F-B4) — ein
    # Mittelwert ueberzeichnet die Erkennung durch Kaltstart-Ausreisser und wird
    # durch Diktate ohne Modelllauf (llm_ms=0) nach unten verzerrt.
    stt_median_ms: int = 0
    stt_p90_ms: int = 0
    llm_median_ms: int = 0               # NUR llm_ms > 0 (kein echter Lauf sonst)
    llm_p90_ms: int = 0
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
                    "audio_seconds, app, mode, tier, status, stt_ms, llm_ms, "
                    "reason, profile, title, dropped) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        record.ts, record.raw, record.cleaned,
                        len(record.cleaned.split()),
                        corrected_word_count(record.raw, record.cleaned),
                        record.audio_seconds, record.app, record.mode,
                        record.tier, record.status,
                        int(record.stt_ms), int(record.llm_ms),
                        record.reason, record.profile, record.title,
                        record.dropped,
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
                # Nachbearbeitung) — dafuer gibt es `raw_text(id)`. Der
                # erklaerende Teil kommt dagegen mit: Die Timeline markiert
                # damit die Eintraege, bei denen etwas nicht glatt lief.
                "SELECT id, ts, cleaned, app, mode, words, reason, profile, "
                "title, dropped FROM dictations "
                "ORDER BY ts DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def search(self, text: str = "", app: str = "", von: float | None = None,
               bis: float | None = None, limit: int = 200) -> list[dict]:
        """Verlauf durchsuchen — Wortsuche, Anwendung, Zeitraum (V-12/H-4).

        Bis 5.10.4 zeigte Home die 40 letzten Eintraege und sonst nichts; alles
        Aeltere war praktisch unerreichbar (bei 29 Diktaten am Tag also alles ab
        anderthalb Tagen). Gesucht wird ueber ROH- UND bereinigten Text: Wer sich
        an ein gesprochenes Wort erinnert, das die Bereinigung entfernt hat, faende
        seinen Eintrag sonst nicht.

        Bewusst schlichtes `LIKE` und kein FTS5: Bei ein paar tausend Zeilen ist
        der volle Durchlauf im Millisekundenbereich — eine zweite Tabelle, die
        synchron gehalten werden muss, waere Aufwand ohne Wirkung.

        `%` und `_` im Suchtext sind LIKE-Platzhalter und werden maskiert, sonst
        faende die Suche nach „x_3" auch „x13". Gross-/Kleinschreibung ignoriert
        SQLite nur bei ASCII — Umlaute muessen passend geschrieben werden.
        """
        felder = ("SELECT id, ts, cleaned, app, mode, words, reason, profile, "
                  "title, dropped FROM dictations")
        bedingungen: list[str] = []
        args: list = []
        text = (text or "").strip()
        if text:
            muster = "%" + text.replace("\\", "\\\\").replace("%", "\\%") \
                              .replace("_", "\\_") + "%"
            bedingungen.append("(raw LIKE ? ESCAPE '\\' OR cleaned LIKE ? ESCAPE '\\')")
            args += [muster, muster]
        if (app or "").strip():
            bedingungen.append("LOWER(app) = ?")
            args.append(app.strip().lower())
        if von:
            bedingungen.append("ts >= ?")
            args.append(float(von))
        if bis:
            bedingungen.append("ts <= ?")
            args.append(float(bis))
        sql = felder + (" WHERE " + " AND ".join(bedingungen) if bedingungen else "")
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(max(1, int(limit)))
        try:
            with self._connect() as con:
                con.row_factory = sqlite3.Row
                rows = con.execute(sql, args).fetchall()
        except Exception:
            log.exception("Historie: Suche fehlgeschlagen.")
            return []
        return [dict(r) for r in rows]

    def recent_cleaned(self, limit: int = 300) -> list[str]:
        """Die bereinigten Texte der letzten `limit` Diktate — Quelle der
        Schreibvarianten-Auswertung (V-14, `fleech/varianten.py`)."""
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT cleaned FROM dictations WHERE cleaned != '' "
                    "ORDER BY ts DESC LIMIT ?", (max(1, int(limit)),)
                ).fetchall()
        except Exception:
            log.exception("Historie: Texte nicht lesbar.")
            return []
        return [r[0] for r in rows]

    # -- Aktionable Auswertungen (Insights-Vorschlaege) --------------------------------
    #
    # Kennzahlen allein sagen dem Nutzer nicht, was er TUN kann. Diese drei Abfragen
    # liefern Beobachtungen, aus denen eine konkrete Handlung folgt.

    # Modi, in denen ein "replace"-Block KEINE Erkennungskorrektur ist, sondern
    # Absicht: Formeln (LaTeX aus dem Formel-Parser), Umschreibungen (prompt/email)
    # und Befehls-Antworten. Ein Vorschlag daraus wuerde nie eine Fehlerkennung
    # treffen, sondern kuenftig jedes Diktat verfaelschen (F-1/Befund 1).
    _KEIN_KORREKTUR_MODUS = ("math", "math_mix", "prompt", "email", "command")

    # Ab dieser Quote gilt ein Wort als "fast nur als Fehlerkennung gesehen":
    # n_korrekturen / (n_korrekturen + n_vorkommen_im_bereinigten_text). An den
    # echten Daten kalibriert (Bahn F, Befund 1) — 0,5 laesst matrize/kompliment/
    # pfoehne/realen/buchstuhl durch und keinen einzigen Grammatikfall (kann/wird/
    # auch liegen alle unter 0,02).
    _KONSISTENZ_SCHWELLE = 0.5

    @staticmethod
    def _normalisiert_anfuehrung(wort: str) -> str:
        """Typografische Apostrophe/Anfuehrungszeichen auf die ASCII-Form bringen —
        "geht's" vs. "geht’s" ist keine Fehlerkennung, sondern derselbe Text in
        zwei Schreibweisen (F-1)."""
        return wort.translate(str.maketrans({
            "’": "'", "‘": "'", "‚": "'", "“": '"', "„": '"', "”": '"',
        }))

    def top_corrections(self, limit: int = 5, scan: int = 300,
                        min_count: int = 2) -> list[tuple[str, str, int]]:
        """Haeufigste Ein-Wort-Korrekturen (roh → bereinigt) der letzten `scan` Diktate
        (nur Modi, in denen eine Abweichung wirklich eine Fehlerkennung sein kann).

        Systematisch falsch erkannte Fachbegriffe tauchen hier oben auf und lassen
        sich mit einem Klick als Woerterbuch-Regel uebernehmen. Einmal-Treffer
        (`min_count`) bleiben draussen — die sind Rauschen, keine Systematik. Ein
        Konsistenz-Test verwirft zusaetzlich Paare, deren "falsches" Wort im
        eigenen bereinigten Textbestand selbst haeufig vorkommt — das sind fast
        immer Grammatik-/Flexionsfaelle (kann/wird/auch …), keine Erkennungsfehler,
        und eine automatische Regel wuerde sie kuenftig kaputt ersetzen.
        """
        placeholders = ",".join("?" * len(self._KEIN_KORREKTUR_MODUS))
        try:
            with self._connect() as con:
                rows = con.execute(
                    f"SELECT raw, cleaned FROM dictations WHERE mode NOT IN "
                    f"({placeholders}) ORDER BY ts DESC LIMIT ?",
                    (*self._KEIN_KORREKTUR_MODUS, max(1, scan)),
                ).fetchall()
        except Exception:
            log.exception("Historie: Korrektur-Auswertung fehlgeschlagen.")
            return []
        pairs: Counter = Counter()
        # Wie oft steht das (kleingeschriebene) Wort selbst im bereinigten
        # Textbestand — Grundlage fuer den Konsistenz-Test unten.
        cleaned_word_counts: Counter = Counter()
        for raw, cleaned in rows:
            before_words, after_words = (raw or "").split(), (cleaned or "").split()
            for w in after_words:
                cleaned_word_counts[w.strip(".,;:!?\"'„“()").lower()] += 1
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
                    if self._normalisiert_anfuehrung(wrong.lower()) == \
                            self._normalisiert_anfuehrung(right.lower()):
                        continue   # nur typografisches Apostroph/Anfuehrung
                    pairs[(wrong.lower(), right)] += 1
        results = []
        for (wrong, right), count in pairs.most_common():
            if count < min_count:
                continue
            vorkommen = cleaned_word_counts.get(wrong, 0)
            quote = count / (count + vorkommen) if (count + vorkommen) else 0.0
            if quote < self._KONSISTENZ_SCHWELLE:
                continue
            results.append((wrong, right, count))
            if len(results) >= limit:
                break
        return results

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

    def reasons(self, since: float | None = None) -> Counter:
        """{Grund: Anzahl} — warum lief etwas nicht glatt?

        Zaehlt die Rueckfaelle (`status='fallback'`) UND die Kuerzungen am
        Rohtext, denn beide sind erklaerungsbeduerftig: Ein gekuerztes Diktat
        traegt einen gruenen Haken und hat trotzdem Woerter verloren. Ein
        Eintrag kann mehrere Gruende tragen (Trenner `gruende.TRENNER`); die
        werden einzeln gezaehlt, sonst entstuende fuer jede Kombination eine
        eigene Kategorie.

        Altzeilen ohne die Spalte bleiben leer und faerben nichts ein.
        """
        from .gruende import TRENNER

        where = " AND ts >= ?" if since else ""
        p: tuple = (since,) if since else ()
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT reason FROM dictations WHERE reason != ''" + where, p
                ).fetchall()
        except Exception:
            log.exception("Historie: Gruende nicht ermittelbar.")
            return Counter()
        counts: Counter = Counter()
        for (reason,) in rows:
            for teil in str(reason or "").split(TRENNER):
                if teil.strip():
                    counts[teil.strip()] += 1
        return counts

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

    def command_kinds(self, limit: int = 4, since: float | None = None) -> list[tuple[str, int]]:
        """[(Befehlsart, Anzahl)] — welche Befehle nutzt du wirklich, im gewaehlten
        Zeitraum (`since` = Unix-Zeit, None = gesamter Verlauf, F-B5)?

        Klassifiziert wird das ROH-Transkript (die gesprochene Anweisung), nicht
        das Ergebnis: nur dort steht, was verlangt wurde."""
        from .commands import classify_command

        counts: Counter = Counter()
        where = "WHERE mode = 'command' AND raw != ''"
        p: tuple = ()
        if since:
            where += " AND ts >= ?"
            p = (since,)
        try:
            with self._connect() as con:
                rows = con.execute(
                    f"SELECT raw FROM dictations {where}", p
                ).fetchall()
        except Exception:
            log.exception("Historie: Befehlsarten nicht ermittelbar.")
            return []
        for (raw,) in rows:
            counts[classify_command(raw)] += 1
        return counts.most_common(limit)

    def app_nutzung(self) -> tuple[list["AppNutzung"], int]:
        """Je Anwendung: Anzahl Diktate, Modus- und Profil-Verteilung.

        Grundlage der Zuordnungsvorschlaege (V-13/G-4). `stats().app_usage` zaehlt
        WOERTER und beantwortet damit die falsche Frage: Fuer „lohnt sich hier ein
        Profil?" zaehlt, wie oft man dort diktiert, und WAS dabei herauskommt.

        Rueckgabe: (Liste, meistgenutzte zuerst; Gesamtzahl der Diktate mit
        bekannter Anwendung). Die Gruppierung laeuft ueber `LOWER(app)`, weil die
        Regelaufloesung ebenfalls case-insensitiv ist — sonst stuende dieselbe
        Anwendung zweimal mit geteilten Zahlen da.
        """
        try:
            with self._connect() as con:
                rows = con.execute(
                    "SELECT LOWER(app), app, mode, profile, COUNT(*) "
                    "FROM dictations WHERE app != '' "
                    "GROUP BY LOWER(app), app, mode, profile"
                ).fetchall()
        except Exception:
            log.exception("Historie: App-Nutzung nicht ermittelbar.")
            return [], 0
        gesammelt: dict = {}
        for klein, app, mode, profile, anzahl in rows:
            eintrag = gesammelt.get(klein)
            if eintrag is None:
                eintrag = gesammelt[klein] = AppNutzung(app=str(app or ""))
            eintrag.diktate += int(anzahl)
            if mode:
                eintrag.modi[str(mode)] = eintrag.modi.get(str(mode), 0) + int(anzahl)
            if profile:
                eintrag.profile[str(profile)] = \
                    eintrag.profile.get(str(profile), 0) + int(anzahl)
        liste = sorted(gesammelt.values(), key=lambda e: -e.diktate)
        return liste, sum(e.diktate for e in liste)

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
            total, words, seconds = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(words),0), COALESCE(SUM(audio_seconds),0)"
                " FROM dictations" + where, p
            ).fetchone()
            # NUR mode='cleanup' (F-B11): Umformulierende Modi (prompt/math/…)
            # aendern Text absichtlich, das ist keine "Korrektur von Fleech".
            corrected = con.execute(
                "SELECT COALESCE(SUM(corrected),0) FROM dictations" +
                und("mode = 'cleanup'"), p
            ).fetchone()[0]
            non_cleanup = con.execute(
                "SELECT COUNT(*) FROM dictations" + und("mode != 'cleanup'"), p
            ).fetchone()[0]
            # Ungefiltert wie die Serie (F-B2/F-B3) — Lebenszeit-Wortzahl fuer die
            # Meilenstein-Karte, unabhaengig vom gewaehlten Zeitraum.
            lifetime_words = con.execute(
                "SELECT COALESCE(SUM(words),0) FROM dictations"
            ).fetchone()[0]
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
            # Median/p90 statt Mittelwert (F-B4): zwei sortierte Listen statt
            # zweier AVG()s, in Python per Index gegriffen. Die KI-Zeile filtert
            # EIGENSTAENDIG auf llm_ms > 0 (nicht auf stt_ms > 0 wie zuvor) — sonst
            # ziehen Diktate ohne Modelllauf (trivial) den Wert nach unten.
            stt_rows = con.execute(
                "SELECT stt_ms FROM dictations" + und("stt_ms > 0") +
                " ORDER BY stt_ms", p
            ).fetchall()
            llm_rows = con.execute(
                "SELECT llm_ms FROM dictations" + und("llm_ms > 0") +
                " ORDER BY llm_ms", p
            ).fetchall()
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
            non_cleanup_dictations=non_cleanup, lifetime_words=int(lifetime_words or 0),
            wpm=(words / (seconds / 60.0)) if seconds > 0 else 0.0,
            app_usage=[], top_words=[], daily_counts={}, tier_shares={},
        )
        stt_vals = [r[0] for r in stt_rows]
        llm_vals = [r[0] for r in llm_rows]
        stats.stt_median_ms = _percentile(stt_vals, 0.5)
        stats.stt_p90_ms = _percentile(stt_vals, 0.9)
        stats.llm_median_ms = _percentile(llm_vals, 0.5)
        stats.llm_p90_ms = _percentile(llm_vals, 0.9)
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
                # Je Stunde vergleichen, nicht als Summe (F-B8) — sonst gewinnt
                # strukturell das breiteste Fach (z. B. "nachts", 6 h).
                je_stunde = {dp: w / _DAYPART_HOURS[dp] for dp, w in daypart_words.items()}
                stats.productive_daypart = max(je_stunde, key=je_stunde.get)
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
