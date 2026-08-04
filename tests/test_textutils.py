"""Rahmen um den LLM-Call: Anfuehrungszeichen aus der Modellantwort schaelen."""

from fleech.textutils import strip_wrapping_quotes


def test_strips_german_quotes_real_case():
    assert strip_wrapping_quotes(
        "„Oh mein Gott, es funktioniert und es sieht sehr geil aus.\""
    ) == "Oh mein Gott, es funktioniert und es sieht sehr geil aus."


def test_strips_various_quote_pairs():
    assert strip_wrapping_quotes('"Hallo Welt."') == "Hallo Welt."
    assert strip_wrapping_quotes("„Hallo Welt.“") == "Hallo Welt."
    assert strip_wrapping_quotes("»Hallo Welt.«") == "Hallo Welt."
    assert strip_wrapping_quotes("“Hallo Welt.”") == "Hallo Welt."


def test_strips_double_wrapping_but_not_endless():
    assert strip_wrapping_quotes('"„Hallo.""') == "Hallo."


def test_inner_quotes_untouched():
    text = 'Er sagte „bis morgen" und ging.'
    assert strip_wrapping_quotes(text) == text


def test_quote_only_at_one_end_untouched():
    assert strip_wrapping_quotes('"Zitat am Anfang aber nicht am Ende') == \
        '"Zitat am Anfang aber nicht am Ende'


def test_short_or_empty_texts_safe():
    assert strip_wrapping_quotes('"') == '"'
    assert strip_wrapping_quotes("") == ""


# -- Trivialheits-Heuristik (Komplexitaets-Routing ohne LLM-Roundtrip) -------------------
