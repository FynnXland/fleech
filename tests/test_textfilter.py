"""Qualitaets-Guards: Trivialitaet, Komplexitaet, Aufblaeh-Erkennung, Stottern."""

import pytest

from fleech.textfilter import classify_complexity, is_trivial_utterance


def test_short_clean_utterances_are_trivial():
    assert is_trivial_utterance("Okay, das passt.")
    assert is_trivial_utterance("Bis morgen!")
    assert is_trivial_utterance("Ja, machen wir so.")


def test_filler_words_require_llm():
    assert not is_trivial_utterance("Okay äh passt.")
    assert not is_trivial_utterance("Also gut.")
    assert not is_trivial_utterance("Ne, lass mal.")


def test_correction_markers_require_llm():
    assert not is_trivial_utterance("Dienstag nein Freitag.")
    assert not is_trivial_utterance("Warte, anders.")


def test_numbers_require_llm():
    # Zahlen-Selbstkorrekturen ("30 ähm 45") duerfen nie am LLM vorbei.
    assert not is_trivial_utterance("Um 15 Uhr.")


def test_long_utterances_require_llm():
    assert not is_trivial_utterance("Das hier ist ein deutlich laengerer Satz ohne Marker.")


def test_empty_is_not_trivial():
    assert not is_trivial_utterance("")


# -- Dreistufiges Komplexitaets-Routing -------------------------------------------------


def test_classify_trivial():
    assert classify_complexity("Okay, das passt.") == "trivial"
    assert classify_complexity("Bis morgen!") == "trivial"


def test_classify_simple_filler_and_medium_length():
    # Nur Fuellwoerter, keine Zahlen/Korrektur, kurz-mittel → kleines Modell.
    assert classify_complexity("also äh ich wollte nur kurz sagen dass das gut klingt") == "simple"
    assert classify_complexity("ähm ja das machen wir halt so") == "simple"


def test_classify_complex_on_correction():
    assert classify_complexity("treffen wir uns dienstag nein freitag") == "complex"
    assert classify_complexity("warte anders herum lieber doch nicht") == "complex"
    assert classify_complexity("das kostet 200 beziehungsweise 250 euro") == "complex"


def test_classify_complex_on_digits():
    assert classify_complexity("der call ist um 15 uhr") == "complex"


def test_classify_complex_on_length():
    long = " ".join(["wort"] * 30)
    assert classify_complexity(long) == "complex"


def test_classify_empty_is_complex_safe():
    assert classify_complexity("") == "complex"


# -- Persoenliches Woerterbuch ---------------------------------------------------------


def test_spoken_code_tokens_force_complex():
    """Technische Diktate ("print Klammer auf x Klammer zu") sind kurz und
    ziffernfrei — sie waeren sonst "trivial" und liefen ganz ohne Modell durch,
    obwohl dort gerade sorgfaeltige Zeichensetzung noetig ist."""
    from fleech.textfilter import classify_complexity

    assert classify_complexity("print Klammer auf x Klammer zu") == "complex"
    assert classify_complexity("Variable in camelCase benennen") == "complex"
    assert classify_complexity("dann ein Semikolon dahinter") == "complex"


def test_common_words_do_not_force_complex():
    """Gegenprobe: "gleich", "plus", "minus", "Punkt" sind normale deutsche Woerter
    und duerfen Alltagsdiktate NICHT ans grosse Modell schicken (Latenz-Regression)."""
    from fleech.textfilter import classify_complexity

    assert classify_complexity("ich komme gleich vorbei") == "trivial"
    # Laenger als 5 Woerter → "simple"; entscheidend ist, dass NICHT "complex" greift.
    assert classify_complexity("das bringt es auf den Punkt") == "simple"
    assert classify_complexity("das ist ein Plus für uns") == "simple"
    assert classify_complexity("wir treffen uns gleich am Eingang") == "simple"


def test_strip_meta_preamble_narrow():
    """Ankuendigungszeilen entfernen — aber eng gefasst, damit echtes Diktat bleibt."""
    from fleech.textfilter import strip_meta_preamble

    assert strip_meta_preamble(
        "Hier ist der bereinigte Text:\nDer Server ist ausgefallen."
    ) == "Der Server ist ausgefallen."
    # Ohne Folgetext bleibt alles stehen (sonst waere das Ergebnis leer).
    assert strip_meta_preamble("Hier ist der Text:") == "Hier ist der Text:"
    # In derselben Zeile weitergeschrieben → echtes Diktat, nicht anfassen.
    text = "Hier ist der Bericht: alles läuft nach Plan."
    assert strip_meta_preamble(text) == text
    # Andere Satzanfaenge bleiben unberuehrt.
    for keep in ("Gerne!\nDer Text.", "Klar:\nDer Text.", "Der Server ist weg."):
        assert strip_meta_preamble(keep) == keep


