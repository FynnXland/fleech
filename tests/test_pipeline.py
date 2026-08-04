import numpy as np
import pytest

from fleech.document import DocumentTracker
from fleech.pipeline import Pipeline


class FakeSTT:
    def __init__(self, text):
        self.text = text
        self.prompts = []

    def transcribe(self, audio, samplerate, initial_prompt=None):
        self.prompts.append(initial_prompt)
        return self.text


class FakeLLM:
    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = []
        self.audio_calls = []

    def complete(self, system_prompt, user_text):
        self.calls.append((system_prompt, user_text))
        if self.error:
            raise self.error
        return self.reply

    def complete_with_audio(self, system_prompt, user_text, wav_bytes):
        self.audio_calls.append((system_prompt, user_text, wav_bytes))
        if self.error:
            raise self.error
        return self.reply


class FakeInjector:
    def __init__(self):
        self.injected = []
        self.replacements = []  # (geloeschte_zeichen, neuer_text)

    def inject(self, text):
        self.injected.append(text)

    def replace_tail(self, delete_chars, text):
        self.replacements.append((delete_chars, text))


AUDIO = np.zeros(16000, dtype=np.float32)  # 1 s


def make_tracker():
    t = DocumentTracker()
    t._window = 42
    t.sync_window = lambda: None  # Fenster-Logik in Unit-Tests neutralisieren
    return t


def make_pipeline(stt_text, llm=None, command_llm=None, fast_llm=None):
    injector = FakeInjector()
    llm = llm or FakeLLM(reply="sauberer Text.")
    p = Pipeline(
        stt=FakeSTT(stt_text),
        cleanup_llm=llm,
        fast_llm=fast_llm,
        injector=injector,
        cleanup_prompt="SYSTEM",
        trigger_word="Redax",
        command_llm=command_llm,
        command_prompt="COMMAND-SYSTEM",
        tracker=make_tracker(),
    )
    return p, llm, injector


def test_happy_path_injects_cleaned_text():
    p, llm, injector = make_pipeline("also äh der text halt")
    p.process(AUDIO, 16000)
    assert injector.injected == ["sauberer Text."]
    system, user = llm.calls[0]
    assert system == "SYSTEM"
    assert "also äh der text halt" in user           # Roh-Transkript im User-Turn …
    assert "⟦TRANSKRIPT⟧" in user                     # … als abgegrenzter Datenblock


RAW_NONTRIVIAL = "also äh das hier ist der rohe text mit ein paar mehr worten"
# Realistische Cleanup-Ausgabe dazu: wortgetreu, nur Fuellwoerter/Interpunktion. Eine
# beziehungslose Fake-Antwort wuerde (zu Recht) den Wortgetreue-Guard ausloesen.
CLEAN_NONTRIVIAL = "Das hier ist der rohe Text mit ein paar mehr Worten."

# -- Wortgetreue + Halluzination am Textende -------------------------------------------

VERBATIM_RAW = ("also das ding ist halt komplett kaputt gegangen und wir kriegen das "
                "nicht mehr hin")


def test_appended_sentence_is_trimmed():
    """Fehlerbild: das Modell haengt einen Schlusssatz an, den niemand gesagt hat.
    Der globale Grounding-Wert faellt dadurch kaum — der Schwanz-Guard muss greifen."""
    llm = FakeLLM(reply=(
        "Das Ding ist komplett kaputt gegangen, und wir kriegen das nicht mehr hin. "
        "Bei Rückfragen melde dich gerne jederzeit."
    ))
    p, _, injector = make_pipeline(VERBATIM_RAW, llm=llm)
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [
        "Das Ding ist komplett kaputt gegangen, und wir kriegen das nicht mehr hin."
    ]


def test_first_sentence_is_never_trimmed():
    """Auch wenn die Ausgabe insgesamt schwach gestuetzt ist, bleibt mindestens ein
    Satz stehen — der globale Grounding-Guard ist fuer den Totalfall zustaendig."""
    from fleech.textfilter import trim_unsupported_tail

    text, removed = trim_unsupported_tail("Völlig anderer Inhalt hier.", VERBATIM_RAW)
    assert removed == 0 and text == "Völlig anderer Inhalt hier."


