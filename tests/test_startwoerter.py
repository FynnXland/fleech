"""Mehrere Startwörter: eintippen, Enter, steht in der Liste.

Welches Wort die eigene Aussprache zuverlässig trifft, lässt sich nicht
vorhersagen — das hat diese Sitzung an „Kimono", „Apfel", „Redax" und „Fleech"
durchgespielt. Zwei oder drei Kandidaten nebeneinander ersetzen das
Herumprobieren mit einem einzigen.
"""

import pytest

from fleech.freihand import (
    enthaelt_eines, woerter_als_text, zerlege_woerter,
)


# -- Zerlegen ----------------------------------------------------------------------------


@pytest.mark.parametrize("roh,erwartet", [
    ("Kimono", ("Kimono",)),
    ("Kimono\nApfel", ("Kimono", "Apfel")),
    ("Kimono, Apfel", ("Kimono", "Apfel")),
    ("Kimono; Apfel", ("Kimono", "Apfel")),
    ("  Kimono  \n\n  Apfel  ", ("Kimono", "Apfel")),
    (["Kimono", "Apfel"], ("Kimono", "Apfel")),
    ("", ()),
    ("   ", ()),
    (None, ()),
])
def test_zerlegen(roh, erwartet):
    assert zerlege_woerter(roh) == erwartet


def test_doppelte_fallen_heraus():
    """Wer dasselbe Wort zweimal einträgt, meint es einmal — und die Prüfung
    zweimal laufen zu lassen kostet nur Zeit."""
    assert zerlege_woerter("Kimono\nkimono\nKIMONO") == ("Kimono",)


def test_reihenfolge_bleibt():
    """Das erste Wort ist das, was in Tray und Statuszeile steht."""
    assert zerlege_woerter("Apfel\nKimono\nZeppelin") == ("Apfel", "Kimono", "Zeppelin")


# -- Erkennen ----------------------------------------------------------------------------


def test_jedes_wort_loest_aus():
    assert enthaelt_eines("also Kimono jetzt", "Kimono\nApfel") == "Kimono"
    assert enthaelt_eines("also Apfel jetzt", "Kimono\nApfel") == "Apfel"


def test_fremdes_wort_loest_nicht_aus():
    assert enthaelt_eines("ganz normales Gerede", "Kimono\nApfel") == ""


def test_es_wird_gemeldet_WELCHES_wort_traf():
    """Bei mehreren Startwörtern ist „hat ausgelöst" nur die halbe Auskunft —
    im Protokoll soll stehen, worauf Fleech angesprungen ist."""
    assert enthaelt_eines("Hey, Apfel.", "Kimono\nApfel\nZeppelin") == "Apfel"


def test_die_unschaerfe_gilt_fuer_jedes_wort():
    """Das Prüfmodell zerreisst Wörter — „Kimu" für „Kimono" ist echt aus dem
    Protokoll. Diese Toleranz darf nicht beim ersten Wort aufhören."""
    assert enthaelt_eines("Kimu", "Apfel\nKimono") == "Kimono"


def test_leere_liste_loest_nie_aus():
    assert enthaelt_eines("Kimono", "") == ""
    assert enthaelt_eines("Kimono", None) == ""


def test_erstes_treffendes_wort_gewinnt():
    assert enthaelt_eines("Kimono und Apfel", "Apfel\nKimono") == "Apfel"


# -- Anzeige -----------------------------------------------------------------------------


@pytest.mark.parametrize("roh,erwartet", [
    ("Kimono", "Kimono"),
    ("Kimono\nApfel", "Kimono oder Apfel"),
    ("Kimono\nApfel\nZeppelin", "Kimono, Apfel oder Zeppelin"),
    ("", ""),
])
def test_anzeigetext(roh, erwartet):
    """Die gespeicherte Form ist zeilengetrennt — direkt ins Tray-Menü gehängt
    ergäbe das einen Umbruch mitten im Satz."""
    assert woerter_als_text(roh) == erwartet


# -- Priming -----------------------------------------------------------------------------


def test_alle_woerter_werden_dem_modell_vorgesagt():
    """Das Priming wirkt je Wort. Ein nicht geprimtes Wort wäre genau das, das
    nie erkannt wird — und man suchte den Fehler bei der Aussprache."""
    import types

    from fleech.freihand import baue_erkenner_aus_engine

    gesehen = []
    engine = types.SimpleNamespace(
        transcribe_kurz=lambda audio, language=None, initial_prompt=None:
            gesehen.append(initial_prompt) or "")
    import numpy as np
    baue_erkenner_aus_engine(engine, sprache="de",
                            startwort="Kimono\nApfel")(np.zeros(16000, dtype=np.float32))
    assert gesehen == ["Kimono. Apfel."]


# -- Die Zustandsmaschine ----------------------------------------------------------------


def test_lauscher_startet_bei_jedem_wort():
    import numpy as np

    from fleech.freihand import Einstellungen, Ereignis, Lauscher, Zustand

    for gesagt in ("Kimono", "Apfel", "Zeppelin"):
        lau = Lauscher(Einstellungen(aktiv=True, startwort="Kimono\nApfel\nZeppelin"),
                       vad=lambda a: True, erkenner=lambda a, g=gesagt: g,
                       samplerate=16000)
        lau.start_lauschen()
        audio = np.zeros(16000, dtype=np.float32)
        assert lau.verarbeite(audio, jetzt=100.0) is Ereignis.START, gesagt
        assert lau.zustand is Zustand.AUFNAHME


def test_einstellungen_bieten_die_woerter_fertig_an():
    from fleech.freihand import Einstellungen

    e = Einstellungen(aktiv=True, startwort="Kimono\nApfel")
    assert e.startwoerter == ("Kimono", "Apfel")


def test_ein_wort_bleibt_wie_bisher():
    """Bestehende settings.json haben einen einzelnen String — der muss ohne
    Migration weiterlaufen."""
    from fleech.freihand import Einstellungen
    from fleech.usersettings import UserSettings

    assert UserSettings().freihand.startwort == "Kimono"
    assert Einstellungen(aktiv=True, startwort="Kimono").startwoerter == ("Kimono",)


def test_die_startwortliste_steht_in_keiner_einstellungsseite_mehr(qapp):
    """Befund E-5/E-9: Die Freihand-Oberflaeche ist in 5.11.0 entfernt — mit ihr
    die Startwoerter-Liste und der Probe-Knopf. Vorher pruefte hier ein Test, dass
    beide auf der Aufnahme-Seite stehen und Eingaben in die Einstellungen
    zurueckschreiben; das waere jetzt genau die falsche Zusicherung (der Modus ist
    stillgelegt, ein bedienbares Feld verspraeche Wirkung, die es nicht gibt).
    Die Zerlege-/Erkenn-Logik oben bleibt geprueft — der Code ist eingefroren,
    nicht geloescht."""
    from fleech.ui.settings_window import SettingsPanel
    from fleech.usersettings import UserSettings

    s = UserSettings()
    s.freihand.startwort = "Kimono\nApfel"
    panel = SettingsPanel(s, lambda sec: None, lambda: [])
    assert getattr(panel, "_startwort_liste", None) is None
    assert getattr(panel, "_startwort_probe_btn", None) is None
    # Die Einstellung selbst bleibt unangetastet (eingefroren, nicht geleert).
    assert zerlege_woerter(s.freihand.startwort) == ("Kimono", "Apfel")
