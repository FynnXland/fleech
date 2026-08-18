"""HistoryStore: Persistenz, Kennzahlen, Serien-Berechnung, Korrektur-Diff."""

import datetime as dt
import time

import pytest

from fleech.history import DictationRecord, HistoryStore, corrected_word_count


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / "history.db")


def rec(ts=None, raw="also äh der test läuft gut", cleaned="Der Test läuft gut.",
        seconds=4.0, app="Code.exe", **kw):
    return DictationRecord(ts=ts if ts is not None else time.time(), raw=raw,
                           cleaned=cleaned, audio_seconds=seconds, app=app, **kw)


def days_ago(n: int) -> float:
    d = dt.datetime.now() - dt.timedelta(days=n)
    return d.timestamp()


# -- Korrektur-Diff -------------------------------------------------------------------


def test_corrected_word_count_filler_removal():
    assert corrected_word_count("also äh das projekt läuft halt gut",
                                "Das Projekt läuft gut.") >= 3  # also, äh, halt


def test_corrected_word_count_identical_is_zero():
    assert corrected_word_count("das passt so", "das passt so") == 0


def test_corrected_word_count_self_correction():
    n = corrected_word_count("treffen wir uns dienstag nein freitag",
                             "treffen wir uns freitag")
    assert n >= 2  # "dienstag nein" entfernt


# -- Persistenz + Verlauf ----------------------------------------------------------------


def test_add_and_recent_roundtrip(store):
    store.add(rec(cleaned="Erster Eintrag."))
    store.add(rec(cleaned="Zweiter Eintrag.", app="comet.exe"))
    entries = store.recent()
    assert len(entries) == 2
    assert entries[0]["cleaned"] == "Zweiter Eintrag."  # neueste zuerst
    assert entries[0]["app"] == "comet.exe"
    assert entries[0]["words"] == 2


def test_recent_limit(store):
    for i in range(10):
        store.add(rec(cleaned=f"Eintrag {i}."))
    assert len(store.recent(limit=3)) == 3


def test_clear(store):
    store.add(rec())
    store.clear()
    assert store.recent() == []
    assert store.stats().total_dictations == 0


# -- Statistiken ---------------------------------------------------------------------


def test_stats_totals_and_wpm(store):
    store.add(rec(cleaned="eins zwei drei vier fünf", seconds=2.0))   # 5 Woerter/2s
    store.add(rec(cleaned="sechs sieben acht neun zehn", seconds=2.0))
    s = store.stats()
    assert s.total_dictations == 2
    assert s.total_words == 10
    assert s.wpm == pytest.approx(150.0)  # 10 Woerter in 4 s


def test_stats_app_usage_shares(store):
    store.add(rec(cleaned="a b c d e f", app="Code.exe"))       # 6 Woerter
    store.add(rec(cleaned="g h", app="comet.exe"))              # 2 Woerter
    usage = store.stats().app_usage
    assert usage[0][0] == "Code.exe"
    assert usage[0][2] == pytest.approx(0.75)
    assert usage[1][2] == pytest.approx(0.25)


def test_stats_empty_store(store):
    s = store.stats()
    assert s.total_words == 0 and s.wpm == 0.0 and s.streak == 0
    assert s.app_usage == [] and s.daily_counts == {}
    assert s.top_words == []
    assert s.productive_daypart == "" and s.productive_weekday == ""


# -- Haeufigste Woerter ("Lieblingswort") --------------------------------------------


def test_top_words_filters_stopwords_and_counts(store):
    store.add(rec(cleaned="Der Server war heute Nacht offline."))
    store.add(rec(cleaned="Der Server ist jetzt wieder online."))
    words = dict((w, c) for w, c, _share in store.stats().top_words)
    assert words["server"] == 2
    assert "der" not in words  # Stopwort ausgeblendet
    assert "war" not in words
    assert "ist" not in words


def test_top_words_ranked_and_share_relative_to_top(store):
    store.add(rec(cleaned="Server Server Server"))
    store.add(rec(cleaned="Server Client Client"))
    top = store.stats().top_words
    assert top[0] == ("server", 4, pytest.approx(1.0))
    assert top[1] == ("client", 2, pytest.approx(0.5))