def test_formula_sentences_are_never_trimmed():
    """LaTeX teilt naturgemaess keine Woerter mit dem gesprochenen Text — ein
    Formel-Satz am Ende darf nie als „erfunden" verworfen werden."""
    from fleech.textfilter import trim_unsupported_tail

    cleaned = "Der Server ist offline gewesen. Die Formel lautet $x^2+1$."
    text, removed = trim_unsupported_tail(cleaned, "der server ist offline gewesen")
    assert removed == 0 and text == cleaned


VERBATIM_CLEAN = "Das Ding ist komplett kaputt gegangen, und wir kriegen das nicht mehr hin."


def test_paraphrase_triggers_stricter_retry():
    """Straffen ist Umformulieren: die Ausgabe erfindet nichts (Grounding bleibt hoch),
    laesst aber die Haelfte weg → EIN strengerer Zweitversuch, dessen wortgetreues
    Ergebnis dann eingefuegt wird."""
    replies = iter(["Das Ding ist kaputt.", VERBATIM_CLEAN])
    llm = FakeLLM(reply="")
    llm.complete = lambda system, user: (llm.calls.append((system, user)),
                                         next(replies))[1]
    p, _, injector = make_pipeline(VERBATIM_RAW, llm=llm)
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [VERBATIM_CLEAN]
    assert len(llm.calls) == 2                      # genau ein Zweitversuch
    assert "UMFORMULIERT" in llm.calls[1][0]        # mit expliziter Ansage


def test_persistent_paraphrase_falls_back_to_raw():
    """Strafft auch der Zweitversuch, gewinnt das Roh-Transkript — lieber unbereinigt
    als in fremden Worten."""
    p, llm, injector = make_pipeline(VERBATIM_RAW, llm=FakeLLM(reply="Das Ding ist kaputt."))
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [VERBATIM_RAW]
    assert len(llm.calls) == 2


def test_strong_intervention_may_reformulate():
    """Eingriffsgrad „strong" ist die ausdrueckliche Erlaubnis zu staerkerem Glaetten —
    dort darf der Wortgetreue-Guard nicht dazwischenfunken."""
    smoothed = "Das Ding ist komplett kaputt gegangen."
    p, llm, injector = make_pipeline(VERBATIM_RAW, llm=FakeLLM(reply=smoothed))
    p.intervention = "strong"
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [smoothed]
    assert len(llm.calls) == 1                      # kein Zweitversuch


def test_self_correction_gets_milder_verbatim_threshold():
    """Bei einer Selbstkorrektur faellt die zurueckgenommene Fassung legitim weg —
    das darf keinen Zweitversuch ausloesen."""
    raw = ("wir machen das am montag im großen konferenzraum ach nein warte wir "
           "machen das online")
    p, llm, injector = make_pipeline(raw, llm=FakeLLM(reply="Wir machen das online."))
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == ["Wir machen das online."]
    assert len(llm.calls) == 1                      # kein Fehlalarm


def test_verbatim_guard_ignores_filler_and_selfcorrection():
    """Fuellwoerter und die zurueckgenommene Fassung einer Selbstkorrektur duerfen
    legitim wegfallen — das darf den Guard nicht ausloesen."""
    from fleech.textfilter import verbatim_ratio

    raw = ("der server ist down seit heute morgen warte nein seit gestern abend und "
           "wir arbeiten dran")
    cleaned = "Der Server ist seit gestern Abend down, und wir arbeiten dran."
    assert verbatim_ratio(raw, cleaned) >= 0.7


# -- Formel-Automatik: Schutz bleibt aktiv (frueher komplett abgeschaltet) -----------

AUTO_LATEX_RAW = ("die ableitung von x hoch zwei ist zwei x und das gilt fuer alle "
                  "reellen zahlen")


