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


@pytest.mark.parametrize("roh, erwartet", [
    # Linkes Komma gehört zum Satz → bleibt (6.4.1; vorher fiel es mit weg).
    ("Hallo zusammen, ähm, ich schicke euch das.", "Hallo zusammen, ich schicke euch das."),
    ("Liebe Anna, äh, danke für die Liste.", "Liebe Anna, danke für die Liste."),
    ("Ja, äh, das passt.", "Ja, das passt."),
    ("Okay, ja, äh, das machen wir.", "Okay, ja, das machen wir."),
    ("Alles klar, ähm, dann so.", "Alles klar, dann so."),
    ("Schreib eine Funktion, die die Liste sortiert, äh, die neuesten zuerst.",
     "Schreib eine Funktion, die die Liste sortiert, die neuesten zuerst."),
    ("Wenn das klappt, äh, dann machen wir weiter.",
     "Wenn das klappt, dann machen wir weiter."),
    ("Ich teste, damit ich das prüfen kann, ähm, er drückt dann den Knopf.",
     "Ich teste, damit ich das prüfen kann, er drückt dann den Knopf."),
    # Zögerkomma mitten im Satz → beide fallen, auch wenn links ein Einleiter steht.
    ("Das ist, äh, gut.", "Das ist gut."),
    ("Das ist ja, äh, gut.", "Das ist ja gut."),
    ("Ich habe, äh, das gemacht.", "Ich habe das gemacht."),
    ("Alles, äh, gut.", "Alles gut."),
    ("Ich finde, dass wir das, äh, morgen machen.", "Ich finde, dass wir das morgen machen."),
    ("Ich weiß, dass wir das morgen, äh, machen.", "Ich weiß, dass wir das morgen machen."),
    ("Die Sachen, die ich gesehen, äh, habe.", "Die Sachen, die ich gesehen habe."),
    ("Ich will, dass wir die neuen, äh, Sachen testen.",
     "Ich will, dass wir die neuen Sachen testen."),
    ("Weil die Zahl springt und deswegen, äh, kurz fällt.",
     "Weil die Zahl springt und deswegen kurz fällt."),
    ("Weil sie mit, äh, mit am schlimmsten war.", "Weil sie mit mit am schlimmsten war."),
    ("Die Liste, äh, ist fertig.", "Die Liste ist fertig."),
])
def test_linkes_komma_bleibt_nur_wenn_es_zum_satz_gehoert(roh, erwartet):
    assert entferne_fuellwoerter(roh)[0] == erwartet


@pytest.mark.parametrize("roh, erwartet", [
    ("The report is, um, almost done.", "The report is almost done."),
    ("Uh, what time does the store close on Saturdays?",
     "What time does the store close on Saturdays?"),
    ("Yeah, um, that works.", "Yeah, that works."),
    ("Hello everyone, uh, here is the update.", "Hello everyone, here is the update."),
    ("I think, uhm, we should go.", "I think we should go."),
    ("The list, erm, which I sent you.", "The list, which I sent you."),
    ("We could umm maybe start later.", "We could maybe start later."),
    ("That was it. Uh. Thanks.", "That was it. Thanks."),
])
def test_englische_fuellwoerter(roh, erwartet):
    text, anzahl = entferne_fuellwoerter(roh, "en")
    assert text == erwartet
    assert anzahl >= 1


@pytest.mark.parametrize("roh", [
    "I like it, so I bought it.",         # like/so sind echte Wörter
    "The umbrella is red and humid air is fine.",
    "Uh-huh, sure.",                      # Zustimmung, kein Füllwort
    "The UM campus is big.",              # Abkürzung
])
def test_englische_echte_woerter_bleiben(roh):
    assert entferne_fuellwoerter(roh, "en") == (roh, 0)


def test_englisch_nur_bei_englischer_diktiersprache():
    """„um" ist auf Deutsch eine Präposition; „äh" lässt Englisch unberührt."""
    assert entferne_fuellwoerter("Wir treffen uns um 14 Uhr.", "de")[1] == 0
    assert entferne_fuellwoerter("Wir treffen uns um 14 Uhr.", "")[1] == 0
    assert entferne_fuellwoerter("Wir treffen uns um 14 Uhr.")[1] == 0
    assert entferne_fuellwoerter("We meet, um, at two.", "en-US")[0] == "We meet at two."


def test_nur_fuellwort_ergibt_leeren_text():
    """Die Pipeline faengt das ab und reicht dann den Rohtext weiter."""
    assert entferne_fuellwoerter("Äh") == ("", 1)