def test_top_words_case_insensitive_and_min_length(store):
    store.add(rec(cleaned="Ok Ok ok, das ist ein A B Test Test."))
    words = dict((w, c) for w, c, _share in store.stats().top_words)
    assert words["ok"] == 3        # Gross-/Kleinschreibung zusammengefasst
    assert words["test"] == 2
    assert "a" not in words        # zu kurz (1 Zeichen)
    assert "b" not in words


def test_top_words_public_method_supports_higher_limit(store):
    # Zehn EIGENSTAENDIGE Woerter (kein Ziffern-Suffix — _WORD_RE matcht nur
    # Buchstaben, "wort1"/"wort2" wuerden beide auf "wort" zusammenfallen).
    woerter = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta",
              "theta", "iota", "kappa"]
    for w in woerter:
        store.add(rec(cleaned=f"{w} {w}"))
    assert len(store.stats().top_words) == 8   # Karte: Standard-Limit
    assert len(store.top_words(limit=20)) == 10  # Detail-Dialog: hoeheres Limit


# -- Deine Muster (produktivste Tageszeit/Wochentag) ---------------------------------


def test_productivity_pattern_needs_minimum_data(store):
    for _ in range(3):  # unter MIN_DICTATIONS_FOR_PATTERN (5)
        store.add(rec())
    s = store.stats()
    assert s.productive_daypart == ""
    assert s.productive_weekday == ""


def test_productivity_pattern_detects_daypart_and_weekday(store):
    monday_morning = dt.datetime(2024, 1, 1, 9, 0, 0)    # Montag, morgens
    tuesday_evening = dt.datetime(2024, 1, 2, 20, 0, 0)  # Dienstag, abends
    for _ in range(5):
        store.add(rec(ts=monday_morning.timestamp(), cleaned="a b c d e f g h"))
    for _ in range(2):
        store.add(rec(ts=tuesday_evening.timestamp(), cleaned="a b"))
    s = store.stats()
    assert s.productive_daypart == "morgens"
    assert s.productive_weekday == "Montag"


def test_productivity_pattern_vergleicht_je_stunde_nicht_als_summe(store):
    """F-B8: Die Faecher sind unterschiedlich breit (nachts 6 h, nachmittags 4 h) —
    als reine Summe gewinnt strukturell das breitere Fach, selbst wenn es je
    Stunde weniger traegt. Hier: nachts=30 Woerter (5/h), nachmittags=24 (6/h) —
    ohne Normalisierung wuerde "nachts" faelschlich gewinnen."""
    nachts = dt.datetime(2024, 1, 1, 2, 0, 0)
    nachmittags = dt.datetime(2024, 1, 2, 15, 0, 0)
    for _ in range(3):
        store.add(rec(ts=nachts.timestamp(), cleaned="a b c d e f g h i j"))  # 10 Woerter
    for _ in range(3):
        store.add(rec(ts=nachmittags.timestamp(), cleaned="a b c d e f g h"))  # 8 Woerter
    s = store.stats()
    assert s.productive_daypart == "nachmittags"   # 24/4=6 je h schlaegt 30/6=5 je h


# -- Serie (Streak) ---------------------------------------------------------------------


def test_streak_counts_consecutive_days_including_today(store):
    for n in (0, 1, 2):
        store.add(rec(ts=days_ago(n)))
    s = store.stats()
    assert s.streak == 3
    assert s.longest_streak == 3


def test_streak_survives_quiet_today(store):
    # Heute noch nichts diktiert → Serie (endend gestern) zaehlt weiter.
    for n in (1, 2, 3):
        store.add(rec(ts=days_ago(n)))
    assert store.stats().streak == 3


def test_streak_broken_by_gap(store):
    for n in (0, 1, 4, 5):
        store.add(rec(ts=days_ago(n)))
    s = store.stats()
    assert s.streak == 2          # heute+gestern
    assert s.longest_streak == 2


def test_daily_counts_keyed_by_local_date(store):
    store.add(rec(ts=days_ago(0)))
    store.add(rec(ts=days_ago(0)))
    today = dt.date.today().isoformat()
    assert store.stats().daily_counts[today] == 2


# -- Verarbeitungs-Telemetrie + Schema-Migration ---------------------------------------


