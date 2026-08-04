"""Vierter Artefakt-Filter: fremdsprachiger Wortsalat am Ende.

Alle „echt"-Faelle stammen aus dem Log des Nutzers — so kam es bei ihm an. Die
Gegenprobe ist wichtiger als der Treffer: Der Filter darf gesprochene Sprache
NICHT anfassen, auch nicht bei Betonungswiederholungen oder englischen Fachwörtern.
"""

import pytest

from fleech.textfilter import strip_gibberish_tail

ECHTER_TEXT = (
    "Deswegen wäre vielleicht cool, wenn man ab einem gewissen Punkt im Projekt das "
    "Team nicht mehr wechseln kann oder irgendwie anders, dass das verhindert wird "
    "auf jeden Fall, dass man damit abusen kann."
)


def test_realer_fall_wird_abgeschnitten():
    """Genau der Block, den der Nutzer nie gesagt hat."""
    müll = ("căn probabilien werden kann. seekers Odoo Time Go Go Go Go S Go Go "
            "and Let me and or")
    behalten, entfernt = strip_gibberish_tail(f"{ECHTER_TEXT} {müll}")
    assert behalten == ECHTER_TEXT
    assert "Odoo" in entfernt and "Go Go" in entfernt


def test_schnitt_reicht_bis_in_den_angefangenen_satz():
    """Halluzinationen fangen selten sauber an: der Satz davor kippt schon ins
    Rumänische („căn"). Ein halber fremder Satz ist genauso wertlos."""
    behalten, entfernt = strip_gibberish_tail(
        ECHTER_TEXT + " căn probabilien werden kann. seekers Go Go Go Go and me or")
    assert "căn" in entfernt
    assert "căn" not in behalten


# -- Gegenprobe: echte Sprache bleibt unangetastet ------------------------------------

@pytest.mark.parametrize("text", [
    # Betonung durch Wiederholung — im Verlaufstest als Fehlalarm aufgefallen.
    "Aber ansonsten gefällt mir sehr gut. Also gefällt mir wirklich wirklich sehr "
    "sehr sehr gut. Das war's gut.",
    # Englische Fachbegriffe sind bei ihm der Normalfall.
    "Also es war schon so gedacht, dass Team Friendly Fire dauerhaft aktiv ist. "
    "Mach das über dieses Cooldown, was man auch vom Shield kennt.",
    # Ein Name mit Akzent ist kein Sprachwechsel.
    "Ich habe mit François gesprochen und wir treffen uns im Café um drei.",
    "Kurzer Text ohne alles.",
    "",
])
def test_echte_sprache_bleibt(text):
    behalten, entfernt = strip_gibberish_tail(text)
    assert entfernt == ""
    assert behalten == text.strip()


def test_zu_wenig_echter_text_wird_nicht_angefasst():
    """Wenn nach dem Schnitt fast nichts übrig bliebe, ist die Lage unklar —
    dann lieber alles behalten und den Nutzer entscheiden lassen."""
    behalten, entfernt = strip_gibberish_tail("Hallo. seekers Go Go Go Go and me or")
    assert entfernt == ""
    assert behalten.startswith("Hallo")


def test_dotless_i_matcht_kein_normales_i():
    """Regressions-Schutz: mit re.IGNORECASE fiel das türkische „ı" mit „I"
    zusammen — dadurch galt jedes Wort mit einem i als fremdsprachig."""
    from fleech.textfilter import _FREMDE_DIAKRITIKA

    for wort in ("damit", "nicht", "ist", "wir", "Diktat", "IMMER"):
        assert not _FREMDE_DIAKRITIKA.search(wort), wort


def test_vier_gleiche_woerter_noetig_nicht_drei():
    """„sehr sehr sehr" ist Betonung, „Go Go Go Go" ist eine Schleife."""
    from fleech.textfilter import _gibberish_signale

    assert _gibberish_signale("sehr sehr sehr gut") < 2
    assert _gibberish_signale("Go Go Go Go and me or") >= 2
