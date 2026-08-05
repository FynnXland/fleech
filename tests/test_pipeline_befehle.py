"""Safe-Word-Befehle: „Redax, …“ — anhaengen, ersetzen, loeschen.

Durchgehende Regel: Scheitert ein Befehl (kaputtes JSON, unplausible
Ersetzung, leerer Puffer), faellt die Pipeline auf normales Cleanup zurueck.
Das Diktat geht nie verloren, und das Safe-Word landet nie im Text.
"""

import numpy as np

from pipelinehelpers import AUDIO, FakeLLM, make_pipeline

def test_command_mode_without_command_llm_falls_back_to_cleanup():
    p, llm, injector = make_pipeline(
        "Hallo zusammen, hier kommt noch etwas Text. Redax, mach das alles formeller."
    )
    p.process(AUDIO, 16000)
    assert len(injector.injected) == 1
    assert llm.calls  # Cleanup wurde aufgerufen


def cmd_json(append="", scope="none", replacement=""):
    import json

    return json.dumps(
        {"append_text": append, "replace_scope": scope, "replacement": replacement},
        ensure_ascii=False,
    )


def test_command_append_only():
    p, _, injector = make_pipeline(
        "Wir legen die Deadline auf Montag. Redax irrelevant hier",
        command_llm=FakeLLM(reply=cmd_json(append="Wir legen die Deadline auf Montag.")),
    )
    p.process(AUDIO, 16000)
    assert injector.injected == ["Wir legen die Deadline auf Montag."]
    assert injector.replacements == []


def test_command_dictated_replace_pastes_final_version_directly():
    p, _, injector = make_pipeline(
        "Der Umsatz stieg. Redax, formeller.",
        command_llm=FakeLLM(
            reply=cmd_json(
                append="Der Umsatz stieg.",
                scope="dictated",
                replacement="Der Umsatz verzeichnete einen Anstieg.",
            )
        ),
    )
    p.process(AUDIO, 16000)
    # Kein Paste-und-sofort-wieder-loeschen: direkt die Endfassung.
    assert injector.injected == ["Der Umsatz verzeichnete einen Anstieg."]
    assert injector.replacements == []
    assert p.tracker.text == "Der Umsatz verzeichnete einen Anstieg."


def test_command_dictated_with_empty_replacement_discards_dictation():
    # "…diktierter Text. Redax, vergiss das wieder." → nichts einfuegen, nicht
    # faelschlich auf append_text zurueckfallen.
    p, _, injector = make_pipeline(
        "Peinlicher Satz. Redax, vergiss das.",
        command_llm=FakeLLM(reply=cmd_json(append="Peinlicher Satz.", scope="dictated", replacement="")),
    )
    p.process(AUDIO, 16000)
    assert injector.injected == []
    assert injector.replacements == []
    assert p.tracker.text == ""


def test_command_replaces_last_sentence_of_previous_dictation():
    command_llm = FakeLLM(
        reply=cmd_json(scope="last_sentence", replacement="Der zweite Satz, neu.")
    )
    p, _, injector = make_pipeline("Redax, letzten Satz umformulieren.", command_llm=command_llm)
    p.tracker.record_append("Erster Satz. Der zweite Satz, alt.")
    p.process(AUDIO, 16000)
    assert injector.replacements == [(len("Der zweite Satz, alt."), "Der zweite Satz, neu.")]
    assert p.tracker.text == "Erster Satz. Der zweite Satz, neu."


def test_force_command_via_button_needs_no_spoken_safeword():
    # Overlay-»-Button: force_command erzwingt den Befehls-Modus, obwohl KEIN
    # Auslösewort gesprochen wurde — die ganze Äußerung ist die Anweisung.
    command_llm = FakeLLM(
        reply=cmd_json(scope="last_sentence", replacement="Der zweite Satz, neu.")
    )
    p, _, injector = make_pipeline("formuliere den letzten Satz um", command_llm=command_llm)
    p.tracker.record_append("Erster Satz. Der zweite Satz, alt.")
    result = p.process(AUDIO, 16000, force_command=True)
    assert result == "ok"
    assert p.last_mode == "command"
    assert injector.replacements == [(len("Der zweite Satz, alt."), "Der zweite Satz, neu.")]


def _mix_audio(seconds: float = 3.0) -> np.ndarray:
    # Leises Rauschen statt Nullen: der Stille-Filter (RMS-Gate gegen Whisper-
    # Halluzinationen) darf die Text-Fenster nicht verwerfen.
    rng = np.random.default_rng(0)
    return rng.normal(0.0, 0.05, int(seconds * 16000)).astype(np.float32)


