"""Der Verlauf und das Protokoll sagen, WARUM (Vorschlag V-1 = H-2 + F-9 + G-5).

Bis 5.10.3 kannte der Verlauf zwei Zustaende: `ok` und `fallback`. Alle 19
Rueckfaelle in der echten Datenbank sahen gleich aus — eine Zeitueberschreitung
von Ollama war nicht von einer Sinnumkehr zu unterscheiden, das wirksame Profil
stand nirgends, der Fenstertitel auch nicht, und das Protokoll trug kein Datum.
Diese Datei haelt die Gegenrichtung fest: Grund, Profil, Titel und der verworfene
Rohtext-Schwanz werden erfasst, ueberleben eine bestehende Datenbank und sind
sichtbar.
"""

import sqlite3
import time

import pytest

from fleech import gruende
from fleech.history import DictationRecord, HistoryStore
from tests.pipelinehelpers import (
    AUDIO, CLEAN_NONTRIVIAL, RAW_NONTRIVIAL, FakeLLM, make_pipeline,
)

# Das Schema, wie es VOR dieser Aenderung aussah — Grundlage des Migrationstests.
_ALTES_SCHEMA = """
CREATE TABLE dictations (
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
    status TEXT NOT NULL DEFAULT 'ok'
);
"""


def _spalten(db) -> set:
    con = sqlite3.connect(db)
    try:
        return {r[1] for r in con.execute("PRAGMA table_info(dictations)")}
    finally:
        con.close()


# -- Migration: die bestehende Datenbank wird nachgezogen, nicht neu angelegt ----------


def test_alte_datenbank_bekommt_die_erklaerenden_spalten(tmp_path):
    """1399 echte Diktate stehen in dieser Datei — sie zu verlieren waere ein
    hoher Preis fuer vier Spalten. Deshalb dasselbe additive Muster wie bei
    `stt_ms`/`llm_ms`: ALTER TABLE, keine Neuanlage."""
    db = tmp_path / "history.db"
    con = sqlite3.connect(db)
    con.executescript(_ALTES_SCHEMA)
    con.execute(
        "INSERT INTO dictations (ts, raw, cleaned, words, audio_seconds, app) "
        "VALUES (?,?,?,?,?,?)", (time.time() - 60, "alt roh", "Alt.", 1, 2.0, "alt.exe"),
    )
    con.commit()
    con.close()

    store = HistoryStore(db)
    assert {"reason", "profile", "title", "dropped"} <= _spalten(db)

    store.add(DictationRecord(ts=time.time(), raw="neu roh", cleaned="Neu.",
                              audio_seconds=1.0, reason=gruende.OLLAMA))
    eintraege = store.recent()
    assert len(eintraege) == 2                      # die Altzeile lebt noch
    assert eintraege[0]["reason"] == gruende.OLLAMA
    assert eintraege[1]["cleaned"] == "Alt."
    assert eintraege[1]["reason"] == ""             # Altzeilen bleiben leer


