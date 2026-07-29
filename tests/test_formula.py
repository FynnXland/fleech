"""Deterministischer Formel-Konverter.

Leitgedanke seit v3.0.0: Gesprochene Mathematik hat keine Klammern, also ist ein
Teil der Faelle prinzipiell mehrdeutig. Statt zu schweigen uebersetzt der Parser
nach den ueblichen Vorrangregeln — und MELDET, dass er geraten hat, damit die
Oberflaeche die Stelle hervorheben kann. Wer Klammern mitspricht, bekommt genau
das und keinen Hinweis.
"""

from fleech.formula import (apply_formulas, find_formulas, restore_formulas,
                            speech_to_latex)


def test_eindeutige_ausdruecke_ohne_ratehinweis():
    for spoken, expected in (
        ("x hoch zwei plus eins", "x^{2} + 1"),
        ("lambda quadrat minus eins", r"\lambda^{2} - 1"),
        ("wurzel aus zwei", r"\sqrt{2}"),
        ("x quadrat durch zwei", r"\frac{x^{2}}{2}"),
    ):
        latex, guessed = speech_to_latex(spoken)
        assert latex == expected, spoken
        assert guessed == [], f"unnoetig als geraten markiert: {spoken}"


def test_funktionen():
    latex, guessed = speech_to_latex("sinus von x plus kosinus von x")
    assert latex == r"\sin(x) + \cos(x)"
    assert guessed == []


def test_bruch_bindet_nur_den_letzten_operanden():
    """„a plus b durch c" heisst nach Vorrangregeln a + b/c — NICHT (a+b)/c."""
    latex, _guessed = speech_to_latex("a plus b durch c")
    assert latex == r"a + \frac{b}{c}"


def test_mehrdeutige_wurzel_wird_geraten_und_gemeldet():
    latex, guessed = speech_to_latex("wurzel aus x quadrat plus c")
    assert latex == r"\sqrt{x^{2}} + c"          # Vorrangregel: Wurzel bindet eng
    assert guessed and "Wurzel" in guessed[0]


def test_mehrdeutiger_exponent_wird_geraten_und_gemeldet():
    """„e hoch lambda x" — im Diktat fast immer e^{lambda x}."""
    latex, guessed = speech_to_latex("e hoch lambda x")
    assert latex == r"e^{\lambda x}"
    assert guessed and "Exponent" in guessed[0]


def test_gesprochene_klammern_loesen_die_mehrdeutigkeit():
    latex, guessed = speech_to_latex(
        "wurzel aus klammer auf x quadrat plus c klammer zu")
    assert latex == r"\sqrt{(x^{2} + c)}"
    assert guessed == []                          # eindeutig → kein Hinweis


def test_normaler_text_wird_nie_angefasst():
    for raw in ("wir treffen uns um zwei", "ich glaube das passt so", ""):
        assert speech_to_latex(raw)[0] is None, raw


def test_fliesstext_nur_die_formel_ersetzen():
    text, formulas, uncertain = apply_formulas(
        "dann ist x hoch zwei plus eins das ergebnis")
    assert formulas == ["x^{2} + 1"]
    assert uncertain == [False]
    assert "[[M1]]" in text and "dann ist" in text and "das ergebnis" in text
    assert restore_formulas(text, formulas) == "dann ist $x^{2} + 1$ das ergebnis"


def test_unsicherheit_wird_pro_formel_gemeldet():
    """Die Vorschau braucht je Formel die Information „geraten ja/nein"."""
    _text, formulas, uncertain = apply_formulas(
        "also wurzel aus x quadrat plus c ist das ergebnis")
    assert formulas and uncertain == [True]


def test_ohne_formel_bleibt_alles_gleich():
    raw = "ich schicke dir das nachher noch rueber"
    assert apply_formulas(raw) == (raw, [], [])


def test_alltagszahlen_werden_nicht_zu_formeln():
    """Der haeufigste Fehlalarm-Kandidat: Zahlen im Fliesstext."""
    for raw in ("wir treffen uns um zwei und bringen drei sachen mit",
                "das dauert noch zehn minuten schaetze ich",
                "punkt eins ist erledigt punkt zwei noch nicht"):
        assert apply_formulas(raw)[1] == [], raw


def test_find_formulas_liefert_positionen():
    spots = find_formulas("also x hoch zwei plus eins ergibt das")
    assert spots
    start, end, latex, guessed = spots[0]
    assert latex == "x^{2} + 1"
    assert "x hoch zwei plus eins" in "also x hoch zwei plus eins ergibt das"[start:end]
    assert guessed == []


# -- Fehler aus dem Live-Test (v3.0.1) --------------------------------------------

def test_whisper_kommas_zerreissen_die_formel_nicht():
    """Whisper transkribierte „Wurzel aus, Klammer auf, x² plus c, Klammer zu."
    Am Komma brach die Erkennung ab — es blieb nur „x + c", den Rest machte das
    Sprachmodell, und die Dollarzeichen landeten ineinander."""
    text, formulas, uncertain = apply_formulas(
        "Wurzel aus, Klammer auf, x plus c, Klammer zu")
    assert formulas == [r"\sqrt{(x + c)}"], formulas
    assert uncertain == [False]          # mit Klammern ist nichts geraten
    assert "[[M1]]" in text


def test_keine_verschachtelten_dollarzeichen():
    r"""Steht der Platzhalter schon in einem Mathe-Bereich (weil das Sprachmodell
    einen Teil selbst als Formel gesetzt hat), darf restore KEINE zweiten
    Dollarzeichen setzen — sonst entsteht `$ \sqrt{$x + c$} $`."""
    out = restore_formulas(r"$ \sqrt{[[M1]]} $", ["x + c"])
    assert out == r"$ \sqrt{x + c} $"
    assert "$x" not in out

    # Ausserhalb eines Mathe-Bereichs wird weiterhin gerahmt.
    assert restore_formulas("also [[M1]] fertig", ["x + c"]) == "also $x + c$ fertig"


# -- Symbole aus der Erkennung + lesbare Anzeige (v3.0.3) -------------------------

def test_whisper_symbole_gehen_nicht_verloren():
    r"""Whisper schreibt „x hoch zwei" oft schon als „x²". Der Tokenizer kannte das
    Zeichen nicht und verschluckte es STILL — aus „Wurzel aus x²-1" wurde
    `\sqrt{x}1`, ohne Warnung. Real vom Nutzer gemeldet."""
    _text, formulas, uncertain = apply_formulas("Und die Wurzel aus x²-1.")
    assert formulas == [r"\sqrt{x^{2}} - 1"], formulas
    assert uncertain == [True]           # ohne Klammern bleibt die Lesart offen


def test_hochgestellte_ziffer_wird_zum_exponenten():
    _text, formulas, _u = apply_formulas("Okay, also x² plus 1 minus c.")
    assert formulas == ["x^{2} + 1 - c"]


def test_readable_macht_latex_lesbar():
    from fleech.formula import readable

    assert readable(r"\sqrt{x} + c") == "√x + c"
    assert readable(r"\sqrt{x} - c + \frac{c}{2}") == "√x - c + c/2"
    assert readable("x^{2} + 1 - c") == "x² + 1 - c"
    assert readable(r"\sqrt{(x + c)}") == "√(x + c)"
    assert "\\" not in readable(r"\lambda^{2} \cdot \pi")
