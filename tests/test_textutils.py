import pytest

from fleech.textutils import (
    classify_complexity, is_trivial_utterance, strip_wrapping_quotes,
)


# -- Anfuehrungszeichen-Strip (realer Bug: Modell wickelt Antwort in „…") --------------


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


def test_parse_dictionary_terms_and_rules():
    from fleech.textutils import parse_dictionary

    terms, rules = parse_dictionary([
        "Fleech", "  Kimono  ", "", "# Kommentar",
        "github => GitHub", "Cosinus=>Kosinus", "kaputt =>", "Fleech",
    ])
    assert terms == ["Fleech", "Kimono", "GitHub", "Kosinus"]  # dedupliziert, rechts der Regel
    assert rules == [("github", "GitHub"), ("Cosinus", "Kosinus")]


def test_vocab_initial_prompt_format():
    from fleech.textutils import parse_dictionary, vocab_initial_prompt

    terms, _ = parse_dictionary(["Fleech", "Ollama"])
    assert vocab_initial_prompt(terms) == "Vokabular: Fleech, Ollama."
    assert vocab_initial_prompt([]) == ""


def test_apply_dictionary_word_boundaries_and_case():
    from fleech.textutils import apply_dictionary

    rules = [("github", "GitHub"), ("Cosinus", "Kosinus")]
    out = apply_dictionary("Der GITHUB-PR nutzt den cosinus, nicht den Cosinussatz.", rules)
    assert "GitHub-PR" in out
    assert "den Kosinus," in out
    assert "Cosinussatz" in out  # Wortgrenze: Teilwoerter bleiben unangetastet


def test_apply_dictionary_broken_rule_is_ignored():
    from fleech.textutils import apply_dictionary

    # kaputtes Muster darf nie raisen (Nutzereingabe)
    assert apply_dictionary("text", [("(", "Klammer")]) in ("text", "Klammer")


# -- Fehlschreibungs-Erkennung (selbstlernendes Woerterbuch) ------------------------------


def test_levenshtein_basics():
    from fleech.textutils import levenshtein

    assert levenshtein("kimono", "kimono") == 0
    assert levenshtein("kimano", "kimono") == 1
    assert levenshtein("kimena", "kimono") == 2
    assert levenshtein("hallo", "kimono", max_dist=2) == 3  # Abbruch: max+1


def test_find_dictionary_candidates_near_matches():
    from fleech.textutils import find_dictionary_candidates

    hits = find_dictionary_candidates(
        "Das Kimano hat funktioniert, GitHub auch.", ["Kimono", "GitHub"]
    )
    assert hits == [("Kimano", "Kimono")]      # exakte Treffer werden ignoriert


def test_find_dictionary_candidates_respects_ignores_and_short_words():
    from fleech.textutils import find_dictionary_candidates

    # Abgelehntes Paar → nie wieder vorschlagen.
    assert find_dictionary_candidates(
        "Das Kimano wieder.", ["Kimono"], ignores=["kimano => kimono"]
    ) == []
    # Kurze Woerter (<4) erzeugen keine Kandidaten (Zufallsnaehe).
    assert find_dictionary_candidates("Er ist da.", ["Uta"]) == []


def test_spoken_code_tokens_force_complex():
    """Technische Diktate ("print Klammer auf x Klammer zu") sind kurz und
    ziffernfrei — sie waeren sonst "trivial" und liefen ganz ohne Modell durch,
    obwohl dort gerade sorgfaeltige Zeichensetzung noetig ist."""
    from fleech.textutils import classify_complexity

    assert classify_complexity("print Klammer auf x Klammer zu") == "complex"
    assert classify_complexity("Variable in camelCase benennen") == "complex"
    assert classify_complexity("dann ein Semikolon dahinter") == "complex"