def test_failed_command_inserts_only_pre_trigger_text_no_safeword():
    # Befehl scheitert (implausibles replacement → Guard) → nur der Diktat-Teil VOR
    # dem Safe-Word; Safe-Word UND Anweisung tauchen NICHT im Ergebnis auf.
    # Leeres replacement bei scope=dictated ohne Loesch-Anweisung → Befehl scheitert.
    command_llm = FakeLLM(reply=cmd_json(scope="dictated", append="egal", replacement=""))
    p, cleanup_llm, injector = make_pipeline(
        "Also das hier ist ein laengerer Diktat-Satz mit einigen Woertern. "
        "Redax, schreib jeden Buchstaben rückwärts.",
        command_llm=command_llm,
        llm=FakeLLM(reply="Das hier ist ein längerer Diktat-Satz mit einigen Wörtern."),
    )
    result = p.process(AUDIO, 16000)
    assert result == "fallback"
    assert injector.injected == ["Das hier ist ein längerer Diktat-Satz mit einigen Wörtern."]
    joined = " ".join(injector.injected)
    assert "Redax" not in joined and "rückwärts" not in joined
    # Cleanup lief nur auf dem Text VOR dem Safe-Word (kein Safe-Word im Input).
    assert cleanup_llm.calls and "Redax" not in cleanup_llm.calls[0][1]


def test_failed_command_bad_json_strips_safeword():
    p, _cleanup, injector = make_pipeline(
        "Hallo Welt hier. Redax, mach da was draus.",
        command_llm=FakeLLM(reply="kein json"),
        llm=FakeLLM(reply="egal"),
    )
    p.process(AUDIO, 16000)
    # „Hallo Welt hier." ist trivial → ohne Cleanup unveraendert; kein Safe-Word.
    assert injector.injected == ["Hallo Welt hier."]
    assert all("Redax" not in t and "mach da" not in t for t in injector.injected)


def test_command_delete_last_sentence_via_empty_replacement():
    command_llm = FakeLLM(reply=cmd_json(scope="last_sentence", replacement=""))
    p, _, injector = make_pipeline("Redax, lösch den letzten Satz.", command_llm=command_llm)
    p.tracker.record_append("Bleibt. Weg damit.")
    p.process(AUDIO, 16000)
    assert injector.replacements == [(len("Weg damit."), "")]
    assert p.tracker.text == "Bleibt. "


def test_command_bad_json_falls_back_to_cleanup():
    cleaned = "Hallo zusammen, das ist längerer Text."
    p, cleanup_llm, injector = make_pipeline(
        "Hallo zusammen, das ist laengerer Text. Redax, mach da mal was draus.",
        command_llm=FakeLLM(reply="kein json, sorry"),
        llm=FakeLLM(reply=cleaned),
    )
    p.process(AUDIO, 16000)
    assert cleanup_llm.calls  # Fallback lief
    assert injector.injected == [cleaned]
    assert injector.replacements == []


def test_command_whole_document_applies_after_append():
    # Die Anweisung bezieht sich auf den Stand INKLUSIVE des gerade Diktierten.
    command_llm = FakeLLM(
        reply=cmd_json(append="Neuer Text.", scope="whole_document", replacement="Alles neu.")
    )
    p, _, injector = make_pipeline("Neuer Text. Redax, schreib alles um.", command_llm=command_llm)
    p.process(AUDIO, 16000)
    assert injector.injected == ["Neuer Text."]
    assert injector.replacements == [(len("Neuer Text."), "Alles neu.")]


def test_command_scope_on_empty_buffer_is_skipped():
    command_llm = FakeLLM(reply=cmd_json(scope="last_sentence", replacement="X"))
    p, _, injector = make_pipeline("Redax, letzten Satz umformulieren.", command_llm=command_llm)
    p.process(AUDIO, 16000)
    assert injector.injected == []
    assert injector.replacements == []