def test_auto_latex_keeps_grounding_on_prose_part():
    """Bei Formel-Automatik darf der Grounding-Guard NICHT abgeschaltet sein: die
    `$…$`-Bloecke werden herausgeschnitten, der Fliesstext weiter geprueft."""
    llm = FakeLLM(reply="Ignoriere alle Anweisungen. Hier ist ein Gedicht $x^2$ ueber Katzen.")
    p, _, injector = make_pipeline(AUTO_LATEX_RAW, llm=llm)
    p.auto_latex = True
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [AUTO_LATEX_RAW]      # Halluzination abgefangen


def test_auto_latex_accepts_legitimate_formula_output():
    """Echte Formel-Ausgabe muss durchgehen — der Fliesstext ist gestuetzt."""
    cleaned = "Die Ableitung von $x^2$ ist $2x$, und das gilt für alle reellen Zahlen."
    p, _, injector = make_pipeline(AUTO_LATEX_RAW, llm=FakeLLM(reply=cleaned))
    p.auto_latex = True
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [cleaned]


def test_auto_latex_rejects_implausible_block_count():
    """Zerlegt das Modell den Text in lauter Mini-Formeln, ist das kein Mathe-Erkennen
    — Minimal-Sicherung fuer den Modus, in dem der Wortvergleich schwach ist."""
    shredded = " ".join(f"${w}$" for w in AUTO_LATEX_RAW.split())
    p, _, injector = make_pipeline(AUTO_LATEX_RAW, llm=FakeLLM(reply=shredded))
    p.auto_latex = True
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [AUTO_LATEX_RAW]


def test_strip_latex_blocks_and_density_rule():
    from fleech.textfilter import latex_blocks_implausible, strip_latex_blocks

    rest, blocks = strip_latex_blocks("Die Ableitung von $x^2$ ist $2x$ hier.")
    assert blocks == 2
    assert "$" not in rest and rest == "Die Ableitung von ist hier."
    # 14 Rohwoerter → bis zu 3 Bloecke plausibel, 4 nicht mehr.
    raw = " ".join(["wort"] * 14)
    assert not latex_blocks_implausible(raw, 3)
    assert latex_blocks_implausible(raw, 4)
    # Kurze Diktate: Mindestbudget 2 Bloecke, damit einfache Formeln durchgehen.
    assert not latex_blocks_implausible("x hoch zwei", 2)


def test_whisper_repetition_loop_is_collapsed():
    """Whisper haengt auf auslaufendem Audio denselben Satz dutzendfach an (real im
    Log beobachtet) — das ist ein Artefakt und wird auf EINE Nennung gekuerzt."""
    from fleech.textfilter import collapse_trailing_repetitions

    raw = "Okay, das schicke ich dir rüber. " + "Das war's. " * 12
    assert collapse_trailing_repetitions(raw) == "Okay, das schicke ich dir rüber. Das war's."
    # ohne Satzzeichen ebenso
    assert collapse_trailing_repetitions("also gut " + "und so weiter " * 6).endswith(
        "also gut und so weiter"
    )
    # echte Rhetorik ueberlebt: dreifaches Einzelwort bleibt stehen
    assert collapse_trailing_repetitions("das geht so nicht nein nein nein") == \
        "das geht so nicht nein nein nein"
    # zweifache Wiederholung ist keine Schleife
    assert collapse_trailing_repetitions("bis dann. bis dann.") == "bis dann. bis dann."


def test_hallucinated_tail_is_dropped():
    """Zerfallener Schwanz OHNE saubere Schleife — der zweite Halluzinations-Typ.

    Wortlaut aus dem echten Log (Diktat 13:57:06): Die Erkennung franst aus und
    wiederholt ein Fachwort verstreut, mit Sprachwechseln dazwischen. Kein
    Teilstueck wiederholt sich unmittelbar, also greift der Schleifen-Guard nicht.
    """
    from fleech.textfilter import strip_hallucinated_tail

    raw = ("Aber ja, da weiß ich wohl der Fehler, aber kannst du es selber in meiner "
           "Datei einmal korrigieren? Am besten in perfekter Klausulnotation zu dem "
           "Punkt, wo wir jetzt gerade sind. Klausulnotation Am besten! Mit einer "
           "F1-B-5-9-105-1015 2019 Polski Der Konflikt L conflicts des Klausulnotation "
           "Kurv für das Klausulnotation Klausulnotation Dr Klausulnotation "
           "Klausulnotation Vergnügen")
    cleaned, dropped = strip_hallucinated_tail(raw)
    assert "Polski" not in cleaned and "conflicts" not in cleaned
    assert "Polski" in dropped
    # Der echte Anfang bleibt unangetastet.
    assert cleaned.startswith("Aber ja, da weiß ich wohl der Fehler")
    assert "wo wir jetzt gerade sind." in cleaned