def test_common_words_do_not_force_complex():
    """Gegenprobe: "gleich", "plus", "minus", "Punkt" sind normale deutsche Woerter
    und duerfen Alltagsdiktate NICHT ans grosse Modell schicken (Latenz-Regression)."""
    from fleech.textutils import classify_complexity

    assert classify_complexity("ich komme gleich vorbei") == "trivial"
    # Laenger als 5 Woerter → "simple"; entscheidend ist, dass NICHT "complex" greift.
    assert classify_complexity("das bringt es auf den Punkt") == "simple"
    assert classify_complexity("das ist ein Plus für uns") == "simple"
    assert classify_complexity("wir treffen uns gleich am Eingang") == "simple"


def test_priming_prefers_actually_used_terms():
    """Ueber dem 60er-Limit wurde bisher stumpf nach Dateireihenfolge abgeschnitten —
    Power-User verloren Priming fuer alles am Listenende, ohne es zu merken."""
    from fleech.textutils import primed_terms, vocab_initial_prompt

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
    from fleech.textutils import find_terms_in_text

    terms = ["Fleech", "PySide", "Kimono"]
    found = find_terms_in_text("Wir haben fleech mit PySide gebaut.", terms)
    assert found == ["Fleech", "PySide"]          # case-insensitiv, Kimono fehlt
    # Teilwoerter zaehlen nicht (Wortgrenzen).
    assert find_terms_in_text("PySide6Extra", ["PySide6Extra"]) == ["PySide6Extra"]
    assert find_terms_in_text("Fleechomat", ["Fleech"]) == []
    # Kaputte Eintraege duerfen nie stoeren.
    assert find_terms_in_text("egal", ["", "   "]) == []


def test_strip_meta_preamble_narrow():
    """Ankuendigungszeilen entfernen — aber eng gefasst, damit echtes Diktat bleibt."""
    from fleech.textutils import strip_meta_preamble

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


def test_session_kind_detection(monkeypatch):
    """Wayland soll benannt werden koennen, statt Funktionen still ausfallen zu lassen."""
    import fleech.platformpaths as pp

    monkeypatch.setattr(pp.sys, "platform", "linux")
    monkeypatch.setattr(pp.os, "environ", {"WAYLAND_DISPLAY": "wayland-0"})
    assert pp.session_kind() == "wayland"
    monkeypatch.setattr(pp.os, "environ", {"XDG_SESSION_TYPE": "Wayland"})
    assert pp.session_kind() == "wayland"
    monkeypatch.setattr(pp.os, "environ", {"DISPLAY": ":0"})
    assert pp.session_kind() == "x11"
    monkeypatch.setattr(pp.os, "environ", {})
    assert pp.session_kind() == "unknown"
    monkeypatch.setattr(pp.sys, "platform", "win32")
    assert pp.session_kind() == "windows"


# -- Aufblaeh-Erkennung (added_ratio, v2.1.0) --------------------------------------

def test_added_ratio_null_bei_wortgetreu():
    from fleech.textutils import added_ratio

    raw = "also ich schicke dir den bericht nachher noch rüber"
    clean = "Ich schicke dir den Bericht nachher noch rüber."
    assert added_ratio(raw, clean) == 0.0


def test_added_ratio_erkennt_synonym_tausch():
    """Realer Fall: „visualisieren" → „visuell darstellen". Die Wortgetreue merkt
    davon NICHTS (alle Rohwoerter ueberleben) — added_ratio schon."""
    from fleech.textutils import added_ratio, verbatim_ratio

    raw = "ich verstehe es aktuell nur bedingt kannst du mir das vielleicht visualisieren"
    clean = "Ich verstehe es aktuell nur bedingt. Kannst du mir das vielleicht visuell darstellen?"
    assert verbatim_ratio(raw, clean) >= 0.8      # sieht harmlos aus …
    assert added_ratio(raw, clean) > 0.1          # … ist es aber nicht


def test_added_ratio_toleriert_noetige_grammatik():
    """Ein ergaenztes „es" ist Grammatik, keine Ausschmueckung — darf nicht anschlagen."""
    from fleech.textutils import added_ratio

    raw = "aber ich fände schon gut die irgendwo anzuzeigen"
    clean = "Aber ich fände es schon gut, die irgendwo anzuzeigen."
    assert added_ratio(raw, clean) < 0.22         # unter der Pipeline-Grenze