def test_alle_vier_felder_ueberstehen_den_rundlauf(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    store.add(DictationRecord(
        ts=time.time(), raw="roh", cleaned="Bereinigt.", audio_seconds=2.0,
        status="fallback", reason=gruende.KONTEXT_VOLL, profile="KI-Prompt",
        title="pipeline.py — Fleech", dropped="Go Go Go and or",
    ))
    eintrag = store.recent()[0]
    assert eintrag["reason"] == gruende.KONTEXT_VOLL
    assert eintrag["profile"] == "KI-Prompt"
    assert eintrag["title"] == "pipeline.py — Fleech"
    assert eintrag["dropped"] == "Go Go Go and or"


def test_reasons_zaehlt_auch_mehrfachgruende_und_achtet_den_zeitraum(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    jetzt = time.time()
    doppelt = gruende.ENDE_GEKUERZT + gruende.TRENNER + gruende.OLLAMA
    for ts, grund in ((jetzt, gruende.OLLAMA), (jetzt, doppelt),
                      (jetzt, ""), (jetzt - 3 * 86400, gruende.WORTSALAT)):
        store.add(DictationRecord(ts=ts, raw="r", cleaned="C.", audio_seconds=1.0,
                                  reason=grund))
    alle = store.reasons()
    assert alle[gruende.OLLAMA] == 2                 # einzeln + aus der Kombination
    assert alle[gruende.ENDE_GEKUERZT] == 1
    assert alle[gruende.WORTSALAT] == 1
    assert "" not in alle                            # glatte Laeufe zaehlen nicht

    heute = store.reasons(since=jetzt - 86400)
    assert gruende.WORTSALAT not in heute            # aelter als der Zeitraum


# -- Die Pipeline haelt den Grund fest --------------------------------------------------


def test_grund_bei_nicht_erreichbarem_modell():
    p, _llm, _inj = make_pipeline(RAW_NONTRIVIAL,
                                  llm=FakeLLM(error=RuntimeError("connection refused")))
    assert p.process(AUDIO, 16000) == "fallback"
    assert p.last_reason == gruende.OLLAMA


def test_absturz_von_ollama_heisst_nicht_keine_antwort():
    """2026-10-08: Ollama brach beim Rechnen ab (CUDA „out of memory" neben einem
    Spiel) und antwortete mit HTTP 500. Der Verlauf sagte „Ollama hat nicht
    geantwortet" — als waere der Dienst aus. Ein 5xx ist ein Abbruch MIT Antwort."""
    import urllib.error

    fehler = urllib.error.HTTPError("http://127.0.0.1:11434/api/chat", 500,
                                    "Internal Server Error", {}, None)
    p, _llm, _inj = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(error=fehler))
    assert p.process(AUDIO, 16000) == "fallback"
    assert p.last_reason == gruende.OLLAMA_FEHLER
    assert gruende.kurzform(p.last_reason) == "Ollama-Fehler"


def test_grund_bei_leerer_antwort():
    p, _llm, _inj = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply="   "))
    assert p.process(AUDIO, 16000) == "fallback"
    assert p.last_reason == gruende.LEERE_ANTWORT


def test_grund_bei_vollem_kontextfenster():
    llm = FakeLLM(reply="Also, was ich gerade schwierig finde, ist,")
    llm.last_truncated = True
    p, _llm, _inj = make_pipeline(RAW_NONTRIVIAL, llm=llm)
    assert p.process(AUDIO, 16000) == "fallback"
    assert p.last_reason == gruende.KONTEXT_VOLL


def test_grund_bei_gekuerztem_rohtext_auch_ohne_rueckfall():
    """Der wichtigste der vier Faelle: Hier ist das Ergebnis „ok" — gruener Haken,
    Bestaetigungston — und trotzdem sind Woerter verschwunden. Genau solche
    Diktate sahen im Verlauf aus wie jedes andere."""
    sauber = "Okay, das schicke ich dir rüber. Das war's."
    p, _llm, _inj = make_pipeline("Okay, das schicke ich dir rüber. "
                                  + "Das war's. " * 6, llm=FakeLLM(reply=sauber))
    assert p.process(AUDIO, 16000) == "ok"
    assert p.last_reason == gruende.ENDE_GEKUERZT


def test_verworfener_schwanz_wird_mitsamt_grund_aufbewahrt():
    """C-6: Der Schwanz landet spaeter im Verlauf (`dropped`) — ein Fehlgriff der
    Roh-Guards bleibt damit heilbar. Bisher stand er nur im Protokoll."""
    raw = ("Analysiere das dir vorliegende Plugin. Es ist ein Minecraft-Bot, der auf "
           "einem Server läuft. Gib mir praxisnahe Anweisungen, was ich zu tun habe. "
           "Wie teste ich das? Und so weiter und so fort. "
           "Und jetzt Porque dice War, war es ein bisschen Nähan. "
           "Denn Sie ладно, da sind schon mal ein bisschen más schnell.")
    p, _llm, _inj = make_pipeline(raw, llm=FakeLLM(reply=CLEAN_NONTRIVIAL))
    p.process(AUDIO, 16000)
    assert gruende.FREMDE_SCHRIFT in p.last_reason
    assert "ладно" in p.last_dropped_tail


