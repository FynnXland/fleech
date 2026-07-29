import pytest

from fleech.commands import build_user_message, parse_command_json


def test_build_user_message():
    msg = build_user_message("Alter Kontext.", "Redax, mach das formeller.")
    assert msg == 'KONTEXT: "Alter Kontext."\nÄUSSERUNG: "Redax, mach das formeller."'


def test_parse_plain_json():
    cmd = parse_command_json(
        '{"append_text": "Hallo.", "replace_scope": "none", "replacement": ""}'
    )
    assert cmd.append_text == "Hallo."
    assert cmd.replace_scope == "none"
    assert cmd.replacement == ""


def test_parse_fenced_json():
    cmd = parse_command_json(
        'Hier das Ergebnis:\n```json\n{"append_text": "", "replace_scope": "last_sentence", "replacement": "Neu."}\n```'
    )
    assert cmd.replace_scope == "last_sentence"
    assert cmd.replacement == "Neu."


def test_parse_json_with_surrounding_prose():
    cmd = parse_command_json(
        'Antwort: {"append_text": "X", "replace_scope": "dictated", "replacement": "Y"} fertig'
    )
    assert cmd.append_text == "X"
    assert cmd.replacement == "Y"


def test_missing_keys_get_defaults():
    cmd = parse_command_json('{"append_text": "Nur Text."}')
    assert cmd.replace_scope == "none"
    assert cmd.replacement == ""


def test_unknown_scope_becomes_as_described():
    cmd = parse_command_json(
        '{"append_text": "T", "replace_scope": "letzter_satz", "replacement": "R"}'
    )
    assert cmd.replace_scope == "as_described"
    assert cmd.append_text == "T"


def test_garbage_raises():
    with pytest.raises(ValueError):
        parse_command_json("Ich kann leider kein JSON erzeugen.")
    with pytest.raises(ValueError):
        parse_command_json('{"append_text": kaputt}')


# -- Plausibilitaets-Check (halluzinierte replacements) ---------------------------------


def test_legitimate_reformulation_is_plausible():
    from fleech.commands import replacement_plausible

    assert replacement_plausible(
        "Der Umsatz stieg um 20 Prozent.",
        "Der Umsatz verzeichnete einen Anstieg von 20 Prozent.",
    )


def test_bullet_list_transformation_is_plausible():
    from fleech.commands import replacement_plausible

    assert replacement_plausible(
        "Die drei Kernpunkte sind Skalierbarkeit, Sicherheit und Kosten.",
        "Die drei Kernpunkte sind:\n- Skalierbarkeit\n- Sicherheit\n- Kosten",
    )


def test_invented_description_is_implausible():
    from fleech.commands import replacement_plausible

    # Realer Fehlermodus: erfundener Satz, der die Situation beschreibt.
    assert not replacement_plausible(
        "Ich rede jetzt einfach ein bisschen, um Fülltext zu haben.",
        "Der Sprecher diktiert einen Beispielsatz zur Demonstration der Funktion.",
    )


def test_deletion_and_short_targets_pass():
    from fleech.commands import replacement_plausible

    assert replacement_plausible("Weg damit.", "")          # Loeschung
    assert replacement_plausible("", "irgendwas")            # kein Vergleichsziel
    assert replacement_plausible("Hallo Tom.", "Sehr geehrter Herr Tom.")  # <3 Woerter


def test_whole_document_friendlier_rewrite_is_plausible():
    from fleech.commands import replacement_plausible

    # Bauplan-Beispiel 2: staerkere Umformulierung, teilt aber Kernbegriffe.
    assert replacement_plausible(
        "Hi Tom, danke für die Mail. Ich schaue mir das morgen an.",
        "Hallo Tom,\n\nvielen Dank für deine Mail! Ich schaue mir das gleich morgen "
        "in Ruhe an.\n\nBeste Grüße",
    )


def test_strong_reformulation_with_inflection_is_plausible():
    from fleech.commands import replacement_plausible

    # Realer False-Positive-Fall: legitime starke Umformulierung, "Server"→"Servers"
    # (Flexion) — Praefix-Matching muss das als Ueberlappung werten.
    assert replacement_plausible(
        "Der Server war heute Nacht kurz offline.",
        "Es kam zu einem vorübergehenden Ausfall des Servers in der vergangenen Nacht.",
    )


def test_numbers_count_as_content_words():
    from fleech.commands import content_words

    assert "20" in content_words("stieg um 20 %")
    assert "um" not in content_words("stieg um 20 %")  # zu kurz, keine Zahl


# -- Anweisungs-sensitive Guard-Schwelle -------------------------------------------------


def test_overlap_threshold_translation_disables_guard():
    from fleech.commands import overlap_threshold_for

    assert overlap_threshold_for("Kimono, übersetz das ins Englische") is None
    assert overlap_threshold_for("Kimono, mach das auf Englisch") is None


def test_overlap_threshold_compression_is_lowered():
    from fleech.commands import COMPRESSION_MIN_OVERLAP, overlap_threshold_for

    assert overlap_threshold_for("Kimono, kürze den letzten Absatz") == COMPRESSION_MIN_OVERLAP
    assert overlap_threshold_for("Kimono, fasse das Ganze zusammen") == COMPRESSION_MIN_OVERLAP


def test_overlap_threshold_default_for_normal_commands():
    from fleech.commands import MIN_REPLACEMENT_OVERLAP, overlap_threshold_for

    assert overlap_threshold_for("Kimono, mach den letzten Satz formeller") == MIN_REPLACEMENT_OVERLAP


def test_sounds_like_deletion():
    from fleech.commands import sounds_like_deletion

    assert sounds_like_deletion("Kimono, lösch den letzten Satz")
    assert sounds_like_deletion("Kimono, vergiss das")
    assert sounds_like_deletion("Kimono, mach den Absatz weg")
    assert not sounds_like_deletion("Kimono, verwende statt Entwickler LLM")
    assert not sounds_like_deletion("Kimono, mach das formeller")


def test_replacement_length_cap():
    """Deckel gegen Ausreisser: umformulieren ja, Aufsatz schreiben nein."""
    from fleech.commands import replacement_too_long

    ziel = "Der Server ist ausgefallen."          # 27 Zeichen
    assert not replacement_too_long(ziel, "Der Server ist gestern ausgefallen.")
    assert not replacement_too_long(ziel, "x" * 280)   # 3x27+200 = 281 → gerade noch
    assert replacement_too_long(ziel, "x" * 400)
    assert not replacement_too_long("", "beliebig lang")  # kein Ziel → kein Deckel


def test_classify_command_loeschen_schlaegt_kuerzen():
    """Vorrang zaehlt: „lösch die Zusammenfassung" ist eine Löschung."""
    from fleech.commands import classify_command

    assert classify_command("Redax, lösch die Zusammenfassung") == "Löschen"
    assert classify_command("Redax, übersetze das ins Englische") == "Übersetzen"
    assert classify_command("Redax, kürz das mal") == "Kürzen"
    assert classify_command("Redax, mach das formeller") == "Umformulieren"
    assert classify_command("") == "Umformulieren"