def test_latency_median_und_p90_statt_mittelwert(store):
    """F-B4: Ein Mittelwert ueberzeichnet die Erkennung durch Kaltstart-
    Ausreisser und wird durch Diktate ohne Modelllauf (llm_ms=0) nach unten
    verzerrt. Median/p90 werden per Index auf sortierten Listen gegriffen
    (nearest-rank) statt AVG() — hier von Hand nachgerechnet: stt=[200,300,400]
    -> Median=300/p90=400, llm (NUR llm_ms>0)=[400,1200] -> Median=400/p90=1200."""
    store.add(rec(cleaned="a b c", tier="simple", stt_ms=200, llm_ms=400))
    store.add(rec(cleaned="d e f", tier="complex", stt_ms=400, llm_ms=1200, status="fallback"))
    store.add(rec(cleaned="g h", tier="trivial", stt_ms=300, llm_ms=0))
    s = store.stats()
    assert s.stt_median_ms == 300
    assert s.stt_p90_ms == 400
    assert s.llm_median_ms == 400   # NUR llm_ms>0 — die 0 aus "trivial" faellt raus
    assert s.llm_p90_ms == 1200
    assert s.tier_shares["simple"] == pytest.approx(1 / 3)
    assert s.tier_shares["complex"] == pytest.approx(1 / 3)
    assert s.fallback_rate == pytest.approx(1 / 3)


def test_stats_without_latency_data(store):
    store.add(rec(cleaned="alt"))  # stt_ms/llm_ms default 0
    s = store.stats()
    assert s.stt_median_ms == 0 and s.llm_median_ms == 0
    assert s.stt_p90_ms == 0 and s.llm_p90_ms == 0
    assert s.fallback_rate == 0.0


