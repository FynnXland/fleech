"""F1 — Freihand-Modus: Startwort sagen, sprechen, aufhören.

Die Zustandsmaschine kennt kein Audio-Gerät und kein Qt: Audio kommt herein,
Ereignisse kommen heraus. Damit ist der heikle Teil — wann startet, wann endet ein
Diktat — vollständig ohne Mikrofon prüfbar.
"""

import numpy as np
import pytest

from fleech.freihand import (
    Einstellungen, Ereignis, Lauscher, Zustand, enthaelt_wort, normalisiere,
)

SR = 16000


def block(sekunden: float = 0.2) -> np.ndarray:
    return np.zeros(int(SR * sekunden), dtype=np.float32)


def _lauscher(text="", sprache=True, **kw):
    """Lauscher mit Attrappen: `text` ist, was die Erkennung liefert."""
    e = Einstellungen(aktiv=True, **kw)
    lau = Lauscher(e, vad=lambda a: sprache, erkenner=lambda a: text, samplerate=SR)
    lau.start_lauschen()
    return lau


# -- Wortvergleich ---------------------------------------------------------------------


@pytest.mark.parametrize("gesprochen", [
    "Kimono", "kimono", "Kimono,", "Also, Kimono!", "kimono.", "  KIMONO  ",
])
def test_startwort_wird_trotz_schreibweise_erkannt(gesprochen):
    """Whisper schreibt dasselbe Wort mal mit Komma, mal groß — ein Startwort,
    das daran scheitert, wäre im Alltag unbrauchbar."""
    assert enthaelt_wort(gesprochen, "Kimono")


@pytest.mark.parametrize("gesprochen", [
    "Kimonos sind schön", "Ich mag Kimonoartiges", "Kimo no", "",
])
def test_teiltreffer_loesen_nicht_aus(gesprochen):
    """Wortgrenzen sind Pflicht — sonst aktiviert jedes längere Wort mit."""
    assert not enthaelt_wort(gesprochen, "Kimono")


def test_normalisierung_entfernt_diakritika():
    assert normalisiere("Männer, Öl!").split() == ["manner", "ol"]


def test_leeres_startwort_loest_nie_aus():
    assert not enthaelt_wort("irgendein Text", "")
    assert not enthaelt_wort("irgendein Text", "   ")


# -- Der Ablauf ------------------------------------------------------------------------


def test_startwort_startet_die_aufnahme():
    lau = _lauscher(text="also Kimono jetzt")
    assert lau.zustand is Zustand.LAUSCHT
    assert lau.verarbeite(block(1.0), jetzt=100.0) is Ereignis.START
    assert lau.zustand is Zustand.AUFNAHME


def test_ohne_startwort_passiert_nichts():
    lau = _lauscher(text="das ist ganz normales Gerede")
    assert lau.verarbeite(block(1.0), jetzt=100.0) is None
    assert lau.zustand is Zustand.LAUSCHT


def test_stille_beendet_das_diktat():
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    lau._erkenner = lambda a: "der eigentliche Diktattext"
    lau._vad = lambda a: False
    assert lau.verarbeite(block(0.5), jetzt=101.0) is None    # noch nicht lang genug
    assert lau.verarbeite(block(0.5), jetzt=103.5) is Ereignis.ENDE
    assert lau.zustand is Zustand.LAUSCHT


def test_sprechen_haelt_die_aufnahme_offen():
    """Eine Denkpause unter der Schwelle darf nicht abschneiden."""
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    for t in (101.0, 102.5, 104.0, 105.5):
        assert lau.verarbeite(block(0.3), jetzt=t) is None
    assert lau.zustand is Zustand.AUFNAHME


def test_abbruchwort_verwirft():
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    lau._erkenner = lambda a: "das war Quatsch, Abbrechen"
    lau._vad = lambda a: False
    assert lau.verarbeite(block(0.5), jetzt=103.5) is Ereignis.ABBRUCH
    assert lau.statistik.verworfen == 1


def test_abbruchwort_startet_nicht_sofort_neu():
    """Sonst machte ein Versprecher daraus eine Endlosschleife."""
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    lau._erkenner = lambda a: "Abbrechen"
    lau._vad = lambda a: False
    lau.verarbeite(block(0.5), jetzt=103.5)
    assert lau.zustand is Zustand.LAUSCHT
    lau._erkenner = lambda a: "Kimono"
    lau._vad = lambda a: True
    assert lau.verarbeite(block(1.0), jetzt=103.6) is None


