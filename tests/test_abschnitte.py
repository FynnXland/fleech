"""Erkennen, waehrend man spricht (`fleech/stt/abschnitte.py`).

Ohne Mikrofon und Modell: Audio, Erkennung und VAD sind Attrappen. Geprueft wird,
wo geschnitten wird, dass am Ende nur der Rest erkannt wird — und dass jeder
Zweifel auf die Erkennung am Stueck zurueckfaellt.
"""

import threading
import time

import numpy as np

from fleech.stt import abschnitte as ab
from fleech.stt.abschnitte import (
    AbschnittsErkenner, Vorerkennung, erkenne_mit_vorab, finde_schnitt,
    ist_ueberlastet, kontext_prompt,
)

SR = 16000


def _s(sek):
    return int(sek * SR)


def _stueck(a, b):
    return {"start": _s(a), "end": _s(b)}


# --- Wo geschnitten wird ---------------------------------------------------

def test_zu_kurz_wird_nie_geschnitten():
    assert finde_schnitt([_stueck(0, 2), _stueck(3, 5)], _s(5.5), SR) is None


def test_schnitt_in_der_mitte_der_letzten_abgeschlossenen_pause():
    sprache = [_stueck(0, 4), _stueck(4.2, 6.5), _stueck(7.5, 9)]   # Pause 6.5–7.5
    assert finde_schnitt(sprache, _s(9.1), SR) == _s(7.0)


def test_kurze_atempause_ist_keine_schnittstelle():
    sprache = [_stueck(0, 4), _stueck(4.2, 9)]        # nur 200 ms
    assert finde_schnitt(sprache, _s(9.1), SR) is None


def test_laufende_pause_am_ende_zaehlt_wenn_lang_genug():
    sprache = [_stueck(0, 7)]
    assert finde_schnitt(sprache, _s(7.5), SR) == _s(7.2)
    assert finde_schnitt(sprache, _s(7.3), SR) is None


def test_pause_zu_frueh_fuer_einen_abschnitt():
    """Eine Pause bei 2 s darf keinen 2-s-Abschnitt erzeugen."""
    sprache = [_stueck(0, 2), _stueck(3, 9)]
    assert finde_schnitt(sprache, _s(9.1), SR) is None


def test_notschnitt_wenn_nie_eine_pause_kommt():
    assert finde_schnitt([_stueck(0, 28.5)], _s(28.5), SR) == _s(28.5)


def test_kontext_prompt_nimmt_das_ende_des_bisherigen():
    bisher = " ".join(f"w{i}" for i in range(100))
    p = kontext_prompt("Signalwort: Fleech.", bisher)
    assert p.startswith("Signalwort: Fleech. w60 ")
    assert p.endswith("w99")
    assert kontext_prompt(None, "") is None


def test_ueberlast_schwelle():
    assert not ist_ueberlastet(0.65, 21)
    assert ist_ueberlastet(5.0, 10)


# --- Der Erkenner im Lauf ---------------------------------------------------

class _Aufnahme:
    """Waechst wie eine echte Aufnahme; Sprache 0–7 s, Pause, Sprache 8–12 s."""

    def __init__(self):
        self.audio = np.zeros(0, dtype=np.float32)

    def bis(self, sek):
        self.audio = np.zeros(_s(sek), dtype=np.float32)

    def snapshot(self):
        return self.audio


def _vad(audio):
    sprache = [_stueck(0, 7), _stueck(8, 12)]
    n = audio.size
    return [{"start": s["start"], "end": min(s["end"], n)} for s in sprache
            if s["start"] < n]


def _warte(bedingung, sek=3.0):
    ende = time.monotonic() + sek
    while time.monotonic() < ende:
        if bedingung():
            return True
        time.sleep(0.01)
    return False


def test_erkenner_erkennt_den_abgeschlossenen_abschnitt_und_meldet_ihn():
    aufnahme = _Aufnahme()
    aufrufe = []

    def erkenne(audio, prompt, sprache):
        aufrufe.append((audio.size, prompt, sprache))
        return "Erster Satz.", ""

    e = AbschnittsErkenner(aufnahme.snapshot, erkenne, _vad, SR, takt_s=0.01)
    e.start("Signalwort: Fleech.", "de")
    aufnahme.bis(7.6)
    assert _warte(lambda: aufrufe)
    aufnahme.bis(12.5)
    v = e.ergebnis(timeout=2)
    assert v.text == "Erster Satz."
    assert v.bis == _s(7.2) and v.abschnitte == 1
    assert aufrufe[0] == (_s(7.2), "Signalwort: Fleech.", "de")


def test_ohne_abschnitt_gibt_es_kein_ergebnis():
    aufnahme = _Aufnahme()
    aufnahme.bis(3)
    e = AbschnittsErkenner(aufnahme.snapshot, lambda *a: ("x", ""), _vad, SR,
                           takt_s=0.01)
    e.start(None, "de")
    time.sleep(0.05)
    assert e.ergebnis(timeout=1) is None


