"""Text-Bausteine: Erkennung, Marker-Runde, Priming."""

from fleech.snippets import (
    expand_snippets, markers_survived, mentions_keyword, parse_snippets,
    restore_snippets, snippet_initial_prompt, snippet_marker,
)

SNIPPETS = parse_snippets([
    "Signatur => Viele Grüße\\nAlex Muster",
    "Absage => Leider muss ich absagen.",
    "Absage Termin => Der Termin entfällt leider.",
    "# Kommentar wird ignoriert",
    "kaputte Zeile ohne Pfeil",
    "   => nur Text, kein Kürzel",
])


def test_parse_liest_nur_valide_zeilen():
    keys = [k for k, _ in SNIPPETS]
    assert set(keys) == {"Signatur", "Absage", "Absage Termin"}


def test_parse_wandelt_escapte_zeilenumbrueche():
    text = dict(SNIPPETS)["Signatur"]
    assert text == "Viele Grüße\nAlex Muster"


def test_laengeres_kuerzel_gewinnt():
    """„Absage Termin" darf nicht als „Absage" + Resttext „Termin" zerfallen."""
    text, texts = expand_snippets("Baustein Absage Termin", SNIPPETS)
    assert texts == ["Der Termin entfällt leider."]
    assert text == snippet_marker(0)


def test_duplikat_kuerzel_wird_ignoriert():
    parsed = parse_snippets(["A => erste", "a => zweite"])
    assert parsed == [("A", "erste")]


def test_baustein_mitten_im_text():
    raw = "Vielen Dank für Ihre Nachricht. Baustein Signatur"
    text, texts = expand_snippets(raw, SNIPPETS)
    assert texts == ["Viele Grüße\nAlex Muster"]
    assert text == f"Vielen Dank für Ihre Nachricht. {snippet_marker(0)}"
    assert restore_snippets(text, texts) == (
        "Vielen Dank für Ihre Nachricht. Viele Grüße\nAlex Muster"
    )


def test_mehrere_bausteine_bekommen_eigene_marker():
    text, texts = expand_snippets("Baustein Absage und Baustein Signatur", SNIPPETS)
    assert len(texts) == 2
    assert snippet_marker(0) in text and snippet_marker(1) in text


def test_asr_toleranz_bei_komma_und_bindestrich():
    """Whisper setzt zwischen Signalwort und Kürzel gern Satzzeichen."""
    for raw in ("Baustein, Signatur", "Baustein: Signatur", "Baustein-Signatur"):
        _text, texts = expand_snippets(raw, SNIPPETS)
        assert texts, f"nicht erkannt: {raw!r}"


def test_gross_kleinschreibung_egal():
    _text, texts = expand_snippets("baustein signatur", SNIPPETS)
    assert texts == ["Viele Grüße\nAlex Muster"]


def test_ohne_treffer_bleibt_text_unveraendert():
    raw = "ein ganz normaler Satz ohne Kürzel"
    text, texts = expand_snippets(raw, SNIPPETS)
    assert (text, texts) == (raw, [])


def test_signalwort_allein_loest_nichts_aus():
    """„Baustein" als normales Wort darf nichts einfügen."""
    text, texts = expand_snippets("der Baustein ist geliefert worden", SNIPPETS)
    assert texts == []
    assert text == "der Baustein ist geliefert worden"


def test_eigenes_signalwort():
    _text, texts = expand_snippets("Vorlage Signatur", SNIPPETS, keyword="Vorlage")
    assert texts == ["Viele Grüße\nAlex Muster"]
    _text, none = expand_snippets("Baustein Signatur", SNIPPETS, keyword="Vorlage")
    assert none == []


def test_marker_ueberlebens_check():
    before = f"Text {snippet_marker(0)} mehr"
    assert markers_survived(before, f"Text {snippet_marker(0)} mehr.", 1)
    assert not markers_survived(before, "Text mehr.", 1)


def test_priming_nennt_signalwort_mit_kuerzel():
    prompt = snippet_initial_prompt(SNIPPETS)
    assert "Baustein Signatur" in prompt
    assert snippet_initial_prompt([]) == ""


def test_mentions_keyword():
    assert mentions_keyword("gleich Baustein Signatr einfügen")
    assert not mentions_keyword("nichts davon hier")


def test_doppeltes_satzzeichen_an_der_naht():
    """Das Modell hängt hinter den Marker gern einen Punkt — endet der Baustein
    selbst auf einem Satzzeichen, gäbe das „absagen..“ (live beobachtet)."""
    texts = ["Leider muss ich absagen."]
    assert restore_snippets(f"Zu Ihrer Anfrage: {snippet_marker(0)}.", texts) == (
        "Zu Ihrer Anfrage: Leider muss ich absagen."
    )
    # Endet der Baustein NICHT auf Satzzeichen, bleibt das Zeichen des Modells stehen.
    assert restore_snippets(f"Gruß {snippet_marker(0)}.", ["Alex"]) == "Gruß Alex."


def test_naht_kosmetik_frisst_keinen_folgetext():
    texts = ["Leider muss ich absagen."]
    out = restore_snippets(f"{snippet_marker(0)}, aber danke.", texts)
    assert out == "Leider muss ich absagen. aber danke."