def test_der_grund_wird_zu_beginn_jedes_diktats_geleert():
    """Sonst haftete der Grund des vorigen Diktats am naechsten — und der Verlauf
    behauptete einen Fehler, den es nicht gab."""
    p, _llm, _inj = make_pipeline(RAW_NONTRIVIAL,
                                  llm=FakeLLM(error=RuntimeError("weg")))
    assert p.process(AUDIO, 16000) == "fallback"
    assert p.last_reason == gruende.OLLAMA

    p.cleanup_llm = FakeLLM(reply=CLEAN_NONTRIVIAL)
    assert p.process(AUDIO, 16000) == "ok"
    assert p.last_reason == ""


def test_mehrere_gruende_stehen_getrennt_in_einer_zeile():
    """Ein Diktat kann zweierlei treffen: Rohtext gekuerzt UND danach ein
    Rueckfall. Der zweite Grund darf den ersten nicht ueberschreiben."""
    raw = "Okay, ich schicke dir das Dokument rüber. " + "Das war's. " * 6
    p, _llm, _inj = make_pipeline(raw, llm=FakeLLM(error=RuntimeError("timeout")))
    assert p.process(AUDIO, 16000) == "fallback"
    assert gruende.ENDE_GEKUERZT in p.last_reason
    assert gruende.OLLAMA in p.last_reason
    assert gruende.TRENNER in p.last_reason


def test_kurzform_findet_auch_den_grund_mit_detail():
    lang = gruende.mit_detail(gruende.SINN_GEDREHT, "1 Zahl fehlt")
    assert lang.endswith("1 Zahl fehlt")
    assert gruende.kurzform(lang) == "Sinnumkehr"
    assert gruende.kurzform("") == ""


# -- Protokoll: Datum und Rotation ------------------------------------------------------


def test_das_protokoll_traegt_ein_datum_und_rotiert():
    """CLAUDE.md schreibt Diagnose aus dem Log vor. Ohne Datum je Zeile liess sich
    keine Fundstelle einem Tag zuordnen (11,5 MB, 126.000 Zeilen, nur Uhrzeit)."""
    import pathlib

    quelle = (pathlib.Path(__file__).resolve().parents[1]
              / "fleech" / "__main__.py").read_text(encoding="utf-8")
    assert 'datefmt="%Y-%m-%d %H:%M:%S"' in quelle
    assert "RotatingFileHandler" in quelle
    assert "maxBytes=20 * 1024 * 1024" in quelle
    assert 'SETTINGS_DIR / "fleech.log"' in quelle      # der Name bleibt


# -- Profil: Name im Verlauf, Regeltreffer im Protokoll --------------------------------


def test_das_wirksame_profil_traegt_seinen_namen(qapp):
    import types

    from fleech.ui.desktop import DesktopApp

    profiles = types.SimpleNamespace(enabled=True, items=[
        {"name": "Standard", "default": True, "intervention": "", "tags": [], "apps": []},
        {"name": "Coding", "intervention": "minimal", "tags": [], "apps": ["Code.exe"]},
    ])
    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=profiles), _record_app="Code.exe")
    assert DesktopApp._app_profile_overrides(fake).name == "Coding"

    fake._record_app = "sonstwas.exe"                  # faellt auf das Standardprofil
    assert DesktopApp._app_profile_overrides(fake).name == "Standard"

    profiles.enabled = False
    assert DesktopApp._app_profile_overrides(fake).name == ""