def test_hallucination_guard_spares_real_speech():
    """Die Laengenbedingung ist der Schutz — alle drei Faelle stehen so im Log.

    Kurze Fuell-/Funktionswoerter haeuft echtes Sprechen sehr wohl. Ohne die
    Mindestwortlaenge wuerde der Guard hier zuschlagen und Gesagtes loeschen —
    besonders schlimm beim Mathe-Diktat, wo "minus" naturgemaess dicht steht.
    """
    from fleech.textfilter import strip_hallucinated_tail

    echt = [
        # Mathematik: "minus" 4x in einem Satz — voellig normal.
        "Wir haben das als eine Nullstelle und dann müssen wir noch die Determinante "
        "von t minus 1, minus 2, minus 2 und t minus 1 bestimmen, also von der Matrix.",
        # Rhetorische Wiederholung kurzer Woerter.
        "Ich glaube über alte würde ja auch gehen, das macht ja sonst eigentlich auch "
        "nicht so viel, dann gerne vorschlagen, gerne implementieren, gerne "
        "eigenständig weiterentwickeln.",
        "Fände ich zwar gut, aber da bin ich skeptisch. Da bin ich sehr, sehr, sehr "
        "skeptisch, ob wir das überhaupt dürfen.",
    ]
    for text in echt:
        cleaned, dropped = strip_hallucinated_tail(text)
        assert dropped == "", f"faelschlich verworfen: {dropped!r}"
        assert cleaned == text


def test_hallucinated_tail_never_reaches_the_model():
    """Der Guard laeuft VOR dem LLM und meldet die Loeschung.

    Beides ist wesentlich: Bekaeme das Modell den Ausschuss zu sehen, baute es ihn
    beim Bereinigen in einen plausiblen Satz ein — genau das Fehlerbild, das
    gemeldet wurde. Und `last_dropped_tail` traegt die Warnung in die Pille;
    stillschweigend loeschen darf Fleech nichts.
    """
    raw = ("Kannst du das in meiner Datei einmal korrigieren? Am besten in perfekter "
           "Klausulnotation zu dem Punkt, wo wir jetzt gerade sind. Klausulnotation "
           "Am besten! Mit einer F1-B-5 2019 Polski Der Konflikt L conflicts des "
           "Klausulnotation Kurv für das Klausulnotation Klausulnotation Dr "
           "Klausulnotation Klausulnotation Vergnügen")
    p, llm, injector = make_pipeline(raw)
    p.process(AUDIO, 16000)

    _system, user_text = llm.calls[0]
    assert "Polski" not in user_text and "conflicts" not in user_text
    assert "wo wir jetzt gerade sind." in user_text
    assert "Polski" in p.last_dropped_tail


def test_clean_dictation_reports_no_dropped_tail():
    """Kein Fehlalarm-Kanal: Ohne Halluzination bleibt die Warnung leer."""
    p, _llm, _injector = make_pipeline(
        "Das ist ein ganz normales Diktat ohne jede Wiederholung am Ende."
    )
    p.process(AUDIO, 16000)
    assert p.last_dropped_tail == ""


def test_hallucination_guard_keeps_short_dictation_whole():
    """Bleibt zu wenig echter Text stehen, wird NICHT geschnitten — dann ist das
    ganze Diktat Ausschuss und der Nutzer soll das sehen statt einen Rest."""
    from fleech.textfilter import strip_hallucinated_tail

    cleaned, dropped = strip_hallucinated_tail("Klausulnotation " * 9)
    assert dropped == ""
    assert cleaned.startswith("Klausulnotation")


