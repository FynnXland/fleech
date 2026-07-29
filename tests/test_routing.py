from fleech.routing import Mode, detect_mode, text_before_trigger

TRIGGER = "Redax"


def test_text_before_trigger_drops_safeword_and_instruction():
    # Nur der Diktat-Teil vor dem Safe-Word — Safe-Word + Anweisung fallen weg.
    assert text_before_trigger(
        "Das ist ein Test. Redax, schreib alles rückwärts.", TRIGGER
    ) == "Das ist ein Test."
    # Reiner Befehl (Trigger am Anfang) → nichts davor.
    assert text_before_trigger("Redax, mach das formeller.", TRIGGER) == ""
    # Erstes Vorkommen zaehlt; alles ab da faellt weg.
    assert text_before_trigger(
        "Frag mal. Redax? Formulier das um.", TRIGGER
    ) == "Frag mal."
    # Kein Trigger → unveraendert.
    assert text_before_trigger("ganz normales diktat", TRIGGER) == "ganz normales diktat"


def test_plain_dictation_is_cleanup():
    assert detect_mode("also das projekt läuft gut", TRIGGER) is Mode.CLEANUP


def test_trigger_word_routes_to_command():
    raw = "Der Umsatz stieg um 20 Prozent. Redax, mach den letzten Satz formeller."
    assert detect_mode(raw, TRIGGER) is Mode.COMMAND


def test_trigger_case_insensitive_and_with_punctuation():
    assert detect_mode("redax, lösch den letzten satz", TRIGGER) is Mode.COMMAND


def test_trigger_not_matched_as_substring():
    assert detect_mode("die redaxion hat zugestimmt", TRIGGER) is Mode.CLEANUP


def test_word_formel_alone_is_not_math():
    assert detect_mode("die formel eins läuft heute im fernsehen", TRIGGER) is Mode.CLEANUP


def test_empty_trigger_never_matches():
    assert detect_mode("irgendwas", "") is Mode.CLEANUP


# -- Signal-Endwort: Befehl + Fortsetzung in einer Aufnahme ------------------------------


def test_split_command_continuation_basic():
    from fleech.routing import split_command_continuation

    cmd, cont = split_command_continuation(
        "Kimono, mach das formeller. Kimono Ende. Und hier geht es weiter.", "Kimono"
    )
    assert cmd == "Kimono, mach das formeller."
    assert cont == "Und hier geht es weiter."


def test_split_command_continuation_asr_variants():
    from fleech.routing import split_command_continuation

    for endform in ("Kimono Ende", "Kimono-Ende", "Kimonoende", "Kimono, Ende"):
        cmd, cont = split_command_continuation(
            f"Kimono, kürze das. {endform} weiter gehts", "Kimono"
        )
        assert cmd == "Kimono, kürze das.", endform
        assert cont == "weiter gehts", endform


def test_split_command_continuation_without_end_word():
    from fleech.routing import split_command_continuation

    raw = "Kimono, mach den letzten Satz formeller."
    assert split_command_continuation(raw, "Kimono") == (raw, "")
    assert split_command_continuation(raw, "") == (raw, "")
