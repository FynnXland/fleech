"""Füllwörter verschwinden ohne Sprachmodell — und nur die Füllwörter.

Hintergrund in `fleech/vorbereinigung.py`: Die Prompt-Regel entfernte von 564
Füllwörtern 14. Diese Regel traf im Verlauf alle 751 und kein echtes Wort.
"""

import pytest

from fleech.vorbereinigung import entferne_fuellwoerter


@pytest.mark.parametrize("roh, erwartet", [
    ("Ähm, ich wollte sagen, äh, dass das geht.", "Ich wollte sagen, dass das geht."),
    ("Das ist, äh, gut.", "Das ist gut."),
    ("Ich glaube, ähm, dass es klappt.", "Ich glaube, dass es klappt."),
    ("Und, ähm, wenn das so ist.", "Und wenn das so ist."),
    ("Wir müssen äh das machen", "Wir müssen das machen"),
    ("Das ist gut. Ähm. Dann los.", "Das ist gut. Dann los."),
    ("Und dann, ähm.", "Und dann."),
    ("Ähhh, also gut.", "Also gut."),
    ("Öhm, ja.", "Ja."),
])
def test_fuellwoerter_verschwinden_samt_kommas(roh, erwartet):
    text, anzahl = entferne_fuellwoerter(roh)
    assert text == erwartet
    assert anzahl >= 1


@pytest.mark.parametrize("roh", [
    # Wörter mit „äh/öh" im Inneren — im Verlauf 33× ähnlich, 30× auswählen, …
    "Das ist ähnlich, aber ungefähr während der Fähigkeit höher.",
    "Bitte auswählen und erhöhen.",
    # Bewusst NICHT entfernt, mit Beleg aus dem Verlauf:
    "Das sieht der Spieler eh nicht.",       # eh = ohnehin
    "Wir treffen uns um 14 Uhr.",            # um = Präposition
    "Das passt, hm?",                        # hm als Frage-Anhängsel
    "Ah, okay, verstehe.",                   # Ausruf
])
def test_echte_woerter_bleiben_unberuehrt(roh):
    assert entferne_fuellwoerter(roh) == (roh, 0)


def test_grossschreibung_von_marken_bleibt():
    """„iPhone" nach einem Füllwort am Satzanfang wird nicht zu „IPhone"."""
    assert entferne_fuellwoerter("Ähm, iPhone ist da.")[0] == "iPhone ist da."


def test_nur_fuellwort_ergibt_leeren_text():
    """Die Pipeline faengt das ab und reicht dann den Rohtext weiter."""
    assert entferne_fuellwoerter("Äh") == ("", 1)