def test_added_ratio_null_bei_wortgetreu():
    from fleech.textfilter import added_ratio

    raw = "also ich schicke dir den bericht nachher noch rüber"
    clean = "Ich schicke dir den Bericht nachher noch rüber."
    assert added_ratio(raw, clean) == 0.0


def test_added_ratio_erkennt_synonym_tausch():
    """Realer Fall: „visualisieren" → „visuell darstellen". Die Wortgetreue merkt
    davon NICHTS (alle Rohwoerter ueberleben) — added_ratio schon."""
    from fleech.textfilter import added_ratio, verbatim_ratio

    raw = "ich verstehe es aktuell nur bedingt kannst du mir das vielleicht visualisieren"
    clean = "Ich verstehe es aktuell nur bedingt. Kannst du mir das vielleicht visuell darstellen?"
    assert verbatim_ratio(raw, clean) >= 0.8      # sieht harmlos aus …
    assert added_ratio(raw, clean) > 0.1          # … ist es aber nicht


def test_added_ratio_toleriert_noetige_grammatik():
    """Ein ergaenztes „es" ist Grammatik, keine Ausschmueckung — darf nicht anschlagen."""
    from fleech.textfilter import added_ratio

    raw = "aber ich fände schon gut die irgendwo anzuzeigen"
    clean = "Aber ich fände es schon gut, die irgendwo anzuzeigen."
    assert added_ratio(raw, clean) < 0.22         # unter der Pipeline-Grenze


def test_added_ratio_schlaegt_bei_umbau_an():
    from fleech.textfilter import added_ratio

    raw = "aber ich fände schon gut die irgendwo anzuzeigen"
    clean = "Aber ich fände es schon gut, wenn sie irgendwo angezeigt würde."
    assert added_ratio(raw, clean) > 0.22


def test_added_ratio_leere_ausgabe():
    from fleech.textfilter import added_ratio

    assert added_ratio("irgendein text hier", "") == 0.0


def test_strip_latex_erfasst_abgesetzte_formeln():
    """Realer Fall: Integrale kamen als $$…$$ — die blieben stehen und ihre
    LaTeX-Befehle zaehlten als erfundene Woerter."""
    from fleech.textfilter import strip_latex_blocks

    rest, n = strip_latex_blocks(r"Also gilt $$\int_a^b \frac{1}{x}\,dx$$ am Ende.")
    assert n == 1 and "int" not in rest and rest == "Also gilt am Ende."
    rest, n = strip_latex_blocks(r"Damit \[x^2 + 1\] fertig.")
    assert n == 1 and rest == "Damit fertig."


# -- Gesprochene Zeichen -------------------------------------------------------------


def test_stotter_token_wird_eingedampft():
    """„G-G-G-G-G-…" ist EIN Token — die Wort- und Satzebene des Filters sehen
    dort nur ein einziges Wort und greifen nicht. Real aufgetreten, als Freihand
    zwei Sekunden Mikrofonrauschen verarbeitete; der Unsinn landete im Textfeld.
    """
    from fleech.textfilter import collapse_trailing_repetitions

    murks = "-".join("G" * 60)
    assert collapse_trailing_repetitions(murks) == "G"
    assert collapse_trailing_repetitions("la" * 30) == "la"


@pytest.mark.parametrize("wort", [
    "Mississippi", "Bonbon", "Hawaii", "Kaffeeersatz", "Schifffahrt",
    "Donaudampfschifffahrt", "Tomatensalat", "Bananenbrot",
])


def test_echte_woerter_bleiben_unangetastet(wort):
    """Die Bedingung ist streng gehalten: lang UND fast vollstaendig aus
    derselben kurzen Gruppe. Sonst wuerde sie echte Woerter zerlegen."""
    from fleech.textfilter import collapse_trailing_repetitions

    assert collapse_trailing_repetitions(wort) == wort


def test_normaler_satz_bleibt_ganz():
    from fleech.textfilter import collapse_trailing_repetitions

    satz = "Das ist ein ganz normaler Satz mit Bonbon und Mississippi darin."
    assert collapse_trailing_repetitions(satz) == satz