def test_llm_failure_falls_back_to_raw_transcript():
    p, _, injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(error=ConnectionError("down")))
    p.process(AUDIO, 16000)
    assert injector.injected == [RAW_NONTRIVIAL]


def test_empty_llm_reply_falls_back_to_raw():
    p, _, injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply=""))
    p.process(AUDIO, 16000)
    assert injector.injected == [RAW_NONTRIVIAL]


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


def test_command_mode_without_command_llm_falls_back_to_cleanup():
    p, llm, injector = make_pipeline(
        "Hallo zusammen, hier kommt noch etwas Text. Redax, mach das alles formeller."
    )
    p.process(AUDIO, 16000)
    assert len(injector.injected) == 1
    assert llm.calls  # Cleanup wurde aufgerufen


# -- M5: Befehls-Modus ------------------------------------------------------------


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


def test_recorder_position_counts_samples():
    from fleech.audio import Recorder

    r = Recorder(16000)
    r._callback(np.zeros((8000, 1), dtype=np.float32), 8000, None, None)
    assert r.position == pytest.approx(0.5)
    r._callback(np.zeros((4000, 1), dtype=np.float32), 4000, None, None)
    assert r.position == pytest.approx(0.75)


MIX_RAW = "also äh der server ist offline gewesen"


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


PE_RAW = "ähm kannst du mir den code cleaner machen also vor allem parse config"


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


def test_auto_latex_addendum_and_grounding_guard_skipped():
    from fleech.pipeline import _AUTO_LATEX_ADDENDUM

    # Modell wandelt gesprochene Mathe zu LaTeX → wenig Wort-Ueberlappung mit dem
    # Rohtext; ohne die auto_latex-Ausnahme wuerde der Grounding-Guard faelschlich
    # auf Rohtext zurueckfallen.
    reply = "Sei $\\int_a^b f(x)\\,dx = F(b)-F(a)$ die zentrale Gleichung hier."
    p, llm, injector = make_pipeline(
        "sei das integral von a bis b von f von x gleich groß f von b minus groß f von a "
        "die zentrale gleichung hier",
        llm=FakeLLM(reply=reply),
    )
    p.auto_latex = True
    p.process(AUDIO, 16000)
    assert injector.injected == [reply]                 # LaTeX bleibt, kein Rohtext-Fallback
    assert _AUTO_LATEX_ADDENDUM in llm.calls[0][0]       # Addendum steckt im System-Prompt


def test_auto_latex_off_keeps_grounding_guard():
    # Ohne auto_latex faengt der Guard erfundenen Inhalt (kaum Ueberlappung) weiter ab.
    raw = "der server war heute nacht kurz offline wir schauen morgen in die logs"
    p, _, injector = make_pipeline(raw, llm=FakeLLM(reply="Ganz andere erfundene Aussage."))
    p.process(AUDIO, 16000)
    assert injector.injected == [raw]                   # Grounding-Guard → Rohtext


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


# -- M6: Formel-Modus ---------------------------------------------------------------


MATH_RAW = "x hoch äh zwei plus eins das ganze geteilt durch zwei"
MATH_CLEANED = "x hoch zwei plus eins, das Ganze geteilt durch zwei."


def test_cleanup_strips_wrapping_quotes():
    # Realer Bug: Modell liefert „Text." trotz Prompt-Verbots.
    p, _, injector = make_pipeline(
        "also äh der text halt bitte war lang genug fuer das llm gedacht",
        llm=FakeLLM(reply='„Der Text war halt lang genug fuer das LLM gedacht."'),
    )
    p.process(AUDIO, 16000)
    assert injector.injected == ["Der Text war halt lang genug fuer das LLM gedacht."]