def test_regeltreffer_steht_im_protokoll(qapp, caplog):
    """Befund G-B9: Die automatische Aufloesung protokollierte nichts — ob eine
    Regel griff und welche, war nach dem Diktat nicht feststellbar."""
    import logging
    import types

    from fleech.ui.desktop import DesktopApp

    profiles = types.SimpleNamespace(enabled=True, items=[
        {"name": "Notizen", "intervention": "strong", "tags": [],
         "apps": ["Code.exe :: Tagebuch"]},
    ])
    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=profiles),
        _record_app="Code.exe", _record_title="2026-08-18 — Tagebuch")
    with caplog.at_level(logging.INFO):
        DesktopApp._app_profile_overrides(fake)
    zeilen = [r.getMessage() for r in caplog.records]
    assert any("Notizen" in z and "Code.exe :: Tagebuch" in z for z in zeilen), zeilen


def test_der_verlaufseintrag_traegt_grund_profil_titel_und_verworfenes(qapp, tmp_path):
    """Der ECHTE Weg Profil → Desktop → Verlauf, nicht die Bedingung abgeschrieben:
    Genau daran sind E-2/E-3 monatelang unbemerkt geblieben."""
    import types

    from fleech.profiles import ProfileOverrides
    from fleech.ui.desktop import DesktopApp
    from fleech.ui.windowsfocus import MAX_TITLE_LEN

    store = HistoryStore(tmp_path / "history.db")
    still = types.SimpleNamespace(emit=lambda *a: None)
    fake = types.SimpleNamespace(
        _app_profile_overrides=lambda: ProfileOverrides(name="Coding",
                                                        intervention="minimal"),
        _setze_sprache=lambda s: None,
        settings=types.SimpleNamespace(
            output=types.SimpleNamespace(command_enabled=True),
            general=types.SimpleNamespace(language="de", save_history=True),
        ),
        config=types.SimpleNamespace(audio=types.SimpleNamespace(samplerate=16000)),
        store=store,
        pipeline=types.SimpleNamespace(
            process=lambda audio, samplerate, **kw: "fallback",
            last_mode="cleanup", last_injected="Text", last_raw="roh",
            last_formulas=[], last_dropped_tail="Go Go Go and or",
            last_reason=gruende.OLLAMA, last_error_kind="", last_tier="",
            last_stt_ms=0, last_llm_ms=0,
            injector=types.SimpleNamespace(send_enter=lambda: None),
        ),
        bus=types.SimpleNamespace(
            injection_fallback=still, formula_preview=still, tail_dropped=still,
            transcript_ready=still, history_changed=still, set_state=lambda *a: None,
        ),
        notifier=types.SimpleNamespace(sound=lambda k: None, toast=lambda *a: None),
        _record_app="Code.exe", _record_title="T" * 400, _undo_candidate=None,
        _check_dictionary_candidates=lambda t: None,
        _count_dictionary_usage=lambda t: None,
        _flash_status=lambda t: None,
    )
    DesktopApp._process_locked(fake, b"\x00" * 32)

    eintrag = store.recent()[0]
    assert eintrag["reason"] == gruende.OLLAMA
    assert eintrag["profile"] == "Coding"
    assert eintrag["dropped"] == "Go Go Go and or"
    # Titel unter derselben Schranke wie ueberall sonst — kein zweiter Weg.
    assert len(eintrag["title"]) == MAX_TITLE_LEN


# -- Anzeige ----------------------------------------------------------------------------


def test_der_detail_dialog_zeigt_profil_fenster_grund_und_verworfenes(qapp):
    from PySide6.QtWidgets import QLabel

    from fleech.ui.dialogs import TranscriptDetailDialog

    eintrag = {
        "id": 1, "ts": time.time(), "cleaned": "Der bereinigte Text.", "app": "Code.exe",
        "mode": "cleanup", "words": 3, "reason": gruende.OLLAMA, "profile": "Coding",
        "title": "pipeline.py — Fleech", "dropped": "Go Go Go and or",
    }
    dialog = TranscriptDetailDialog(eintrag, raw="der bereinigte text")
    zusammen = " | ".join(w.text() for w in dialog.findChildren(QLabel))
    assert "Profil: Coding" in zusammen
    assert "Fenster: pipeline.py — Fleech" in zusammen
    assert f"Grund: {gruende.OLLAMA}" in zusammen
    assert "Verworfen (Rohtext-Ende): Go Go Go and or" in zusammen