def test_ergebnis_wartet_auf_den_abschnitt_in_arbeit():
    aufnahme = _Aufnahme()
    aufnahme.bis(7.6)
    laeuft, weiter = threading.Event(), threading.Event()

    def erkenne(audio, prompt, sprache):
        laeuft.set()
        weiter.wait(2)
        return "Fertig.", ""

    e = AbschnittsErkenner(aufnahme.snapshot, erkenne, _vad, SR, takt_s=0.01)
    e.start(None, "de")
    assert laeuft.wait(2)
    threading.Timer(0.1, weiter.set).start()
    assert e.ergebnis(timeout=2).text == "Fertig."


def test_fehler_im_hintergrund_laesst_den_bisherigen_stand_stehen():
    aufnahme = _Aufnahme()
    aufnahme.bis(7.6)

    def erkenne(*a):
        raise RuntimeError("CUDA weg")

    e = AbschnittsErkenner(aufnahme.snapshot, erkenne, _vad, SR, takt_s=0.01)
    e.start(None, "de")
    time.sleep(0.05)
    assert e.ergebnis(timeout=1) is None      # → am Stueck


def test_ueberlast_stoppt_weitere_abschnitte(monkeypatch):
    monkeypatch.setattr(ab, "ist_ueberlastet", lambda dauer, audio_s: True)
    aufnahme = _Aufnahme()
    aufnahme.bis(7.6)
    aufrufe = []

    def erkenne(audio, prompt, sprache):
        aufrufe.append(1)
        return "Eins.", ""

    e = AbschnittsErkenner(aufnahme.snapshot, erkenne, _vad, SR, takt_s=0.01)
    e.start(None, "de")
    assert _warte(lambda: aufrufe)
    aufnahme.bis(20)       # haette einen zweiten Abschnitt (8–12 s, Pause danach)
    time.sleep(0.1)
    assert e.ergebnis(timeout=1).abschnitte == 1
    assert len(aufrufe) == 1


def test_start_nach_dem_loslassen_laeuft_nicht_mehr_an():
    """Der Start-Thread kann langsamer sein als ein sehr kurzes Diktat."""
    aufnahme = _Aufnahme()
    aufnahme.bis(9)
    e = AbschnittsErkenner(aufnahme.snapshot, lambda *a: ("x", ""), _vad, SR,
                           takt_s=0.01)
    e.beende()
    e.start(None, "de")
    time.sleep(0.05)
    assert e.ergebnis(timeout=1) is None


# --- Zusammensetzen in der Pipeline -----------------------------------------

class _STT:
    def __init__(self, sprache="de", rest="zweiter Satz.", schwanz=""):
        self.cfg = type("C", (), {"language": sprache})()
        self.rest, self.schwanz = rest, schwanz
        self.aufrufe = []
        self.letzter_schwanz_ohne_ton = "alt"

    def transcribe(self, audio, sr, initial_prompt=None):
        self.aufrufe.append((audio.size, initial_prompt))
        self.letzter_schwanz_ohne_ton = self.schwanz
        return self.rest


def test_nur_der_rest_wird_erkannt_und_angehaengt():
    stt = _STT()
    vorab = Vorerkennung(_s(7.2), "Erster Satz.", "de", "P.", abschnitte=1)
    text = erkenne_mit_vorab(stt, np.zeros(_s(12.5), np.float32), SR, "P.", vorab)
    assert text == "Erster Satz. zweiter Satz."
    assert stt.aufrufe == [(_s(12.5) - _s(7.2), "P. Erster Satz.")]


def test_andere_sprache_verwirft_die_vorarbeit():
    stt = _STT(sprache="en", rest="whole thing")
    vorab = Vorerkennung(_s(7.2), "Erster Satz.", "de", None, abschnitte=1)
    text = erkenne_mit_vorab(stt, np.zeros(_s(12.5), np.float32), SR, None, vorab)
    assert text == "whole thing"
    assert stt.aufrufe == [(_s(12.5), None)]


def test_ohne_vorab_wie_bisher_am_stueck():
    stt = _STT(rest="alles")
    assert erkenne_mit_vorab(stt, np.zeros(_s(3), np.float32), SR, "P.", None) == "alles"
    assert stt.aufrufe == [(_s(3), "P.")]


def test_kein_rest_keine_erkennung_und_kein_alter_schwanz():
    stt = _STT()
    vorab = Vorerkennung(_s(7.2), "Alles schon da.", "de", None, abschnitte=1)
    text = erkenne_mit_vorab(stt, np.zeros(_s(7.3), np.float32), SR, None, vorab)
    assert text == "Alles schon da."
    assert stt.aufrufe == []
    assert stt.letzter_schwanz_ohne_ton == ""


def test_verworfene_schwaenze_aller_abschnitte_werden_gemeldet():
    stt = _STT(schwanz="Tschüss.")
    vorab = Vorerkennung(_s(7.2), "Eins.", "de", None, abschnitte=1,
                         verworfen=["Vielen Dank."])
    erkenne_mit_vorab(stt, np.zeros(_s(12), np.float32), SR, None, vorab)
    assert stt.letzter_schwanz_ohne_ton == "Vielen Dank. Tschüss."
