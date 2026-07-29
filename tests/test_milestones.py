"""Wörter-Vergleich mit bekannten Büchern (Insights-Karte „Wörter diktiert")."""

import random

from fleech.milestones import WERKE, word_milestone


def test_zeigt_ein_erreichtes_werk_mit_faktor():
    # 74.245 Wörter = der echte Stand bei der Einführung des Features.
    zeile = word_milestone(74_245, random.Random(1))
    assert "Fache von" in zeile
    assert any(titel.strip("„“") in zeile for _w, titel in WERKE)


def test_waehlt_nur_aus_dem_was_wirklich_erreicht_ist():
    """Kern der Sache: Niemals ein Werk zeigen, das noch nicht überschritten ist —
    „das 0,3-Fache der Bibel" wäre kein Erfolgserlebnis, sondern eine Rüge."""
    for seed in range(50):
        zeile = word_milestone(30_000, random.Random(seed))
        zu_gross = [t.strip("„“") for w, t in WERKE if w > 30_000]
        assert not any(t in zeile for t in zu_gross), zeile


def test_variiert_ueber_die_erreichten_werke():
    """Ohne Abwechslung stünde monatelang derselbe Titel da."""
    gesehen = {word_milestone(200_000, random.Random(s)) for s in range(40)}
    assert len(gesehen) >= 3


def test_vor_dem_ersten_werk_kommt_das_naechste_ziel():
    zeile = word_milestone(5_000)
    assert "noch" in zeile and "Der kleine Prinz" in zeile
    assert "12.000" in zeile          # 17.000 − 5.000, deutsche Schreibweise


def test_knapp_darueber_wird_nicht_als_faktor_verkauft():
    """„das 1,0-Fache" liest sich albern — dann lieber die Klartext-Meldung."""
    zeile = word_milestone(17_200, random.Random(0))
    assert zeile == "gerade „Der kleine Prinz“ überschritten"


def test_leerer_und_unsinniger_stand_liefert_nichts():
    assert word_milestone(0) == ""
    assert word_milestone(-5) == ""


def test_deutsche_zahlschreibweise():
    zeile = word_milestone(34_000, random.Random(0))   # 2,0× Der kleine Prinz
    assert "." not in zeile.split("-Fache")[0] or "," in zeile


def test_werke_sind_aufsteigend_sortiert():
    """Die Liste wird von Hand gepflegt — eine falsche Reihenfolge fiele sonst
    erst auf, wenn die Karte Unsinn anzeigt."""
    zahlen = [w for w, _t in WERKE]
    assert zahlen == sorted(zahlen)
    assert len(set(zahlen)) == len(zahlen)
