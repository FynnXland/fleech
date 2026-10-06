"""Persoenliches Woerterbuch: Parsen, Priming, Ersetzung, Fehlschreib-Vorschlaege."""


def test_parse_dictionary_terms_and_rules():
    from fleech.dictionary import parse_dictionary

    terms, rules = parse_dictionary([
        "Fleech", "  Kimono  ", "", "# Kommentar",
        "github => GitHub", "Cosinus=>Kosinus", "kaputt =>", "Fleech",
    ])
    assert terms == ["Fleech", "Kimono", "GitHub", "Kosinus"]  # dedupliziert, rechts der Regel
    assert rules == [("github", "GitHub"), ("Cosinus", "Kosinus")]


def test_vocab_initial_prompt_format():
    from fleech.dictionary import parse_dictionary, vocab_initial_prompt

    terms, _ = parse_dictionary(["Fleech", "Ollama"])
    assert vocab_initial_prompt(terms) == "Vokabular: Fleech, Ollama."
    assert vocab_initial_prompt([]) == ""


def test_apply_dictionary_word_boundaries_and_case():
    from fleech.dictionary import apply_dictionary

    rules = [("github", "GitHub"), ("Cosinus", "Kosinus")]
    out = apply_dictionary("Der GITHUB-PR nutzt den cosinus, nicht den Cosinussatz.", rules)
    assert "GitHub-PR" in out
    assert "den Kosinus," in out
    assert "Cosinussatz" in out  # Wortgrenze: Teilwoerter bleiben unangetastet


def test_apply_dictionary_broken_rule_is_ignored():
    from fleech.dictionary import apply_dictionary

    # kaputtes Muster darf nie raisen (Nutzereingabe)
    assert apply_dictionary("text", [("(", "Klammer")]) in ("text", "Klammer")


# -- Fehlschreibungs-Erkennung (selbstlernendes Woerterbuch) ------------------------------


def test_levenshtein_basics():
    from fleech.dictionary import levenshtein

    assert levenshtein("kimono", "kimono") == 0
    assert levenshtein("kimano", "kimono") == 1
    assert levenshtein("kimena", "kimono") == 2
    assert levenshtein("hallo", "kimono", max_dist=2) == 3  # Abbruch: max+1


def test_find_dictionary_candidates_near_matches():
    from fleech.dictionary import find_dictionary_candidates

    hits = find_dictionary_candidates(
        "Das Kimano hat funktioniert, GitHub auch.", ["Kimono", "GitHub"]
    )
    assert hits == [("Kimano", "Kimono")]      # exakte Treffer werden ignoriert


def test_find_dictionary_candidates_respects_ignores_and_short_words():
    from fleech.dictionary import find_dictionary_candidates

    # Abgelehntes Paar → nie wieder vorschlagen.
    assert find_dictionary_candidates(
        "Das Kimano wieder.", ["Kimono"], ignores=["kimano => kimono"]
    ) == []
    # Kurze Woerter (<4) erzeugen keine Kandidaten (Zufallsnaehe).
    assert find_dictionary_candidates("Er ist da.", ["Uta"]) == []


def test_priming_prefers_actually_used_terms():
    """Ueber dem 60er-Limit wurde bisher stumpf nach Dateireihenfolge abgeschnitten —
    Power-User verloren Priming fuer alles am Listenende, ohne es zu merken."""
    from fleech.dictionary import primed_terms, vocab_initial_prompt

    terms = [f"Begriff{i:03d}" for i in range(80)]
    # Ohne Nutzungsdaten: Dateireihenfolge, die letzten 20 fallen raus.
    assert primed_terms(terms)[:2] == ["Begriff000", "Begriff001"]
    assert "Begriff079" not in primed_terms(terms)
    # Mit Nutzung: der viel genutzte Begriff vom Listenende rueckt nach vorn.
    usage = {"begriff079": 12, "begriff078": 5}
    picked = primed_terms(terms, usage)
    assert picked[0] == "Begriff079" and picked[1] == "Begriff078"
    assert len(picked) == 60
    # Gleichstand aendert die Reihenfolge nicht (stabile Sortierung).
    assert primed_terms(terms, {}) == primed_terms(terms)
    assert "Begriff079" in vocab_initial_prompt(terms, usage)