def test_startwort_landet_nicht_im_diktat():
    """Sonst stünde „Kimono" am Anfang jedes Textes."""
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    assert len(lau.aufnahme_audio()) == 0
    lau.verarbeite(block(0.5), jetzt=100.5)
    assert len(lau.aufnahme_audio()) == int(0.5 * SR)


# -- Die Sparsamkeit, die den Dauerbetrieb trägt ---------------------------------------


def test_ohne_sprache_laeuft_die_erkennung_gar_nicht():
    """Der Kern der Architektur: Das teure Modell bleibt aus, solange das billige
    VAD keine Sprache meldet."""
    gerufen = []
    lau = Lauscher(Einstellungen(aktiv=True), vad=lambda a: False,
                   erkenner=lambda a: gerufen.append(1) or "Kimono", samplerate=SR)
    lau.start_lauschen()
    for i in range(10):
        lau.verarbeite(block(1.0), jetzt=100.0 + i * 2)
    assert gerufen == []
    assert lau.statistik.pruefungen == 0


def test_pruefungen_werden_entzerrt():
    """Ohne Mindestabstand liefe tiny bei durchgehendem Sprechen permanent."""
    gerufen = []
    lau = Lauscher(Einstellungen(aktiv=True), vad=lambda a: True,
                   erkenner=lambda a: gerufen.append(1) or "", samplerate=SR)
    lau.start_lauschen()
    for i in range(20):
        lau.verarbeite(block(0.1), jetzt=100.0 + i * 0.1)
    assert 1 <= len(gerufen) <= 4


def test_zu_wenig_material_wird_nicht_geprueft():
    gerufen = []
    lau = Lauscher(Einstellungen(aktiv=True), vad=lambda a: True,
                   erkenner=lambda a: gerufen.append(1) or "", samplerate=SR)
    lau.start_lauschen()
    lau.verarbeite(block(0.3), jetzt=100.0)
    assert gerufen == []


def test_ringpuffer_waechst_nicht():
    """Die technische Zusicherung hinter „kein Mitschnitt": Es bleiben immer nur
    wenige Sekunden im Speicher."""
    lau = _lauscher(text="")
    for i in range(50):
        lau.verarbeite(block(1.0), jetzt=100.0 + i)
    assert len(lau._ring) <= int(2.0 * SR) + 1


# -- Schalter und Grenzen ---------------------------------------------------------------


def test_ausgeschaltet_verarbeitet_nichts():
    lau = Lauscher(Einstellungen(aktiv=False), vad=lambda a: True,
                   erkenner=lambda a: "Kimono", samplerate=SR)
    lau.start_lauschen()
    assert lau.zustand is Zustand.AUS
    assert lau.verarbeite(block(1.0), jetzt=100.0) is None


def test_ausgeschlossene_apps():
    """In Spielen und Meetings ist Sprache im Raum die Regel."""
    lau = _lauscher(ausgeschlossene_apps=("game.exe", "Teams.exe"))
    assert lau.app_erlaubt("code.exe")
    assert not lau.app_erlaubt("game.exe")
    assert not lau.app_erlaubt("TEAMS.EXE")
    assert not lau.app_erlaubt("")


@pytest.mark.parametrize("eingabe,erwartet", [
    (0.2, 1.0), (1.0, 1.0), (2.0, 2.0), (4.0, 4.0), (9.0, 4.0), (None, 2.0),
])
def test_stille_dauer_bleibt_im_sinnvollen_bereich(eingabe, erwartet):
    assert Einstellungen(stille_s=eingabe).clamp().stille_s == erwartet


def test_fehler_in_den_stufen_legen_nichts_lahm():
    def kaputt(_a):
        raise RuntimeError("Modell weg")

    lau = Lauscher(Einstellungen(aktiv=True), vad=kaputt, erkenner=kaputt,
                   samplerate=SR)
    lau.start_lauschen()
    assert lau.verarbeite(block(1.0), jetzt=100.0) is None


def test_statistik_zaehlt_mit():
    lau = _lauscher(text="Kimono")
    lau.verarbeite(block(1.0), jetzt=100.0)
    assert lau.statistik.aktivierungen == 1
    assert lau.statistik.pruefungen == 1
    assert "1 Aktivierungen" in lau.statistik.als_text()
