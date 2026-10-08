"""Was gar nicht erst gespeichert wird (6.3.0): Aufbewahrungsfrist, kein Diktattext im
Protokoll, kein Diktat im Zwischenablageverlauf."""

from __future__ import annotations

import datetime as dt
import logging

from fleech import protokolltext
from fleech.history import DictationRecord, HistoryStore

TAG = 86400


def _record(ts, text="ein zwei drei", sekunden=2.0):
    return DictationRecord(ts=ts, raw=text, cleaned=text, audio_seconds=sekunden,
                           app="notepad.exe")


# -- Aufbewahrungsfrist ----------------------------------------------------------------


def test_alte_diktate_gehen_ihre_zahlen_bleiben(tmp_path):
    jetzt = dt.datetime(2026, 10, 9, 12, 0).timestamp()
    store = HistoryStore(tmp_path / "h.db")
    store.add(_record(jetzt - 200 * TAG, "alt eins zwei", 3.0))
    store.add(_record(jetzt - 200 * TAG + 60, "alt drei", 1.0))
    store.add(_record(jetzt - 5 * TAG, "neu vier fuenf sechs", 2.0))
    vorher = store.stats()

    store.aufbewahrung_tage = 90
    assert store.aufbewahren(jetzt=jetzt) == 2

    assert [e["cleaned"] for e in store.recent()] == ["neu vier fuenf sechs"]
    assert store.search("alt") == []
    nachher = store.stats()
    # Summen, Lebenszeit-Woerter und die Tage der Serie ueberleben den Text.
    assert nachher.total_dictations == vorher.total_dictations == 3
    assert nachher.total_words == vorher.total_words
    assert nachher.total_audio_seconds == vorher.total_audio_seconds
    assert nachher.lifetime_words == vorher.lifetime_words
    assert nachher.daily_counts == vorher.daily_counts


def test_zeitraum_zaehlt_nur_seine_tage(tmp_path):
    jetzt = dt.datetime(2026, 10, 9, 12, 0).timestamp()
    store = HistoryStore(tmp_path / "h.db", aufbewahrung_tage=90)
    store.add(_record(jetzt - 200 * TAG))
    store.aufbewahren(jetzt=jetzt)
    assert store.stats(since=jetzt - 30 * TAG).total_dictations == 0
    assert store.stats().total_dictations == 1


def test_unbegrenzt_loescht_nichts(tmp_path):
    store = HistoryStore(tmp_path / "h.db", aufbewahrung_tage=0)
    store.add(_record(1_000_000.0))
    assert store.aufbewahren() == 0
    assert len(store.recent()) == 1


def test_frist_wird_beim_hinzufuegen_gepflegt(tmp_path):
    """Tray-App: Fleech laeuft wochenlang durch — nur beim Start zu pflegen reicht nicht."""
    store = HistoryStore(tmp_path / "h.db", aufbewahrung_tage=30)
    store._gepflegt = float("-inf")
    store.add(_record(1_000_000.0))
    assert store.recent() == []


def test_verlauf_loeschen_nimmt_auch_die_zahlen_mit(tmp_path):
    store = HistoryStore(tmp_path / "h.db", aufbewahrung_tage=30)
    store.add(_record(1_000_000.0))
    store.clear()
    assert store.stats().total_dictations == 0


def test_vorgabe_der_einstellung_ist_90_tage():
    from fleech.usersettings import GeneralSettings

    assert GeneralSettings().verlauf_tage == 90


# -- Protokoll ---------------------------------------------------------------------------


def test_inhalt_zeigt_ohne_freigabe_nur_den_umfang(monkeypatch):
    monkeypatch.setattr(protokolltext, "_zeigen", False)
    assert protokolltext.inhalt("Meine PIN ist 1234") == "‹4 Wörter›"
    assert protokolltext.inhalt("Hallo") == "‹1 Wort›"
    assert protokolltext.inhalt("") == "<leer>"
    monkeypatch.setattr(protokolltext, "_zeigen", True)
    assert protokolltext.inhalt("Meine PIN ist 1234", 8) == "Meine PI"


def test_ein_ganzes_diktat_hinterlaesst_keinen_text_im_protokoll(caplog, monkeypatch):
    """Ende zu Ende: Roh, bereinigt, eingefuegt — nichts davon im Log, auf keiner Stufe."""
    from pipelinehelpers import AUDIO, CLEAN_NONTRIVIAL, RAW_NONTRIVIAL, FakeLLM, \
        make_pipeline

    monkeypatch.setattr(protokolltext, "_zeigen", False)
    p, _llm, injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply=CLEAN_NONTRIVIAL))
    with caplog.at_level(logging.DEBUG):
        p.process(AUDIO, 16000)
    assert injector.injected == [CLEAN_NONTRIVIAL]
    protokoll = "\n".join(r.getMessage() for r in caplog.records)
    for wort in ("rohe", "Text mit", "paar mehr"):
        assert wort not in protokoll, protokoll


def test_auch_ein_rueckfall_schreibt_keinen_text(caplog, monkeypatch):
    from pipelinehelpers import AUDIO, RAW_NONTRIVIAL, FakeLLM, make_pipeline

    monkeypatch.setattr(protokolltext, "_zeigen", False)
    p, _llm, _inj = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply="Völlig anderer "
                                  "erfundener Inhalt über Urlaub am Meer und Sonne."))
    with caplog.at_level(logging.DEBUG):
        p.process(AUDIO, 16000)
    protokoll = "\n".join(r.getMessage() for r in caplog.records)
    assert "rohe" not in protokoll and "Urlaub" not in protokoll, protokoll


# -- Zwischenablage ------------------------------------------------------------------------


def test_kopieren_geht_unter_windows_den_privaten_weg(monkeypatch, zwischenablage):
    from fleech import clipboard

    monkeypatch.setattr(clipboard, "_use_copykitten", lambda: False)
    clipboard.copy_text("Diktat mit Telefonnummer")
    assert zwischenablage == ["Diktat mit Telefonnummer"]


def test_private_formate_sind_die_von_microsoft_dokumentierten():
    from fleech import clipboard

    assert set(clipboard._PRIVAT_FORMATE) == {
        "ExcludeClipboardContentFromMonitorProcessing",
        "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard"}
