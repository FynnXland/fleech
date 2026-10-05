"""Die Pipeline im Normalbetrieb: Ablauf, Statuscodes, Modellwahl, Woerterbuch.

Die Qualitaets-Guards, die Safe-Word-Befehle und die Ausgabeformate haben
eigene Dateien — siehe test_pipeline_guards.py, _halluzination.py,
_befehle.py und _formate.py.
"""

import numpy as np
import pytest

from pipelinehelpers import (
    AUDIO,
    CLEAN_NONTRIVIAL,
    FakeLLM,
    RAW_NONTRIVIAL, RAW_NONTRIVIAL_OHNE_FW,
    make_pipeline,
)

SIMPLE_RAW = "also äh ich wollte nur kurz sagen dass das ganz gut klingt soweit"

COMPLEX_RAW = "treffen wir uns dienstag nein doch lieber freitag um 15 uhr"


def test_happy_path_injects_cleaned_text():
    p, llm, injector = make_pipeline("also äh der text halt")
    p.process(AUDIO, 16000)
    assert injector.injected == ["sauberer Text."]
    system, user = llm.calls[0]
    assert system == "SYSTEM"
    # Roh-Transkript im User-Turn, UNVERAENDERT: Fuellwoerter entfernt Fleech erst
    # NACH dem Modell (vorbereinigte Eingabe liess es live anders formulieren).
    assert "also äh der text halt" in user
    assert "⟦TRANSKRIPT⟧" in user                     # … als abgegrenzter Datenblock


def test_llm_failure_falls_back_to_raw_transcript():
    p, _, injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(error=ConnectionError("down")))
    p.process(AUDIO, 16000)
    assert injector.injected == [RAW_NONTRIVIAL_OHNE_FW]


def test_empty_llm_reply_falls_back_to_raw():
    """Leere Modellantwort ist ein Rueckfall wie jeder andere — und wird seit
    Befund C-4 auch so gemeldet. Vorher meldete die Oberflaeche gruenen Haken und
    Bestaetigungston fuer ein unbereinigtes Transkript."""
    p, _, injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply=""))
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [RAW_NONTRIVIAL_OHNE_FW]


def test_too_short_audio_is_dropped():
    p, llm, injector = make_pipeline("egal")
    p.process(np.zeros(1000, dtype=np.float32), 16000)  # 0,06 s
    assert injector.injected == []
    assert llm.calls == []


def test_empty_transcript_injects_nothing():
    p, llm, injector = make_pipeline("")
    p.process(AUDIO, 16000)
    assert injector.injected == []
    assert llm.calls == []


def test_recorder_position_counts_samples():
    from fleech.audio import Recorder

    r = Recorder(16000)
    r._callback(np.zeros((8000, 1), dtype=np.float32), 8000, None, None)
    assert r.position == pytest.approx(0.5)
    r._callback(np.zeros((4000, 1), dtype=np.float32), 4000, None, None)
    assert r.position == pytest.approx(0.75)


def test_consecutive_dictations_get_space_separator():
    p, _, injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply=CLEAN_NONTRIVIAL))
    p.process(AUDIO, 16000)
    p.process(AUDIO, 16000)
    assert injector.injected == [CLEAN_NONTRIVIAL, " " + CLEAN_NONTRIVIAL]


def test_process_returns_status_codes():
    p, _, _ = make_pipeline("hallo welt")
    assert p.process(AUDIO, 16000) == "ok"
    assert p.process(np.zeros(100, dtype=np.float32), 16000) == "too_short"
    p2, _, _ = make_pipeline("")
    assert p2.process(AUDIO, 16000) == "empty"


def test_llm_failure_returns_fallback_status():
    p, _, injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(error=ConnectionError("down")))
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [RAW_NONTRIVIAL_OHNE_FW]


def test_trivial_utterance_skips_llm_entirely():
    p, llm, injector = make_pipeline("Okay, das passt.")
    p.process(AUDIO, 16000)
    assert injector.injected == ["Okay, das passt."]
    assert llm.calls == []  # kein LLM-Roundtrip → keine Latenz


def test_trivial_fast_path_disabled_for_strong_intervention():
    p, llm, _ = make_pipeline("Okay, das passt.")
    p.intervention = "strong"
    p.strong_addendum = "MEHR"
    p.process(AUDIO, 16000)
    assert llm.calls  # Strong = Nutzer will explizit Glaettung → immer LLM


def test_simple_utterance_uses_fast_model():
    fast = FakeLLM(reply="Ich wollte nur kurz sagen, dass das ganz gut klingt soweit.")
    p, big, injector = make_pipeline(SIMPLE_RAW, fast_llm=fast)
    p.process(AUDIO, 16000)
    assert fast.calls and not big.calls          # kleines Modell, nicht das grosse
    assert injector.injected == [fast.reply]