def test_der_detail_dialog_bleibt_ohne_diese_felder_unveraendert(qapp):
    """Ein glatt gelaufenes Diktat bekommt KEINE Zeilen voller „—"."""
    from PySide6.QtWidgets import QLabel

    from fleech.ui.dialogs import TranscriptDetailDialog

    eintrag = {"id": 1, "ts": time.time(), "cleaned": "Alles gut.", "app": "",
               "mode": "cleanup", "words": 2}
    dialog = TranscriptDetailDialog(eintrag)
    zusammen = " | ".join(w.text() for w in dialog.findChildren(QLabel))
    assert "Profil:" not in zusammen and "Grund:" not in zusammen


def test_die_verlaufszeile_markiert_eintraege_mit_grund(qapp):
    from PySide6.QtWidgets import QLabel

    from fleech.ui.pages.home import HistoryEntryRow

    basis = {"id": 1, "ts": time.time(), "cleaned": "Ein Diktat.", "app": "", "words": 2}
    ohne = HistoryEntryRow(dict(basis), lambda _i: None)
    mit = HistoryEntryRow(dict(basis, reason=gruende.WORTSALAT), lambda _i: None)
    punkte = [w for w in mit.findChildren(QLabel) if w.text() == "●"]
    assert len(punkte) == 1
    assert punkte[0].toolTip() == gruende.WORTSALAT
    assert not [w for w in ohne.findChildren(QLabel) if w.text() == "●"]


def test_die_verarbeitungs_karte_nennt_die_haeufigsten_gruende():
    from collections import Counter

    from fleech.history import Stats
    from fleech.ui.pages.insights import _processing_summary

    stats = Stats(total_dictations=10, stt_median_ms=200, llm_median_ms=3000,
                  stt_p90_ms=400, llm_p90_ms=6000,
                  tier_shares={"complex": 1.0}, fallback_rate=0.3)
    text = _processing_summary(stats, Counter({
        gruende.OLLAMA: 2,
        gruende.mit_detail(gruende.SINN_GEDREHT, "1 Zahl fehlt"): 1,
    }))
    assert "Fallback-Quote: 30 %" in text
    assert "Rückfälle:" in text
    assert "2× Ollama" in text
    assert "1× Sinnumkehr" in text
    # Ohne Gruende bleibt die Karte so knapp wie bisher.
    assert "Rückfälle:" not in _processing_summary(stats)


@pytest.mark.parametrize("grund", ["", None])
def test_leere_gruende_erzeugen_keine_zeile(grund):
    from fleech.ui.pages.insights import _gruende_zeile

    assert _gruende_zeile(grund) == ""