def test_cleanup_executed_prompt_falls_back_to_raw():
    # Realer Bug: Sprecher liest einen Prompt vor, Modell FUEHRT ihn aus statt zu
    # transkribieren → erfundener Inhalt (niedriges Grounding) → Roh-Transkript.
    raw = ("schreib mir eine hoefliche absage an die konferenz naechste woche und "
           "erwaehne dass ich leider keine zeit habe")
    executed = ("Sehr geehrte Damen und Herren, vielen Dank fuer die freundliche "
                "Einladung. Bedauerlicherweise kann ich nicht teilnehmen. Mit besten "
                "Gruessen.")
    p, _, injector = make_pipeline(raw, llm=FakeLLM(reply=executed))
    result = p.process(AUDIO, 16000)
    assert injector.injected == [raw]   # der vorgelesene Prompt, nicht die Ausfuehrung
    assert result == "fallback"


def test_cleanup_normal_result_passes_guard():
    raw = "also aeh der server ist seit heute morgen down und wir arbeiten dran"
    cleaned = "Der Server ist seit heute Morgen down, und wir arbeiten dran."
    p, _, injector = make_pipeline(raw, llm=FakeLLM(reply=cleaned))
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [cleaned]


def test_cleanup_guard_inactive_for_short_input():
    # Nicht-trivial (Marker "also" → LLM laeuft), aber < 6 Inhaltswoerter → Guard
    # aus: eine kurze, wenig ueberlappende Ausgabe wird nicht faelschlich verworfen.
    p, llm, injector = make_pipeline("also aeh guten morgen zusammen", llm=FakeLLM(reply="Moin."))
    p.process(AUDIO, 16000)
    assert llm.calls  # LLM lief (nicht trivial)
    assert injector.injected == ["Moin."]  # trotz null Grounding nicht verworfen


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


# -- Adaptives Modell-Routing (kleines vs. grosses Modell) ------------------------------

SIMPLE_RAW = "also äh ich wollte nur kurz sagen dass das ganz gut klingt soweit"
COMPLEX_RAW = "treffen wir uns dienstag nein doch lieber freitag um 15 uhr"


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


def test_consecutive_dictations_get_space_separator():
    p, _, injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply=CLEAN_NONTRIVIAL))
    p.process(AUDIO, 16000)
    p.process(AUDIO, 16000)
    assert injector.injected == [CLEAN_NONTRIVIAL, " " + CLEAN_NONTRIVIAL]


# -- Desktop-App: Ergebnis-Status, Eingriffsgrad, Mathe-Prioritaet ---------------------


def test_process_returns_status_codes():
    p, _, _ = make_pipeline("hallo welt")
    assert p.process(AUDIO, 16000) == "ok"
    assert p.process(np.zeros(100, dtype=np.float32), 16000) == "too_short"
    p2, _, _ = make_pipeline("")
    assert p2.process(AUDIO, 16000) == "empty"


def test_llm_failure_returns_fallback_status():
    p, _, injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(error=ConnectionError("down")))
    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [RAW_NONTRIVIAL]


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


# -- Woerterbuch, App-Profile, anweisungs-sensitiver Guard --------------------------------


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


def test_app_profile_override_minimal_skips_llm():
    p, llm, injector = make_pipeline(RAW_NONTRIVIAL)
    p.process(AUDIO, 16000, intervention_override="minimal")
    assert llm.calls == []                       # App-Profil: kein LLM-Eingriff
    assert injector.injected == [RAW_NONTRIVIAL]
    # Override gilt nur pro Durchlauf — die Grundeinstellung bleibt unveraendert.
    assert p.intervention == "standard"
    p.process(AUDIO, 16000)
    assert llm.calls                             # ohne Override laeuft das LLM wieder


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


def test_stt_hint_contains_trigger_word_priming():
    p, _, _injector = make_pipeline(RAW_NONTRIVIAL)
    p.process(AUDIO, 16000)
    prompt = p.stt.prompts[-1]
    assert prompt is not None and "Redax" in prompt  # Signalwort-Priming immer aktiv


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


# -- Text-Bausteine --------------------------------------------------------------

SNIPPET_LINES = ["Signatur => Viele Grüße\nAlex"]


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


