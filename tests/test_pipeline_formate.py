"""Ausgabeformate und Bausteine: Was aus dem Diktat wird, statt nur wie geglaettet.

Beide teilen dieselbe Rueckfallebene: Liefert das Format nicht (Prompt-Datei
fehlt, Modell antwortet leer), landet der Text als normales Cleanup im Feld.
"""


from pipelinehelpers import (
    AUDIO,
    CLEAN_NONTRIVIAL,
    FakeLLM,
    RAW_NONTRIVIAL,
    make_pipeline,
)

PE_RAW = "ähm kannst du mir den code cleaner machen also vor allem parse config"

SNIPPET_LINES = ["Signatur => Viele Grüße\nAlex"]


def test_prompt_mode_structures_dictation():
    # KI-Prompting-Latch: Diktat → strukturierter Prompt ueber das grosse Modell.
    structured = "**Aufgabe:** Refaktoriere den Code — insbesondere `parse_config`."
    p, llm, injector = make_pipeline(PE_RAW, llm=FakeLLM(reply=structured))
    p.prompt_engineer_prompt = "PE-SYSTEM"
    result = p.process(AUDIO, 16000, prompt_mode=True)
    assert result == "ok"
    assert injector.injected == [structured]
    assert p.last_mode == "prompt"
    system, user = llm.calls[0]
    assert system == "PE-SYSTEM"                 # eigener System-Prompt, nicht Cleanup
    assert PE_RAW in user and "⟦TRANSKRIPT⟧" in user  # Delimiter-Rahmung


def test_prompt_mode_failure_falls_back_to_cleanup():
    # LLM kaputt → Diktat geht NIE verloren: Cleanup-Fallback (hier: Rohtext).
    p, _, injector = make_pipeline(PE_RAW, llm=FakeLLM(error=ConnectionError("down")))
    p.prompt_engineer_prompt = "PE-SYSTEM"
    result = p.process(AUDIO, 16000, prompt_mode=True)
    assert result == "fallback"
    assert injector.injected == [PE_RAW]


def test_prompt_mode_without_prompt_file_degrades_to_cleanup():
    # prompts/prompt_engineer.md fehlt (prompt_engineer_prompt="") → normales Cleanup.
    # (Der Fake-Cleanup-Reply hat keinen Bezug zum Rohtext → Grounding-Guard liefert
    # den Rohtext; entscheidend: es wird ETWAS eingefuegt, kein Crash, kein Verlust.)
    p, _, injector = make_pipeline(PE_RAW)
    result = p.process(AUDIO, 16000, prompt_mode=True)
    assert result == "fallback"
    assert injector.injected == [PE_RAW]


def test_reiner_baustein_aufruf_ohne_llm():
    """„Baustein Signatur" allein: nichts zu bereinigen → kein Modell-Roundtrip."""
    p, llm, injector = make_pipeline("Baustein Signatur")
    p.set_snippets(SNIPPET_LINES)
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == ["Viele Grüße\nAlex"]
    assert llm.calls == []          # kein LLM angefasst


def test_baustein_im_satz_geht_als_marker_ans_modell():
    raw = "vielen dank für ihre nachricht bis bald Baustein Signatur"
    # Das Modell sieht den Marker und gibt ihn (regelkonform) zurueck.
    llm = FakeLLM(reply="Vielen Dank für Ihre Nachricht, bis bald. [[B1]]")
    p, _, injector = make_pipeline(raw, llm=llm)
    p.set_snippets(SNIPPET_LINES)
    assert p.process(AUDIO, 16000) == "ok"
    # Der Baustein-Inhalt darf dem Modell NIE gezeigt werden.
    _system, user = llm.calls[0]
    assert "[[B1]]" in user
    assert "Viele Grüße" not in user
    assert injector.injected == ["Vielen Dank für Ihre Nachricht, bis bald. Viele Grüße\nAlex"]


def test_verschluckter_marker_rettet_den_baustein():
    """Verliert das Modell den Platzhalter, gewinnt das Rohtext-Gerüst — der
    Baustein darf nie ersatzlos verschwinden."""
    raw = "vielen dank für ihre nachricht bis bald Baustein Signatur"
    llm = FakeLLM(reply="Vielen Dank für Ihre Nachricht, bis bald.")  # Marker weg
    p, _, injector = make_pipeline(raw, llm=llm)
    p.set_snippets(SNIPPET_LINES)
    assert p.process(AUDIO, 16000) == "fallback"
    assert "Viele Grüße\nAlex" in injector.injected[0]


def test_baustein_kuerzel_wird_der_erkennung_genannt():
    p, _llm, _injector = make_pipeline("egal")
    p.set_snippets(SNIPPET_LINES)
    p.process(AUDIO, 16000)
    assert "Baustein Signatur" in p.stt.prompts[0]


def test_ohne_bausteine_bleibt_alles_wie_bisher():
    p, llm, injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply=CLEAN_NONTRIVIAL))
    p.set_snippets([])
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [CLEAN_NONTRIVIAL]
    assert llm.calls


def test_bausteine_gehen_immer_ans_grosse_modell():
    """Live gemessen: das kleine Modell verschluckt Marker. Kurzer Satz + Baustein
    darf trotzdem nie beim schnellen Modell landen."""
    big = FakeLLM(reply="Danke, bis morgen. [[B1]]")
    fast = FakeLLM(reply="verschluckt den Marker")
    p, _, injector = make_pipeline("danke bis morgen Baustein Signatur",
                                   llm=big, fast_llm=fast)
    p.set_snippets(SNIPPET_LINES)
    assert p.process(AUDIO, 16000) == "ok"
    assert fast.calls == []          # das kleine Modell wurde nie gefragt
    assert big.calls
    assert injector.injected == ["Danke, bis morgen. Viele Grüße\nAlex"]