def test_complex_utterance_uses_big_model():
    fast = FakeLLM(reply="<sollte nicht verwendet werden>")
    p, big, injector = make_pipeline(
        COMPLEX_RAW, llm=FakeLLM(reply="Treffen wir uns Freitag um 15 Uhr."), fast_llm=fast,
    )
    p.process(AUDIO, 16000)
    assert not fast.calls                          # Korrektur + Zahl → grosses Modell
    assert injector.injected == ["Treffen wir uns Freitag um 15 Uhr."]


def test_adaptive_disabled_forces_big_model():
    fast = FakeLLM(reply="Ich wollte nur kurz sagen, dass das klein klingt.")
    p, big, injector = make_pipeline(
        SIMPLE_RAW,
        llm=FakeLLM(reply="Ich wollte nur kurz sagen, dass das ganz gut klingt soweit."),
        fast_llm=fast,
    )
    p.adaptive = False
    p.process(AUDIO, 16000)
    assert big.calls and not fast.calls   # trotz "simple" das grosse Modell
    assert injector.injected == ["Ich wollte nur kurz sagen, dass das ganz gut klingt soweit."]


def test_fast_model_failure_falls_back_to_big_model():
    fast = FakeLLM(error=ConnectionError("klein weg"))
    p, big, injector = make_pipeline(
        SIMPLE_RAW, llm=FakeLLM(reply="Ich wollte nur kurz sagen, dass das ganz gut klingt."),
        fast_llm=fast,
    )
    p.process(AUDIO, 16000)
    assert fast.calls                              # zuerst klein versucht …
    assert injector.injected == ["Ich wollte nur kurz sagen, dass das ganz gut klingt."]


def test_intervention_minimal_skips_llm():
    p, llm, injector = make_pipeline("also äh roher text")
    p.intervention = "minimal"
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == ["also äh roher text"]
    assert llm.calls == []


def test_intervention_strong_appends_addendum():
    p, llm, _ = make_pipeline("text")
    p.intervention = "strong"
    p.strong_addendum = "ZUSATZREGELN"
    p.process(AUDIO, 16000)
    system_prompt = llm.calls[0][0]
    assert system_prompt.startswith("SYSTEM")
    assert system_prompt.endswith("ZUSATZREGELN")


def test_dictionary_priming_reaches_whisper():
    p, _, _injector = make_pipeline(RAW_NONTRIVIAL)
    p.set_dictionary(["Fleech", "github => GitHub"])
    p.process(AUDIO, 16000)
    prompt = p.stt.prompts[-1]
    assert prompt is not None and "Fleech" in prompt and "GitHub" in prompt


def test_dictionary_replacement_applied_to_output():
    p, _, injector = make_pipeline("der pr liegt auf github und github ist down")
    p.intervention = "minimal"   # LLM-frei → Ersetzung direkt auf dem Rohtext sichtbar
    p.set_dictionary(["github => GitHub"])
    p.process(AUDIO, 16000)
    assert injector.injected == ["der pr liegt auf GitHub und GitHub ist down"]


def test_stt_hint_contains_trigger_word_priming():
    p, _, _injector = make_pipeline(RAW_NONTRIVIAL)
    p.process(AUDIO, 16000)
    prompt = p.stt.prompts[-1]
    assert prompt is not None and "Redax" in prompt  # Signalwort-Priming immer aktiv


def test_app_profile_override_minimal_skips_llm():
    p, llm, injector = make_pipeline(RAW_NONTRIVIAL)
    p.process(AUDIO, 16000, intervention_override="minimal")
    assert llm.calls == []                       # App-Profil: kein LLM-Eingriff
    # … und auch keine Fuellwort-Entfernung: „minimal" heisst Text wie gesprochen.
    assert injector.injected == [RAW_NONTRIVIAL]
    # Override gilt nur pro Durchlauf — die Grundeinstellung bleibt unveraendert.
    assert p.intervention == "standard"
    p.process(AUDIO, 16000)
    assert llm.calls                             # ohne Override laeuft das LLM wieder


def test_style_hints_flow_into_cleanup_prompt():
    p, llm, _injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply=CLEAN_NONTRIVIAL))
    p.process(AUDIO, 16000, style_hints=["professioneller Ton"])
    system, _user = llm.calls[0]
    assert "professioneller Ton" in system
    assert "Stil-Vorgaben" in system
    # Ohne Hints bleibt der Prompt unveraendert.
    p.process(AUDIO, 16000)
    system2, _ = llm.calls[1]
    assert "Stil-Vorgaben" not in system2


# -- „Die lokale KI laeuft gar nicht" (Befund E-13) --------------------------------