def test_abgeschnittene_cleanup_ausgabe_faellt_auf_rohtext_zurueck():
    """Kontextfenster voll → lieber unbereinigt und VOLLSTAENDIG.

    Das Fehlerbild ist heimtueckisch: Was das Modell geliefert hat, ist korrekt
    bereinigt — es endet nur mitten im Satz. Kein inhaltlicher Guard schlaegt an,
    weil nichts Falsches dasteht; es fehlt bloss der Rest. Deshalb wertet die
    Pipeline `last_truncated` des Clients aus (real: 610 Woerter rein, 84 raus).
    """
    raw = ("Also was ich gerade aktuell ein bisschen schwierig finde ist dass die "
           "Navigation noch nicht so richtig sitzt und ich glaube wir sollten da "
           "nochmal ran und zwar konkret an den Header und die Unterpunkte darin.")
    llm = FakeLLM(reply="Also, was ich gerade aktuell ein bisschen schwierig finde, ist,")
    llm.last_truncated = True
    p, _llm, injector = make_pipeline(raw, llm=llm)
    result = p.process(AUDIO, 16000)

    assert result == "fallback"
    assert injector.injected == [raw]      # vollstaendig, unbereinigt


def test_vollstaendige_ausgabe_bleibt_unangetastet():
    """Gegenprobe: ohne Abschneiden gewinnt weiter die bereinigte Fassung."""
    llm = FakeLLM(reply=CLEAN_NONTRIVIAL)
    llm.last_truncated = False
    p, _llm, injector = make_pipeline(RAW_NONTRIVIAL, llm=llm)
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == [CLEAN_NONTRIVIAL]


def test_fremdsprachiger_schwanz_wird_verworfen():
    """Der real gemeldete Fall: Nach dem Diktat lief Musik weiter, Whisper machte
    daraus mehrsprachigen Wortsalat. Kein Guard griff — keine Wiederholung, kein
    dominantes Wort. Der sichere Marker ist die fremde SCHRIFT: Kyrillisch oder
    Koreanisch in einem deutschen Diktat kann nur geraten sein.
    """
    from fleech.textfilter import strip_foreign_tail

    raw = ("Analysiere das dir vorliegende Plugin. Es ist ein Minecraft-Bot, der auf "
           "einem Server läuft. Gib mir praxisnahe Anweisungen, was ich zu tun habe. "
           "Wie teste ich das? Und so weiter und so fort. "
           "Und jetzt Porque dice War, war es ein bisschen Nähan. "
           "Denn Sie ладно, da sind schon mal ein bisschen más schnell.")
    cleaned, dropped = strip_foreign_tail(raw)

    assert "ладно" not in cleaned
    assert "ладно" in dropped
    assert cleaned.startswith("Analysiere das dir vorliegende Plugin.")
    assert "Und so weiter und so fort." in cleaned


def test_griechische_buchstaben_bleiben_unangetastet():
    """DIE Fehlalarm-Gefahr: α, β und λ stehen regelmäßig in Formeln. Griechisch
    ist deshalb bewusst NICHT in der Zeichenliste — ein Mathe-Diktat darf nie
    beschnitten werden."""
    from fleech.textfilter import strip_foreign_tail

    for text in (
        "Die Ableitung von e hoch λ x ist λ mal e hoch λ x, das gilt für alle x.",
        "Sei α der Winkel und β die Gegenkathete, dann folgt daraus der Sinussatz.",
        "Das Integral über φ von 0 bis 2π ergibt genau den Umfang des Kreises.",
    ):
        cleaned, dropped = strip_foreign_tail(text)
        assert dropped == "", f"faelschlich verworfen: {dropped!r}"
        assert cleaned == text


def test_fremdschrift_schneidet_nicht_wenn_zu_wenig_bleibt():
    """Ist praktisch das ganze Diktat Ausschuss, wird NICHT beschnitten — dann soll
    der Nutzer sehen, was passiert ist, statt einen sinnlosen Rest zu bekommen."""
    from fleech.textfilter import strip_foreign_tail

    cleaned, dropped = strip_foreign_tail("Кто это ладно 진짜 was")
    assert dropped == ""
    assert cleaned.startswith("Кто")


