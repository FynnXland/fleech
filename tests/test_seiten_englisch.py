"""Hauptfenster auf Englisch (6.6.0): Anzeigetexte aus gespeicherten Werten.

Gespeichert bleibt deutsch — übersetzt wird beim Anzeigen. Die Fallen dabei:
Tausendertrenner und Datum folgen der Sprache, Nutzertext bleibt unberührt, und
ein übersetzt angezeigter Profilname darf nie in die Einstellungen zurückwandern.
"""

import datetime as dt

import pytest

import fleech.i18n as i18n


@pytest.fixture
def englisch(monkeypatch):
    def setze(katalog):
        monkeypatch.setattr(i18n, "lade_katalog", lambda s: dict(katalog))
        i18n.setze("en")
    return setze


def test_zahl_und_datum_folgen_der_sprache(englisch):
    from fleech.ui.pages.anzeigetext import datum, ganzzahl

    assert ganzzahl(74245) == "74.245"
    assert datum(dt.date(2026, 11, 3)) == "03.11.2026"
    englisch({})
    assert ganzzahl(74245) == "74,245"
    assert datum(dt.date(2026, 11, 3)) == "Nov 3, 2026"


def test_uebersetzter_profilname_wandert_nicht_in_die_einstellungen(
        qapp, tmp_path, monkeypatch, englisch):
    """Der Titel der Detailspalte ist ein Eingabefeld. Zeigt es „Business“ und
    verliert den Fokus, darf daraus kein Umbenennen werden."""
    from uihelpers import make_main_window

    englisch({"Geschäftlich": "Business"})
    window, _panel, _store, settings, _changed = make_main_window(tmp_path, monkeypatch)
    seite = window.profiles
    seite.refresh()
    namen = [p["name"] for p in settings.profiles.items]
    zeile = next(i for i in range(seite._profiles_list.count())
                 if namen[seite._profiles_list.item(i).data(0x0100)] == "Geschäftlich")
    seite._profiles_list.setCurrentRow(zeile)
    assert seite._detail_title.text() == "Business"
    seite._on_rename_profile()
    assert "Geschäftlich" in [p["name"] for p in settings.profiles.items]
    seite._detail_title.setText("Kunden")
    seite._on_rename_profile()
    assert "Kunden" in [p["name"] for p in settings.profiles.items]