def test_command_hallucinated_replacement_falls_back_to_cleanup():
    # Modell erfindet einen Satz statt umzuformulieren → Plausibilitaets-Check greift.
    command_llm = FakeLLM(reply=cmd_json(
        append="Der Server war heute Nacht kurz offline.",
        scope="dictated",
        replacement="Diese Aussage wurde auf Wunsch des Nutzers angepasst und verbessert.",
    ))
    p, cleanup_llm, injector = make_pipeline(
        "Der Server war heute Nacht kurz offline. Redax, mach den letzten Satz formeller.",
        llm=FakeLLM(reply="Der Server war heute Nacht kurz offline."),  # geerdeter Cleanup
        command_llm=command_llm,
    )
    p.process(AUDIO, 16000)
    assert cleanup_llm.calls                       # Cleanup-Fallback lief
    assert injector.injected == ["Der Server war heute Nacht kurz offline."]
    assert injector.replacements == []


def test_command_plausible_replacement_still_executes():
    command_llm = FakeLLM(reply=cmd_json(
        append="Der Server war heute Nacht kurz offline.",
        scope="dictated",
        replacement="Der Server war heute Nacht voruebergehend nicht erreichbar.",
    ))
    p, cleanup_llm, injector = make_pipeline(
        "egal. Redax, mach das formeller.", command_llm=command_llm
    )
    p.process(AUDIO, 16000)
    assert injector.injected == ["Der Server war heute Nacht voruebergehend nicht erreichbar."]
    assert cleanup_llm.calls == []


def test_translation_command_bypasses_plausibility_guard():
    # Uebersetzung teilt sprachbedingt KEINE Woerter mit dem Original — der Guard
    # wuerde sie als halluziniert verwerfen. Die Anweisung hebt ihn deshalb auf.
    command_llm = FakeLLM(
        reply=cmd_json(scope="last_sentence", replacement="The meeting begins tomorrow morning.")
    )
    p, _, injector = make_pipeline(
        "Redax, übersetz das ins Englische.", command_llm=command_llm
    )
    p.tracker.record_append("Vorher. Das Treffen beginnt morgen früh.")
    p.process(AUDIO, 16000)
    assert injector.replacements == [
        (len("Das Treffen beginnt morgen früh."), "The meeting begins tomorrow morning.")
    ]


def test_command_with_end_word_continues_as_dictation():
    # "<Trigger> Ende" schliesst den Befehl ab — der Rest ist normales Diktat und
    # wird nach dem Befehl bereinigt angehaengt.
    command_llm = FakeLLM(reply=cmd_json(scope="last_sentence", replacement="Neu formuliert."))
    p, cleanup_llm, injector = make_pipeline(
        "Redax, formuliere den letzten Satz neu. Redax Ende. Und der Text geht hier weiter.",
        command_llm=command_llm,
    )
    p.tracker.record_append("Anfang. Alter Satz.")
    p.process(AUDIO, 16000)
    assert injector.replacements == [(len("Alter Satz."), "Neu formuliert.")]
    # Fortsetzung lief durch das normale Cleanup und wurde eingefuegt.
    assert cleanup_llm.calls
    assert any("geht hier weiter" in user for _sys, user in cleanup_llm.calls)
    assert injector.injected  # Fortsetzungstext kam an


def test_empty_replacement_without_deletion_instruction_is_rejected():
    # KRITISCHER REAL-BUG: "ersetze Wort X durch Y" → Modell lieferte scope=dictated
    # mit LEEREM replacement → 2701 Zeichen wurden geloescht. Jetzt: Befehl wird
    # verworfen (Cleanup-Fallback), nichts geht verloren.
    command_llm = FakeLLM(reply=cmd_json(scope="dictated", replacement=""))
    p, cleanup_llm, injector = make_pipeline(
        "Redax, verwende statt des Wortes Entwickler Large Language Model.",
        command_llm=command_llm,
    )
    p.tracker.record_append("Langer wichtiger diktierter Text mit Entwickler darin.")
    p.process(AUDIO, 16000)
    assert injector.replacements == []          # NICHTS geloescht
    # Reiner Befehl ohne Diktat davor → bei Fehlschlag wird NICHTS eingefuegt
    # (kein Safe-Word/Anweisung im Text, kein Cleanup des Rohtexts).
    assert injector.injected == []
    assert not cleanup_llm.calls
    assert p.tracker.text.startswith("Langer wichtiger")


def test_empty_replacement_with_deletion_instruction_still_works():
    command_llm = FakeLLM(reply=cmd_json(scope="last_sentence", replacement=""))
    p, _, injector = make_pipeline("Redax, lösch den letzten Satz.",
                                   command_llm=command_llm)
    p.tracker.record_append("Bleibt. Weg damit.")
    p.process(AUDIO, 16000)
    assert injector.replacements == [(len("Weg damit."), "")]