def test_find_terms_in_text():
    from fleech.dictionary import find_terms_in_text

    terms = ["Fleech", "PySide", "Kimono"]
    found = find_terms_in_text("Wir haben fleech mit PySide gebaut.", terms)
    assert found == ["Fleech", "PySide"]          # case-insensitiv, Kimono fehlt
    # Teilwoerter zaehlen nicht (Wortgrenzen).
    assert find_terms_in_text("PySide6Extra", ["PySide6Extra"]) == ["PySide6Extra"]
    assert find_terms_in_text("Fleechomat", ["Fleech"]) == []
    # Kaputte Eintraege duerfen nie stoeren.
    assert find_terms_in_text("egal", ["", "   "]) == []


def test_gesprochene_zeichen_kleben_am_folgewort():
    """So wird es gesprochen: Pfade, Handles, Kanäle."""
    from fleech.dictionary import spoken_symbols

    assert spoken_symbols("einmal Slash Hunter Help") == "einmal /Hunter Help"
    assert spoken_symbols("Schreib Hashtag Fleech dazu") == "Schreib #Fleech dazu"
    # chr(92) = Backslash — als Literal waere die Zeile beim Bearbeiten zu leicht
    # in ein echtes Zeilenumbruch-Escape zu verwandeln (genau das ist passiert).
    assert (spoken_symbols("Backslash n macht einen Umbruch")
            == chr(92) + "n macht einen Umbruch")


def test_zeichenwort_am_satzende_bleibt_wort():
    """Ohne Folgewort ist „Slash" vermutlich wirklich gemeint."""
    from fleech.dictionary import spoken_symbols

    assert spoken_symbols("Setz da einen Slash.") == "Setz da einen Slash."


def test_gewoehnliche_deutsche_zeichenwoerter_bleiben_text():
    """Befund A-9: „Raute", „Unterstrich" und „Schrägstrich" sind ganz normale
    deutsche Wörter. An 1399 echten Diktaten waren beide gemessenen Fehltreffer
    genau von dieser Art (id 47: „Also Schrägstrich und dann halt" → „Also /und
    dann halt")."""
    from fleech.dictionary import spoken_symbols

    for satz in ("Zeichne eine Raute darunter",
                 "Die Raute ist ein Viereck",
                 "Ein Unterstrich im Namen",
                 "Also Schrägstrich und dann halt"):
        assert spoken_symbols(satz) == satz


def test_zeichen_vor_gewoehnlichem_wort_behaelt_das_leerzeichen():
    """Befund A-9, zweite Hälfte: id 1141 „Kontext oder Hashtag oder Slash" wurde zu
    „Kontext oder #oder /oder" — das verschluckte Leerzeichen machte aus zwei Wörtern
    eines. An einen Namen (Großbuchstabe) oder ein einzelnes Zeichen klebt es weiter."""
    from fleech.dictionary import spoken_symbols

    assert spoken_symbols("Kontext oder Hashtag oder Slash") == "Kontext oder # oder Slash"
    assert spoken_symbols("die Befehle alle also Slash Hunter") == \
        "die Befehle alle also /Hunter"


def test_minus_und_plus_bleiben_text():
    """Gewöhnliche deutsche Wörter — eine Ersetzung macht hier mehr kaputt als sie
    hilft. Rechnende Minuszeichen entstehen ohnehin im Formel-Parser."""
    from fleech.dictionary import spoken_symbols

    satz = "Der Preis ist minus zwanzig Grad, mal sehen, plus Versand."
    assert spoken_symbols(satz) == satz


def test_zeichenwort_nur_als_ganzes_wort():
    from fleech.dictionary import spoken_symbols

    assert spoken_symbols("Slasher Filme mag ich nicht") == "Slasher Filme mag ich nicht"


def test_leerer_text_bleibt_leer():
    from fleech.dictionary import spoken_symbols

    assert spoken_symbols("") == ""
    assert spoken_symbols(None) is None