def test_added_ratio_schlaegt_bei_umbau_an():
    from fleech.textutils import added_ratio

    raw = "aber ich fände schon gut die irgendwo anzuzeigen"
    clean = "Aber ich fände es schon gut, wenn sie irgendwo angezeigt würde."
    assert added_ratio(raw, clean) > 0.22


def test_added_ratio_leere_ausgabe():
    from fleech.textutils import added_ratio

    assert added_ratio("irgendein text hier", "") == 0.0


def test_strip_latex_erfasst_abgesetzte_formeln():
    """Realer Fall: Integrale kamen als $$…$$ — die blieben stehen und ihre
    LaTeX-Befehle zaehlten als erfundene Woerter."""
    from fleech.textutils import strip_latex_blocks

    rest, n = strip_latex_blocks(r"Also gilt $$\int_a^b \frac{1}{x}\,dx$$ am Ende.")
    assert n == 1 and "int" not in rest and rest == "Also gilt am Ende."
    rest, n = strip_latex_blocks(r"Damit \[x^2 + 1\] fertig.")
    assert n == 1 and rest == "Damit fertig."


# -- Gesprochene Zeichen -------------------------------------------------------------

def test_gesprochene_zeichen_kleben_am_folgewort():
    """So wird es gesprochen: Pfade, Handles, Kanäle."""
    from fleech.textutils import spoken_symbols

    assert spoken_symbols("einmal Slash Hunter Help") == "einmal /Hunter Help"
    assert spoken_symbols("Schreib Hashtag Fleech dazu") == "Schreib #Fleech dazu"
    # chr(92) = Backslash — als Literal waere die Zeile beim Bearbeiten zu leicht
    # in ein echtes Zeilenumbruch-Escape zu verwandeln (genau das ist passiert).
    assert (spoken_symbols("Backslash n macht einen Umbruch")
            == chr(92) + "n macht einen Umbruch")


def test_zeichenwort_am_satzende_bleibt_wort():
    """Ohne Folgewort ist „Slash" vermutlich wirklich gemeint."""
    from fleech.textutils import spoken_symbols

    assert spoken_symbols("Setz da einen Slash.") == "Setz da einen Slash."


def test_minus_und_plus_bleiben_text():
    """Gewöhnliche deutsche Wörter — eine Ersetzung macht hier mehr kaputt als sie
    hilft. Rechnende Minuszeichen entstehen ohnehin im Formel-Parser."""
    from fleech.textutils import spoken_symbols

    satz = "Der Preis ist minus zwanzig Grad, mal sehen, plus Versand."
    assert spoken_symbols(satz) == satz


def test_zeichenwort_nur_als_ganzes_wort():
    from fleech.textutils import spoken_symbols

    assert spoken_symbols("Slasher Filme mag ich nicht") == "Slasher Filme mag ich nicht"


def test_leerer_text_bleibt_leer():
    from fleech.textutils import spoken_symbols

    assert spoken_symbols("") == ""
    assert spoken_symbols(None) is None


def test_stotter_token_wird_eingedampft():
    """„G-G-G-G-G-…" ist EIN Token — die Wort- und Satzebene des Filters sehen
    dort nur ein einziges Wort und greifen nicht. Real aufgetreten, als Freihand
    zwei Sekunden Mikrofonrauschen verarbeitete; der Unsinn landete im Textfeld.
    """
    from fleech.textutils import collapse_trailing_repetitions

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
    from fleech.textutils import collapse_trailing_repetitions

    assert collapse_trailing_repetitions(wort) == wort


def test_normaler_satz_bleibt_ganz():
    from fleech.textutils import collapse_trailing_repetitions

    satz = "Das ist ein ganz normaler Satz mit Bonbon und Mississippi darin."
    assert collapse_trailing_repetitions(satz) == satz