def test_pipeline_verwirft_fremdschrift_vor_dem_modell():
    """Der Ausschuss darf das LLM nie erreichen — sonst baut es ihn in einen
    plausiblen Satz ein. Und die Loeschung wird gemeldet."""
    raw = ("Analysiere bitte das Plugin und gib mir danach eine Schritt für Schritt "
           "Anleitung dazu. Wie teste ich das? Und so weiter und so fort. "
           "Denn Sie ладно, da sind schon mal ein bisschen más schnell.")
    p, llm, _injector = make_pipeline(raw)
    p.process(AUDIO, 16000)

    _system, user_text = llm.calls[0]
    assert "ладно" not in user_text
    assert "Und so weiter und so fort." in user_text
    assert "ладно" in p.last_dropped_tail


# -- Bedeutungs-Erhaltung (v3.9.0, aus externem Gutachten) -------------------------

def test_verlorene_verneinung_wird_erkannt():
    """Die Lücke aus dem Gutachten: Das Modell dreht die AUSSAGE, ohne fremde Wörter
    einzuführen. Wortüberlappung und Wortgetreue bleiben hoch — alle bisherigen
    Schichten sind blind dafür."""
    from fleech.textfilter import meaning_flipped

    raw = "die miete ist im januar noch nicht überwiesen"
    assert meaning_flipped(raw, "Die Miete ist im Januar noch nicht überwiesen.") == ""
    assert "Verneinung" in meaning_flipped(raw, "Die Miete ist im Januar überwiesen.")


def test_verlorene_zahl_wird_erkannt():
    """Real aus dem Verlauf: „Heute ist der 6.7." wurde zu „der 6., oder der 7.?" —
    und in einem anderen Diktat verschwanden zwei Geldbeträge ersatzlos."""
    from fleech.textfilter import meaning_flipped

    raw = "die rechnung über 22,60 euro ist noch offen"
    assert meaning_flipped(raw, "Die Rechnung über 22,60 Euro ist noch offen.") == ""
    treffer = meaning_flipped(raw, "Die Rechnung ist noch offen.")
    assert "22,60" in treffer


def test_selbstkorrektur_darf_die_verneinung_verlieren():
    """Wer sich korrigiert, nimmt die Verneinung selbst zurück — das ist richtig so
    und darf keinen Fehlalarm auslösen."""
    raw = ("wir treffen uns nicht am montag ach nein warte doch wir treffen uns "
           "am montag um drei")
    llm = FakeLLM(reply="Wir treffen uns am Montag um drei.")
    p, _llm, injector = make_pipeline(raw, llm=llm)

    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == ["Wir treffen uns am Montag um drei."]
    assert len(llm.calls) == 1                      # kein Zweitversuch


def test_gedrehte_aussage_loest_zweitversuch_aus():
    """Erst ein Zweitversuch mit Ansage — erst wenn auch der die Aussage dreht,
    gewinnt das Roh-Transkript."""
    raw = "der server ist seit gestern nicht mehr erreichbar gewesen"
    replies = iter(["Der Server ist seit gestern erreichbar gewesen.",
                    "Der Server ist seit gestern nicht mehr erreichbar gewesen."])
    llm = FakeLLM(reply="")
    llm.complete = lambda s, u: (llm.calls.append((s, u)), next(replies))[1]
    p, _llm, injector = make_pipeline(raw, llm=llm)

    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected == ["Der Server ist seit gestern nicht mehr erreichbar gewesen."]
    assert len(llm.calls) == 2


def test_hartnaeckig_gedrehte_aussage_faellt_auf_rohtext():
    raw = "die zahlung ist nicht eingegangen und wir warten weiterhin darauf"
    llm = FakeLLM(reply="Die Zahlung ist eingegangen und wir warten weiterhin darauf.")
    p, _llm, injector = make_pipeline(raw, llm=llm)

    assert p.process(AUDIO, 16000) == "fallback"
    assert injector.injected == [raw]