def test_schema_migration_adds_latency_columns(tmp_path):
    import sqlite3

    from fleech.history import HistoryStore

    # Alt-Datenbank OHNE die neuen Spalten anlegen (Stand vor v1.1.x).
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE dictations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL, raw TEXT NOT NULL, cleaned TEXT NOT NULL,
            words INTEGER NOT NULL, corrected INTEGER NOT NULL DEFAULT 0,
            audio_seconds REAL NOT NULL, app TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL DEFAULT 'cleanup', tier TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ok'
        );
        INSERT INTO dictations (ts, raw, cleaned, words, audio_seconds)
        VALUES (1700000000, 'alt', 'Alt.', 1, 2.0);
    """)
    con.commit()
    con.close()

    store = HistoryStore(db)          # Migration laeuft im Konstruktor
    store.add(rec(cleaned="neu", stt_ms=150, llm_ms=250))
    s = store.stats()
    assert s.total_dictations == 2    # Altbestand blieb erhalten
    assert s.stt_median_ms == 150


# -- Aktionable Auswertungen ------------------------------------------------------


def _store_with(tmp_path, entries):
    """entries: [(raw, cleaned, status, llm_ms, alter_in_tagen)]"""
    import time

    from fleech.history import DictationRecord, HistoryStore

    store = HistoryStore(tmp_path / "actionable.db")
    now = time.time()
    for raw, cleaned, status, llm_ms, age in entries:
        store.add(DictationRecord(
            ts=now - age * 86400, raw=raw, cleaned=cleaned, audio_seconds=5.0,
            app="Test.exe", mode="cleanup", tier="simple", status=status,
            stt_ms=200, llm_ms=llm_ms,
        ))
    return store


def test_top_corrections_finds_systematic_misrecognitions(tmp_path):
    """Systematisch falsch erkannte Fachbegriffe sollen als Regel-Vorschlag
    auftauchen — Einmal-Treffer dagegen nicht (Rauschen)."""
    store = _store_with(tmp_path, [
        ("wir nutzen kimano dafuer", "wir nutzen Kimono dafuer", "ok", 900, 0),
        ("das kimano laeuft gut", "das Kimono laeuft gut", "ok", 900, 0),
        ("kimano ist super", "Kimono ist super", "ok", 900, 1),
        ("einmaliger fehlgriff hier", "einmaliger Ausrutscher hier", "ok", 900, 1),
    ])
    hits = store.top_corrections()
    assert ("kimano", "Kimono", 3) in hits
    assert all(w != "fehlgriff" for w, _r, _c in hits)   # nur 1x → kein Vorschlag


def test_top_corrections_ignores_short_and_identical(tmp_path):
    store = _store_with(tmp_path, [
        ("der ball war rund", "die ball war rund", "ok", 900, 0),   # <4 Zeichen
        ("der ball war rund", "die ball war rund", "ok", 900, 0),
    ])
    assert store.top_corrections() == []


def test_fallback_trend_compares_windows(tmp_path):
    """Steigende Fallback-Quote ist das Signal fuer eine kaputte Modell-Anbindung."""
    entries = [("roh text hier", "Roher Text hier.", "fallback", 0, 0) for _ in range(4)]
    entries += [("roh text hier", "Sauberer Text.", "ok", 900, 0)]
    entries += [("roh text hier", "Sauberer Text.", "ok", 900, 5) for _ in range(4)]
    store = _store_with(tmp_path, entries)
    recent, previous, seen = store.fallback_trend(days=3)
    assert seen == 5
    assert recent == pytest.approx(0.8)
    assert previous == 0.0


def test_latency_by_day_groups_and_skips_zero(tmp_path):
    store = _store_with(tmp_path, [
        ("a b c d", "A b c d.", "ok", 5000, 0),
        ("a b c d", "A b c d.", "ok", 1000, 0),
        ("a b c d", "A b c d.", "ok", 0, 1),      # ohne LLM → zaehlt nicht
    ])
    days = store.latency_by_day(days=14)
    assert len(days) == 1 and days[0][1] == 3000   # Mittel aus 5000/1000


def test_top_corrections_aligns_equal_length_blocks(tmp_path):
    """Neben dem falschen Begriff wird oft auch das Nachbarwort korrigiert — difflib
    macht daraus EINEN Block. Bei gleicher Laenge lassen sich die Woerter sicher
    positionsweise zuordnen, sonst ginge der eigentliche Fund verloren."""
    store = _store_with(tmp_path, [
        ("wir nutzen kimano dafuer heute", "wir nutzen Kimono dafür heute", "ok", 900, 0),
        ("wir nutzen kimano dafuer heute", "wir nutzen Kimono dafür heute", "ok", 900, 0),
    ])
    hits = dict(((w, r), c) for w, r, c in store.top_corrections())
    assert hits.get(("kimano", "Kimono")) == 2
    assert hits.get(("dafuer", "dafür")) == 2


def test_top_corrections_skips_rewritten_passages(tmp_path):
    """Unterschiedlich lange Bloecke sind umgebaute Passagen — daraus eine Wort-Regel
    zu raten waere gefaehrlich, sie wuerde ja kuenftig automatisch angewendet."""
    store = _store_with(tmp_path, [
        ("also der server ist irgendwie weg", "Der Server fehlt", "ok", 900, 0),
        ("also der server ist irgendwie weg", "Der Server fehlt", "ok", 900, 0),
    ])
    assert store.top_corrections() == []


def test_top_corrections_ignoriert_umformulierende_modi(tmp_path):
    """F-1/Befund 1a: In math/math_mix/prompt/email/command ist eine Abweichung
    ABSICHT (Formel, Umschreibung, Befehlsantwort), keine Fehlerkennung — z. B.
    "omega" -> "$\\Omega$" aus dem Formel-Modus. Ein automatischer Vorschlag
    daraus wuerde kuenftig JEDES Diktat verfaelschen."""
    store = HistoryStore(tmp_path / "h.db")
    for _ in range(2):
        store.add(rec(raw="omega ist wichtig hier",
                      cleaned="$\\Omega$ ist wichtig dort", mode="math"))
    assert store.top_corrections() == []


def test_top_corrections_ignoriert_typografische_apostrophe(tmp_path):
    """F-1/Befund 1b: "geht's" (ASCII-Apostroph, wie das Roh-Transkript es liefert)
    vs. "geht’s" (typografischer Apostroph nach der Bereinigung) ist keine
    Fehlerkennung, sondern derselbe Text in zwei Schreibweisen — nach
    Normalisierung identisch, darf also keine Regel vorschlagen."""
    store = _store_with(tmp_path, [
        ("na klar geht's doch", "na klar geht’s doch", "ok", 900, 0),
        ("na klar geht's doch", "na klar geht’s doch", "ok", 900, 0),
    ])
    assert store.top_corrections() == []


def test_top_corrections_konsistenz_verwirft_grammatikfaelle(tmp_path):
    """F-1/Befund 1c: Ein Wort, das im eigenen bereinigten Textbestand selbst
    haeufig als "richtig" steht, ist eine Fehlerkennung nie — Grammatik/Flexion
    (kann/wird/...), keine Systematik. Die Schwelle 0,5 laesst echte
    Fehlerkennungen durch (Wort taucht sonst so gut wie nie korrekt auf)."""
    entries = [
        # "kann" wird 2x zu "können" "korrigiert" (gleich lange Bloecke), steht
        # aber daneben zigfach unveraendert als "kann" im bereinigten Text —
        # klassischer Grammatikfall, der NICHT vorgeschlagen werden darf.
        ("man kann das schon machen", "man können das schon machen", "ok", 900, 0),
        ("man kann das schon machen", "man können das schon machen", "ok", 900, 0),
    ]
    # Viele weitere Zeilen, in denen "kann" im bereinigten Text KORREKT steht.
    entries += [("egal", "Ich kann das gut.", "ok", 900, 0) for _ in range(20)]
    store = _store_with(tmp_path, entries)
    assert all(w != "kann" for w, _r, _c in store.top_corrections())


def test_top_corrections_laesst_echte_fehlerkennung_durch(tmp_path):
    """Gegenprobe zum Konsistenz-Test: Ein Wort, das NIE korrekt im bereinigten
    Text auftaucht, ist die Sorte Fund, fuer die die Karte gebaut ist."""
    store = _store_with(tmp_path, [
        ("wir nutzen matrize dafuer", "wir nutzen Matrix dafuer", "ok", 900, 0),
        ("die matrize ist neu", "die Matrix ist neu", "ok", 900, 0),
    ])
    hits = dict(((w, r), c) for w, r, c in store.top_corrections())
    assert hits.get(("matrize", "Matrix")) == 2


# -- Befehlsarten ------------------------------------------------------------------

def test_command_kinds_klassifiziert_die_anweisung(tmp_path):
    store = HistoryStore(tmp_path / "h.db")
    for raw in ("Redax, lösch den letzten Satz.",
                "Redax, entferne das bitte.",
                "Redax, übersetze das ins Englische.",
                "Redax, fass das mal zusammen.",
                "Redax, mach das etwas formeller."):
        store.add(rec(raw=raw, cleaned="…", mode="command"))
    # Diktate ohne Befehls-Modus zaehlen nie mit.
    store.add(rec(raw="lösch das mal", cleaned="…", mode="cleanup"))
    assert dict(store.command_kinds()) == {
        "Löschen": 2, "Übersetzen": 1, "Kürzen": 1, "Umformulieren": 1,
    }


def test_command_kinds_ohne_befehle(tmp_path):
    store = HistoryStore(tmp_path / "h.db")
    store.add(rec(raw="ganz normal", cleaned="Ganz normal.", mode="cleanup"))
    assert store.command_kinds() == []


def test_command_kinds_folgt_dem_zeitraum(tmp_path):
    """F-B5: Die Karte darf nicht "immer" zeigen, ohne es zu sagen — `since`
    grenzt genau wie bei `stats()`/`top_words()` ein."""
    import time

    store = HistoryStore(tmp_path / "h.db")
    jetzt = time.time()
    store.add(rec(ts=jetzt - 40 * 86400, raw="Redax, lösch das.",
                  cleaned="…", mode="command"))
    store.add(rec(ts=jetzt - 600, raw="Redax, entferne das.",
                  cleaned="…", mode="command"))

    heute = dict(store.command_kinds(since=jetzt - 86400))
    alle = dict(store.command_kinds())
    assert heute == {"Löschen": 1}
    assert alle == {"Löschen": 2}


def test_stats_zeitraum_grenzt_wirklich_ein(tmp_path):
    """Der Zeitraum ist der Grund, warum die Insights nicht mehr eingefroren wirken:
    Ohne ihn rechnet jede Zahl ueber ALLE Diktate, und nach ein paar hundert bewegt
    ein neues den Schnitt rechnerisch nicht mehr."""
    import time

    store = HistoryStore(tmp_path / "h.db")
    jetzt = time.time()
    # Zwei alte Diktate (langsam gesprochen) und ein frisches (schnell).
    langsam = " ".join(["wort"] * 60)      # 60 Wörter in 60 s = 60 WPM
    schnell = " ".join(["wort"] * 90)      # 90 Wörter in 30 s = 180 WPM
    store.add(DictationRecord(ts=jetzt - 40 * 86400, raw="alt", cleaned=langsam,
                              audio_seconds=60.0, app="A.exe"))
    store.add(DictationRecord(ts=jetzt - 10 * 86400, raw="mittel", cleaned=langsam,
                              audio_seconds=60.0, app="B.exe"))
    store.add(DictationRecord(ts=jetzt - 3600, raw="neu", cleaned=schnell,
                              audio_seconds=30.0, app="C.exe"))

    alle = store.stats()
    heute = store.stats(since=jetzt - 86400)
    monat = store.stats(since=jetzt - 30 * 86400)

    assert alle.total_dictations == 3
    assert heute.total_dictations == 1
    assert monat.total_dictations == 2
    # Und die Kennzahl bewegt sich wirklich: 180 WPM heute gegen 84 ueber alles.
    assert round(heute.wpm) == 180
    assert round(alle.wpm) < round(heute.wpm)
    # App-Nutzung folgt dem Zeitraum mit.
    assert [a for a, _w, _s in heute.app_usage] == ["C.exe"]


def test_stats_serie_bleibt_ungefiltert(tmp_path):
    """Die Straehne lebt vom langen Verlauf — „Serie ueber die letzten 24 Stunden"
    waere sinnlos. Sie ist bewusst vom Zeitraum ausgenommen."""
    import time

    store = HistoryStore(tmp_path / "h.db")
    jetzt = time.time()
    for tage in (5, 3, 0):
        store.add(DictationRecord(ts=jetzt - tage * 86400, raw="x", cleaned="Text",
                                  audio_seconds=5.0))

    heute = store.stats(since=jetzt - 86400)
    assert len(heute.daily_counts) == 3          # alle drei Tage, nicht nur heute


def test_stats_lifetime_words_bleibt_ungefiltert(tmp_path):
    """F-B2/F-B3: Die Meilenstein-Karte vergleicht IMMER gegen alles je Diktierte,
    nicht gegen den gewaehlten Zeitraum — sonst behauptet sie auf "Heute"
    faelschlich, kaum etwas erreicht zu sein, obwohl die Lebenszeit-Summe laengst
    viel weiter ist. Bewusst ungefiltert wie die Serie (Docstring von stats())."""
    import time

    store = HistoryStore(tmp_path / "h.db")
    jetzt = time.time()
    store.add(DictationRecord(ts=jetzt - 40 * 86400, raw="alt", cleaned="a b c d e",
                              audio_seconds=5.0))         # 5 Woerter, ausserhalb "Heute"
    store.add(DictationRecord(ts=jetzt - 600, raw="neu", cleaned="f g",
                              audio_seconds=5.0))         # 2 Woerter, "Heute"

    heute = store.stats(since=jetzt - 86400)
    assert heute.total_words == 2          # zeitraum-gefiltert
    assert heute.lifetime_words == 7       # ungefiltert: 5 + 2


def test_stats_korrekturen_nur_mode_cleanup(tmp_path):
    """F-B11: Umformulierende Modi (prompt/math/…) aendern Text ABSICHTLICH — das
    ist keine "Korrektur von Fleech" und darf die Kennzahl nicht aufblaehen. Sie
    zaehlen stattdessen als eigene Zeile (`non_cleanup_dictations`)."""
    store = HistoryStore(tmp_path / "h.db")
    store.add(rec(mode="cleanup"))                         # corrected: aus rec()-Diff
    store.add(rec(raw="wandle das um bitte hier",
                  cleaned="Ein komplett umformulierter Satz mit vielen Woertern.",
                  mode="prompt"))
    s = store.stats()
    cleanup_only = corrected_word_count(
        "also äh der test läuft gut", "Der Test läuft gut.")
    assert s.corrected_words == cleanup_only    # NICHT die prompt-Zeile mit
    assert s.non_cleanup_dictations == 1
    assert s.total_dictations == 2


def test_top_words_folgt_dem_zeitraum(tmp_path):
    import time

    store = HistoryStore(tmp_path / "h.db")
    jetzt = time.time()
    store.add(DictationRecord(ts=jetzt - 40 * 86400, raw="a",
                              cleaned="Sonnenblume Sonnenblume Sonnenblume",
                              audio_seconds=5.0))
    store.add(DictationRecord(ts=jetzt - 600, raw="b",
                              cleaned="Kaffeemaschine Kaffeemaschine Kaffeemaschine",
                              audio_seconds=5.0))

    woerter_heute = [w for w, _c, _s in store.top_words(since=jetzt - 86400)]
    assert "kaffeemaschine" in [w.lower() for w in woerter_heute]
    assert "sonnenblume" not in [w.lower() for w in woerter_heute]
