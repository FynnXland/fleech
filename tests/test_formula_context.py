"""Formel-Erkennung darf normalen Text nicht anfassen.

Alle Faelle unter „aus dem echten Log" sind so eingefuegt worden — der Bindestrich
in zusammengesetzten Woertern lieferte das Operator-Token, das aus zwei harmlosen
Zeichen eine „Formel" machte. Diese Tests halten das fest.
"""

import pytest

from fleech.formula import apply_formulas, find_formulas


def formeln(text: str) -> list:
    return [f[2] for f in find_formulas(text)]


# -- Aus dem echten Log: so kam es beim Nutzer an ------------------------------------

@pytest.mark.parametrize("text", [
    # „Combat$-\log -$Dummy-System"
    "Dann widme dich dem ausgeklügelten Combat-Log-Dummy-System.",
    # „$3D -$Model"
    "kannst du das 3D-Model von dem Hierarchiehammer analysieren",
    # „$121 -$Jar"
    "Warum kann ich die 1.21-Jar von Paper nirgends downloaden?",
    # „schl$-a -$gen"
    "es sei denn, man kann damit ja nicht mehr schl-a-gen?",
    # weitere Bindestrich-Kompositа, die genauso getroffen haetten
    "Das E-Mail-Postfach und der 4K-Monitor sind fertig.",
    "Bitte das Log-Level auf Debug-2 stellen.",
])
def test_bindestrich_woerter_sind_keine_formeln(text):
    assert formeln(text) == []


def test_log_allein_wird_nicht_zum_logarithmus():
    """„Log" ist im Alltag ein Protokoll, kein Logarithmus."""
    assert formeln("Schau mal ins Log rein.") == []
    assert formeln("Das Combat-Log zeigt den Schaden.") == []


# -- Echte Formeln muessen weiterhin erkannt werden ----------------------------------

@pytest.mark.parametrize("text,erwartet", [
    ("x hoch zwei plus drei gleich zehn", "x^{2} + 3 = 10"),
    ("Wurzel aus x hoch zwei plus eins", r"\sqrt{x^{2}} + 1"),
])
def test_echte_formeln_bleiben(text, erwartet):
    assert formeln(text) == [erwartet]


def test_formel_mitten_im_fliesstext_bleibt():
    """Der Normalfall des Nutzers: ein Satz Prosa mit einer Formel darin. Eine
    Einordnung des GANZEN Diktats haette genau die verworfen."""
    text = ("Und zwar eine Matrix, von der die Determinante t + 2 zum Quadrat, "
            "mal (t - 1) ist.")
    assert formeln(text) == ["t + 2", "(t - 1)"]


# -- Die Regel dahinter ---------------------------------------------------------------

def test_minus_allein_traegt_keine_formel():
    """Zwei Operanden mit einem Strich dazwischen sind noch keine Mathematik —
    sonst wird jede Aufzaehlung mit Bindestrich zur Formel."""
    assert formeln("Seite 3 - 4 ansehen") == []


def test_minus_mit_echtem_signal_zaehlt():
    """Kommt ein zweites, eindeutiges Signal dazu, ist es wieder Mathematik."""
    assert formeln("x minus drei gleich vier") == ["x - 3 = 4"]


def test_getrennt_stehender_strich_bleibt_operator():
    """Ein Strich MIT Leerzeichen ist ein Minus — nur der Wort-Bindestrich nicht."""
    assert formeln("a + b - c gleich null") == ["a + b - c = 0"]


def test_apply_formulas_laesst_normalen_text_unveraendert():
    text = "Das 3D-Model im Combat-Log-Dummy-System ist fertig."
    ergebnis, gefunden, _ = apply_formulas(text)
    assert ergebnis == text
    assert gefunden == []


def test_nacktes_minus_braucht_umfang():
    """Am echten Verlauf kalibriert: „Seite 3 - 4" ist keine Rechnung, die
    Zeilenumformung „Z2 - 3Z1" schon. Unterschieden wird über die Zahl der
    Operanden, nicht über den Satzinhalt — den sieht der Parser nicht."""
    assert formeln("also Z2 - 3Z1 rechnen") == ["Z2 - 3Z1"]
    assert formeln("Seite 3 - 4 ansehen") == []
    assert formeln("das ist n - 1 mal") == []
