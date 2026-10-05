"""Ausgabeformate und Formel-Platzhalter: Was aus dem Diktat wird, statt nur wie
geglaettet.

Beide teilen dieselbe Rueckfallebene: Liefert das Format nicht (Prompt-Datei
fehlt, Modell antwortet leer) oder verschluckt das Modell einen Platzhalter,
landet der Text als normales Cleanup bzw. als Rohtext-Geruest im Feld.

Die Baustein-Tests dieser Datei sind mit den Text-Bausteinen in 5.11.0 entfallen
(Befund E-1): kein Baustein in 1399 Diktaten, kein wiederkehrender Text im
Verlauf. Was daran wirklich schuetzte — die Formel-Platzhalter-Pruefung aus C-3 —
wird hier weiter geprueft, jetzt am verbliebenen Formel-Zweig.
"""


from fleech.vorbereinigung import entferne_fuellwoerter
from pipelinehelpers import (
    AUDIO,
    FakeLLM,
    make_pipeline,
)

PE_RAW = "ähm kannst du mir den code cleaner machen also vor allem parse config"
PE_RAW_OHNE_FW = entferne_fuellwoerter(PE_RAW)[0]


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
    # Rueckfall = Rohtext, aber ohne das Fuellwort am Anfang: Fuellwoerter
    # entfernt Fleech nach jedem Cleanup-Weg, auch nach dem Rueckfall.
    assert injector.injected == [PE_RAW_OHNE_FW]


def test_prompt_mode_without_prompt_file_degrades_to_cleanup():
    # prompts/prompt_engineer.md fehlt (prompt_engineer_prompt="") → normales Cleanup.
    # (Der Fake-Cleanup-Reply hat keinen Bezug zum Rohtext → Grounding-Guard liefert
    # den Rohtext; entscheidend: es wird ETWAS eingefuegt, kein Crash, kein Verlust.)
    p, _, injector = make_pipeline(PE_RAW)
    result = p.process(AUDIO, 16000, prompt_mode=True)
    assert result == "fallback"
    # Rueckfall = Rohtext, aber ohne das Fuellwort am Anfang: Fuellwoerter
    # entfernt Fleech nach jedem Cleanup-Weg, auch nach dem Rueckfall.
    assert injector.injected == [PE_RAW_OHNE_FW]


FORMEL_RAW = "vielen dank die formel lautet x hoch zwei plus eins bis bald"


def test_formel_im_satz_geht_als_marker_ans_modell():
    """Der Parser ersetzt die Formel VOR dem Modell — das Modell sieht nur `[[M1]]`
    und bekommt die Regel dazu im System-Prompt."""
    llm = FakeLLM(reply="Vielen Dank, die Formel lautet [[M1]]. Bis bald.")
    p, _, injector = make_pipeline(FORMEL_RAW, llm=llm)
    p.auto_latex = True
    assert p.process(AUDIO, 16000) == "ok"
    system, user = llm.calls[0]
    assert "[[M1]]" in user and "[[M1]]" in system
    assert injector.injected == ["Vielen Dank, die Formel lautet $x^{2} + 1$. Bis bald."]


def test_verschluckter_formel_marker_rettet_die_formel():
    """C-3: Verschluckt das Modell den Platzhalter, ersetzt `restore_formulas` ihn
    durch NICHTS — die Formel wäre spurlos weg, mit grünem Haken. Stattdessen
    gewinnt das Rohtext-Gerüst.

    Bis 5.10.x prüfte das derselbe Test am Baustein-Zweig (der Zweig, in dem C-3
    entstand). Mit den Text-Bausteinen (Befund E-1) ist er entfallen; geprüft wird
    jetzt der verbliebene Formel-Zweig, in dem dieselbe Prüfung sitzt."""
    llm = FakeLLM(reply="Vielen Dank, die Formel lautet. Bis bald.")  # [[M1]] weg
    p, _, injector = make_pipeline(FORMEL_RAW, llm=llm)
    p.auto_latex = True
    assert p.process(AUDIO, 16000) == "fallback"
    assert "x^{2} + 1" in injector.injected[0]      # die Formel ist noch da


def test_formeln_gehen_immer_ans_grosse_modell():
    """Live gemessen: das kleine Modell verschluckt Platzhalter. Ein kurzer Satz mit
    Formel darf trotzdem nie beim schnellen Modell landen."""
    big = FakeLLM(reply="Vielen Dank, die Formel lautet [[M1]]. Bis bald.")
    fast = FakeLLM(reply="verschluckt den Marker")
    p, _, injector = make_pipeline(FORMEL_RAW, llm=big, fast_llm=fast)
    p.auto_latex = True
    assert p.process(AUDIO, 16000) == "ok"
    assert fast.calls == []          # das kleine Modell wurde nie gefragt
    assert big.calls
    assert "$x^{2} + 1$" in injector.injected[0]