def test_nur_in_der_ablage_loest_die_blase_aus_auch_ohne_benachrichtigungen(qapp, tmp_path):
    """Der Fall vom 2026-10-02: Diktat 33 s nach dem Sprechen fertig, Nutzer in
    einem anderen Fenster → Text in die Zwischenablage. Der Toast wurde
    unterdrueckt (Benachrichtigungen auf „Nichts"), die Pille verschwand — der
    Nutzer sah nichts. Die Blase muss IMMER kommen, egal was der Toast tut."""
    import types

    from fleech.profiles import ProfileOverrides
    from fleech.ui.desktop import DesktopApp

    blasen, toasts = [], []
    still = types.SimpleNamespace(emit=lambda *a: None)
    fake = types.SimpleNamespace(
        _app_profile_overrides=lambda: ProfileOverrides(),
        _setze_sprache=lambda s: None,
        settings=types.SimpleNamespace(
            output=types.SimpleNamespace(command_enabled=True),
            general=types.SimpleNamespace(language="de", save_history=False),
        ),
        config=types.SimpleNamespace(audio=types.SimpleNamespace(samplerate=16000)),
        store=HistoryStore(tmp_path / "history.db"),
        pipeline=types.SimpleNamespace(
            process=lambda audio, samplerate, **kw: "ok",
            last_mode="cleanup", last_injected="", last_raw="roh",
            last_formulas=[], last_dropped_tail="", last_reason="",
            last_error_kind="", last_tier="", last_stt_ms=0, last_llm_ms=0,
            in_ablage_statt_eingefuegt=True, in_ablage_text="Mein spätes Diktat.",
            injector=types.SimpleNamespace(send_enter=lambda: None),
        ),
        bus=types.SimpleNamespace(
            injection_fallback=still, formula_preview=still, tail_dropped=still,
            transcript_ready=still, history_changed=still, set_state=lambda *a: None,
            in_ablage=types.SimpleNamespace(emit=blasen.append),
        ),
        # Ein Notifier, der ALLES unterdrueckt — wie bei der Stufe „Nichts".
        notifier=types.SimpleNamespace(sound=lambda k: None,
                                       toast=lambda *a, **k: toasts.append(a) and False),
        _record_app="", _record_title="", _undo_candidate=None,
        _check_dictionary_candidates=lambda t: None,
        _count_dictionary_usage=lambda t: None,
        _flash_status=lambda t: None,
    )
    DesktopApp._process_locked(fake, b"\x00" * 32)
    assert blasen == ["Mein spätes Diktat."]


def test_nur_in_der_ablage_landet_trotzdem_im_verlauf(qapp, tmp_path):
    """Am 2026-10-02 fehlte das spaete Diktat im Verlauf — dem einzigen Ort, an
    dem man es haette wiederfinden koennen. Es stand nur noch im Protokoll."""
    import types

    from fleech.profiles import ProfileOverrides
    from fleech.ui.desktop import DesktopApp

    still = types.SimpleNamespace(emit=lambda *a: None)
    store = HistoryStore(tmp_path / "history.db")
    fake = types.SimpleNamespace(
        _app_profile_overrides=lambda: ProfileOverrides(),
        _setze_sprache=lambda s: None,
        settings=types.SimpleNamespace(
            output=types.SimpleNamespace(command_enabled=True),
            general=types.SimpleNamespace(language="de", save_history=True),
        ),
        config=types.SimpleNamespace(audio=types.SimpleNamespace(samplerate=16000)),
        store=store,
        pipeline=types.SimpleNamespace(
            process=lambda audio, samplerate, **kw: "ok",
            last_mode="cleanup", last_injected="", last_raw="roh",
            last_formulas=[], last_dropped_tail="", last_reason="",
            last_error_kind="", last_tier="", last_stt_ms=0, last_llm_ms=0,
            in_ablage_statt_eingefuegt=True, in_ablage_text="Mein spätes Diktat.",
            injector=types.SimpleNamespace(send_enter=lambda: None),
        ),
        bus=types.SimpleNamespace(
            injection_fallback=still, formula_preview=still, tail_dropped=still,
            transcript_ready=still, history_changed=still, set_state=lambda *a: None,
            in_ablage=still,
        ),
        notifier=types.SimpleNamespace(sound=lambda k: None, toast=lambda *a, **k: False),
        _record_app="", _record_title="", _undo_candidate=None,
        _check_dictionary_candidates=lambda t: None,
        _count_dictionary_usage=lambda t: None,
        _flash_status=lambda t: None,
    )
    DesktopApp._process_locked(fake, b"\x00" * 32)
    eintrag = store.recent()[0]
    assert eintrag["cleaned"] == "Mein spätes Diktat."
    assert gruende.IN_ABLAGE in eintrag["reason"]