def _rueckfall_grund(fehler, base_url="http://127.0.0.1:11434"):
    """Ein Cleanup-Rueckfall mit einem Endpunkt-Fehler → welcher Grund kommt an?"""
    import types

    llm = FakeLLM(error=fehler)
    llm.cfg = types.SimpleNamespace(base_url=base_url)
    p, _, injector = make_pipeline(RAW_NONTRIVIAL, llm=llm)
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [RAW_NONTRIVIAL_OHNE_FW]     # Rohtext kommt weiter an
    return p.last_error_kind


def test_nicht_laufender_ollama_wird_als_solcher_erkannt():
    """Wer die Einfuehrung ueberspringt, ueberspringt die Einrichtung von Ollama.
    Jedes Diktat kommt dann als Roh-Transkript an — und der einzige Klartext dazu
    stand in der Logdatei. Damit die Pille es sagen kann, muss die Pipeline den
    fehlenden DIENST von einem schlecht antwortenden Modell unterscheiden."""
    import urllib.error

    assert _rueckfall_grund(
        urllib.error.URLError(ConnectionRefusedError(10061, "abgelehnt"))
    ) == "llm_offline"
    assert _rueckfall_grund(ConnectionRefusedError(10061, "abgelehnt")) == "llm_offline"


def test_ein_antwortender_server_gilt_nicht_als_abwesend():
    """HTTP-Fehler und Modell-Macken sind etwas anderes als „kein Dienst da" —
    sonst schickte Fleech den Nutzer wegen jeder Stoerung in die Einfuehrung."""
    import urllib.error

    assert _rueckfall_grund(
        urllib.error.HTTPError("http://127.0.0.1:11434/api/chat", 500,
                               "Server Error", {}, None)
    ) == ""
    assert _rueckfall_grund(ValueError("kaputtes JSON")) == ""
    # Ein entfernter Endpunkt ist kein Fall fuer den Einfuehrungs-Hinweis.
    assert _rueckfall_grund(ConnectionRefusedError(),
                            base_url="http://192.168.1.9:11434") == ""


def test_zeitueberschreitung_heisst_nicht_dass_die_ki_fehlt():
    """Ein Dienst, der NICHT laeuft, lehnt sofort ab. Einer, der in eine Zeit-
    ueberschreitung laeuft, laeuft — er rechnet nur zu lange (im Log am 25.09.:
    Timeout, eine Sekunde spaeter „Lokale KI laeuft nicht", obwohl das Warmhalten
    kurz davor erfolgreich war). Die Meldung schickte den Nutzer in die Einfuehrung."""
    import socket
    import urllib.error

    assert _rueckfall_grund(TimeoutError("timed out")) == ""
    assert _rueckfall_grund(socket.timeout("timed out")) == ""
    assert _rueckfall_grund(urllib.error.URLError(TimeoutError("timed out"))) == ""


def test_nur_in_der_ablage_wird_nicht_als_eingefuegt_gefuehrt():
    """Lag der Text am Ende nur in der Zwischenablage (spaet fertig, Nutzer
    woanders), steht er in keinem Dokument. Der Tracker darf ihn dann nicht als
    angehaengt fuehren — sonst bezoegen sich Befehle wie „mach den letzten Satz
    formeller" auf Text, der nirgends steht. Und die App muss es melden koennen."""
    llm = FakeLLM(reply=RAW_NONTRIVIAL)
    p, _, injector = make_pipeline(RAW_NONTRIVIAL, llm=llm)
    injector.inject = lambda text: (injector.injected.append(text), False)[1]

    assert p.process(AUDIO, 16000) == "ok"
    assert p.in_ablage_statt_eingefuegt is True
    assert p.in_ablage_text                             # die App zeigt ihn in der Blase
    assert p.tracker.context_tail() == ""

    injector.inject = lambda text: (injector.injected.append(text), True)[1]
    p.process(AUDIO, 16000)
    assert p.in_ablage_statt_eingefuegt is False        # je Diktat zurueckgesetzt


def test_fuellwoerter_verschwinden_nach_dem_modell():
    """Die Regel im Prompt entfernte 14 von 564 Füllwörtern. Bleibt eines in der
    Modellantwort stehen, entfernt Fleech es danach — das Modell selbst sieht den
    Rohtext unverändert."""
    llm = FakeLLM(reply="Also, ähm, das ist der Text.")
    p, _, injector = make_pipeline(RAW_NONTRIVIAL, llm=llm)
    p.process(AUDIO, 16000)
    assert "ähm" not in injector.injected[0].lower()
    assert "äh" in llm.calls[0][1]                        # Eingabe unverändert


def test_minimal_behaelt_die_fuellwoerter():
    """„minimal" heißt: Text wie gesprochen."""
    p, _, injector = make_pipeline(RAW_NONTRIVIAL)
    p.process(AUDIO, 16000, intervention_override="minimal")
    assert injector.injected == [RAW_NONTRIVIAL]