def _app_nach_diktat(tmp_path, ergebnis: str, in_ablage: bool):
    """DesktopApp-Attrappe, deren Pipeline `ergebnis` liefert — der Text steht
    danach im Feld oder (`in_ablage`) nur in der Zwischenablage. Gibt die Attrappe
    und die Listen der Pillen-Zustaende, Blasen und Toasts zurueck."""
    import types

    from fleech.profiles import ProfileOverrides

    zustaende, blasen, toasts = [], [], []
    still = types.SimpleNamespace(emit=lambda *a: None)
    text = "Mein spätes Diktat."
    fake = types.SimpleNamespace(
        _app_profile_overrides=lambda: ProfileOverrides(),
        _setze_sprache=lambda s: None,
        settings=types.SimpleNamespace(
            output=types.SimpleNamespace(command_enabled=True),
            general=types.SimpleNamespace(language="de", save_history=False),
        ),
        config=types.SimpleNamespace(audio=types.SimpleNamespace(samplerate=16000)),
        store=HistoryStore(tmp_path / "history.db"),
        pipeline=types.SimpleNamespace(
            process=lambda audio, samplerate, **kw: ergebnis,
            last_mode="cleanup", last_injected="" if in_ablage else text,
            last_raw="roh", last_formulas=[], last_dropped_tail="", last_reason="",
            last_error_kind="", last_tier="", last_stt_ms=0, last_llm_ms=0,
            in_ablage_statt_eingefuegt=in_ablage,
            in_ablage_text=text if in_ablage else "",
            injector=types.SimpleNamespace(send_enter=lambda: None),
        ),
        bus=types.SimpleNamespace(
            injection_fallback=still, formula_preview=still, tail_dropped=still,
            transcript_ready=still, history_changed=still,
            set_state=lambda zustand, text="": zustaende.append(text),
            in_ablage=types.SimpleNamespace(emit=blasen.append),
        ),
        notifier=types.SimpleNamespace(sound=lambda k: None,
                                       toast=lambda *a, **k: toasts.append(a)),
        _record_app="", _record_title="", _undo_candidate=None,
        _check_dictionary_candidates=lambda t: None,
        _count_dictionary_usage=lambda t: None,
        _flash_status=lambda t: None,
    )
    return fake, zustaende, blasen, toasts


def test_rueckfall_in_der_ablage_meldet_die_ablage(qapp, tmp_path):
    """Der Fall vom 2026-10-08: Ollama brach ab, das Rohtranskript war erst 39 s
    nach dem Sprechen fertig, der Nutzer in einem anderen Fenster → Zwischenablage.
    Die Pille meldete „eingefügt (Fallback — Log prüfen)", Blase und Toast blieben
    aus — der Ablage-Zweig galt nur fuer „ok". Gemeldet „eingefügt", angekommen
    nichts."""
    from fleech.ui.desktop import DesktopApp

    fake, zustaende, blasen, toasts = _app_nach_diktat(tmp_path, "fallback", True)
    DesktopApp._process_locked(fake, b"\x00" * 32)
    assert blasen == ["Mein spätes Diktat."]
    assert zustaende[-1] == "in der Zwischenablage (unbereinigt)"
    assert not any("eingefügt" in z for z in zustaende)
    assert any("ohne KI-Bereinigung" in t[2] for t in toasts)


@pytest.mark.parametrize("ergebnis,zustand", [
    ("ok", "eingefügt"),
    ("fallback", "eingefügt (Fallback — Log prüfen)"),
])
def test_eingefuegtes_diktat_meldet_weiter_eingefuegt(qapp, tmp_path, ergebnis, zustand):
    """Gegenprobe: Stand der Text im Feld, bleibt alles wie bisher — keine Blase,
    kein Ablage-Toast, und „ok" landet nicht im Fehlerzweig."""
    from fleech.ui.desktop import DesktopApp

    fake, zustaende, blasen, toasts = _app_nach_diktat(tmp_path, ergebnis, False)
    DesktopApp._process_locked(fake, b"\x00" * 32)
    assert zustaende[-1] == zustand
    assert blasen == []
    assert not any("Zwischenablage" in t[2] for t in toasts)
