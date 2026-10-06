"""Die Pille muss beim Freihand-Diktat auch wirklich etwas bewirken.

Bis 5.8.2 war sie dort eine Attrappe: Sie zeigte „Aufnahme läuft" und aktivierte
ihre drei Knöpfe, aber alle drei wirkten ausschliesslich auf den
`RecordingController` — und der läuft beim Freihand-Weg gar nicht.

    ✕ Abbrechen → controller.cancel()       → None  → return, nichts passiert
    ✓ Fertig    → controller.stop_if_active() → nicht aktiv → nichts passiert
    ⏸ Pause     → recorder.recording = False  → „Pause ignoriert"

Schlimmer noch in einem Raum mit Hintergrundgeräuschen: Dort meldet das VAD
dauernd Sprache, die Stille-Erkennung greift nie — und ohne wirksamen Knopf kam
man aus der Aufnahme nicht mehr heraus. Genau so gemeldet: „kann ich nicht auf
Abbrechen drücken, manchmal auch nicht auf Absenden, manchmal stuckt das dann".
"""

import numpy as np

from fleech.freihand import (
    MAX_DIKTAT_S, Einstellungen, Ereignis, Lauscher, Zustand,
)

SR = 16000


def block(sekunden: float = 0.2) -> np.ndarray:
    return np.zeros(int(SR * sekunden), dtype=np.float32)


def _aufnehmender_lauscher(text="Kimono"):
    """Ein Lauscher, der bereits im Aufnahme-Zustand ist."""
    lau = Lauscher(Einstellungen(aktiv=True, startwort="Kimono"),
                   vad=lambda a: True, erkenner=lambda a: text, samplerate=SR)
    lau.start_lauschen()
    assert lau.verarbeite(block(1.0), jetzt=100.0) is Ereignis.START
    return lau


# -- ✓ Fertig ----------------------------------------------------------------------------


def test_fertig_beendet_sofort():
    """Wichtig ist das SOFORT: Der Knopf darf nicht darauf warten, dass die
    Stille-Erkennung zufällig zustimmt — in einem lauten Raum tut sie das nie."""
    lau = _aufnehmender_lauscher()
    lau.verarbeite(block(1.0), jetzt=101.0)      # es wird geredet
    assert lau.beende_vorzeitig() is True
    assert lau.verarbeite(block(0.2), jetzt=101.2) is Ereignis.ENDE
    assert lau.zustand is Zustand.LAUSCHT


def test_fertig_liefert_das_gesammelte_audio():
    lau = _aufnehmender_lauscher()
    for i in range(10):
        lau.verarbeite(block(0.2), jetzt=100.2 + i * 0.2)
    lau.beende_vorzeitig()
    lau.verarbeite(block(0.2), jetzt=103.0)
    assert len(lau.aufnahme_audio()) >= int(1.8 * SR)


def test_fertig_ohne_laufendes_diktat_tut_nichts():
    lau = Lauscher(Einstellungen(aktiv=True), vad=lambda a: True,
                   erkenner=lambda a: "", samplerate=SR)
    lau.start_lauschen()
    assert lau.beende_vorzeitig() is False


# -- ✕ Abbrechen -------------------------------------------------------------------------


def test_abbrechen_verwirft():
    lau = _aufnehmender_lauscher()
    lau.verarbeite(block(1.0), jetzt=101.0)
    assert lau.verwirf_vorzeitig() is True
    assert lau.verarbeite(block(0.2), jetzt=101.2) is Ereignis.ABBRUCH
    assert lau.zustand is Zustand.LAUSCHT
    assert lau.statistik.verworfen == 1


def test_abbrechen_hat_vorrang_vor_fertig():
    """Wer beides drückt, meint verwerfen — das ist die Entscheidung, die man
    nicht zurücknehmen kann, also gewinnt sie."""
    lau = _aufnehmender_lauscher()
    lau.beende_vorzeitig()
    lau.verwirf_vorzeitig()
    assert lau.verarbeite(block(0.2), jetzt=101.2) is Ereignis.ABBRUCH


def test_wunsch_gilt_nur_fuer_dieses_diktat():
    """Ein stehengebliebenes Flag würde das NÄCHSTE Diktat sofort beenden."""
    lau = _aufnehmender_lauscher()
    lau.beende_vorzeitig()
    lau.verarbeite(block(0.2), jetzt=101.2)          # ENDE
    assert lau.zustand is Zustand.LAUSCHT

    lau._sperre_bis = 0.0                            # Sperre nach dem Start überspringen
    assert lau.verarbeite(block(1.0), jetzt=110.0) is Ereignis.START
    assert lau.verarbeite(block(0.2), jetzt=110.2) is None, "Flag war noch gesetzt"


# -- ⏸ Pause -----------------------------------------------------------------------------


def test_pause_sammelt_nicht_weiter():
    lau = _aufnehmender_lauscher()
    for i in range(5):
        lau.verarbeite(block(0.2), jetzt=100.2 + i * 0.2)
    vorher = len(lau.aufnahme_audio())
    assert lau.pausiere_diktat(True) is True
    for i in range(5):
        lau.verarbeite(block(0.2), jetzt=101.2 + i * 0.2)
    assert len(lau.aufnahme_audio()) == vorher


def test_pause_haelt_die_stille_uhr_an():
    """DER Sinn der Pause: kurz mit jemandem sprechen, ohne das Diktat zu
    verlieren. Liefe die Uhr weiter, wäre es nach `stille_s` beendet."""
    lau = _aufnehmender_lauscher()
    lau.pausiere_diktat(True)
    lau._vad = lambda a: False                       # im Raum ist es still
    for i in range(60):                              # 12 s Pause
        assert lau.verarbeite(block(0.2), jetzt=101.0 + i * 0.2) is None
    assert lau.zustand is Zustand.AUFNAHME


def test_pause_wieder_aufheben():
    lau = _aufnehmender_lauscher()
    lau.pausiere_diktat(True)
    lau.verarbeite(block(0.2), jetzt=101.0)
    assert lau.diktat_pausiert is True
    lau.pausiere_diktat(False)
    assert lau.diktat_pausiert is False
    vorher = len(lau.aufnahme_audio())
    lau.verarbeite(block(0.2), jetzt=101.4)
    assert len(lau.aufnahme_audio()) > vorher


def test_pause_ohne_diktat_tut_nichts():
    lau = Lauscher(Einstellungen(aktiv=True), vad=lambda a: True,
                   erkenner=lambda a: "", samplerate=SR)
    lau.start_lauschen()
    assert lau.pausiere_diktat(True) is False
    assert lau.diktat_pausiert is False


# -- Der Deckel gegen die Aufnahme, die nie endet -----------------------------------------


def test_diktat_endet_spaetestens_nach_dem_deckel():
    """In einem Raum mit laufendem Video meldet das VAD dauerhaft Sprache — die
    Stille-Erkennung greift dann nie. Der Knopf wirkt jetzt; das hier ist die
    zweite Sicherung für den Fall, dass niemand hinsieht."""
    lau = _aufnehmender_lauscher()
    jetzt, ereignis = 100.0, None
    for i in range(int(MAX_DIKTAT_S / 0.2) + 20):
        jetzt += 0.2
        ereignis = lau.verarbeite(block(0.2), jetzt=jetzt)
        if ereignis is not None:
            break
    assert ereignis is Ereignis.ENDE
    laenge = jetzt - 100.0
    # Ein Block Toleranz nach unten: Der Deckel greift, sobald das GESAMMELTE
    # Audio ihn erreicht — die Wanduhr im Test kann eine Blocklänge davorliegen.
    assert MAX_DIKTAT_S - 0.3 <= laenge <= MAX_DIKTAT_S + 1.0


def test_der_deckel_ist_grosszuegig_aber_endlich():
    assert 60.0 <= MAX_DIKTAT_S <= 300.0


# -- Verdrahtung in der Oberfläche --------------------------------------------------------


def test_pillenknoepfe_fragen_zuerst_den_freihand_weg():
    """Sonst laufen sie wie bisher in den RecordingController, der beim
    Freihand-Diktat gar nicht aktiv ist."""
    import inspect

    from fleech.ui.desktop import DesktopApp

    for name in ("_cancel_recording", "_finish_recording", "toggle_pause"):
        quelle = inspect.getsource(getattr(DesktopApp, name))
        assert "_freihand_lauscher()" in quelle, f"{name} kennt den Freihand-Weg nicht"


def test_finish_knopf_ist_nicht_mehr_direkt_am_controller():
    """Er hing als Lambda direkt an `controller.stop_if_active` — genau deshalb
    war er beim Freihand-Diktat wirkungslos."""
    import inspect

    from fleech.ui import desktop

    quelle = inspect.getsource(desktop)
    assert "finish_requested.connect(self._finish_recording)" in quelle
    assert "finish_requested.connect(lambda" not in quelle


def test_freihand_lauscher_nur_waehrend_der_aufnahme():
    import types

    from fleech.ui.desktop import DesktopApp

    lau = _aufnehmender_lauscher()
    fake = types.SimpleNamespace(_freihand=types.SimpleNamespace(lauscher=lau))
    assert DesktopApp._freihand_lauscher(fake) is lau

    lau.beende_vorzeitig()
    lau.verarbeite(block(0.2), jetzt=101.2)          # zurück ins Lauschen
    assert DesktopApp._freihand_lauscher(fake) is None

    assert DesktopApp._freihand_lauscher(types.SimpleNamespace(_freihand=None)) is None
    assert DesktopApp._freihand_lauscher(types.SimpleNamespace()) is None


# -- Anlaufzeit: die Pille darf nicht weg sein, bevor man reagieren kann ------------------


def test_diktat_endet_nicht_sofort_nach_dem_startwort():
    """DER Grund, warum „Abbrechen funktioniert nicht" gemeldet wurde.

    Das VAD braucht mindestens 0,8 s Audio, um Sprache zu melden. Direkt nach dem
    Startwort ist die Aufnahme aber erst 0,2 s lang — in dieser Zeit meldet es
    zwangsläufig „keine Sprache", egal ob jemand spricht. Die Stille-Uhr lief
    also gegen einen Messfehler, und im Protokoll stand immer exakt `stille_s`:

        15:37:38  Startwort erkannt in 'Apfel.'
        15:37:38  Aufnahme ohne Sprache — verworfen (2.0 s)

    Der Abbruch-Knopf war dabei in Ordnung — es gab nur nichts mehr abzubrechen.
    """
    from fleech.freihand import ANLAUF_S

    lau = _aufnehmender_lauscher()
    lau._vad = lambda a: False            # das VAD meldet NIE Sprache

    jetzt, ereignis = 100.0, None
    for _ in range(60):
        jetzt += 0.2
        ereignis = lau.verarbeite(block(0.2), jetzt=jetzt)
        if ereignis is not None:
            break

    gelaufen = jetzt - 100.0
    assert ereignis is not None
    mindestens = ANLAUF_S + lau.einstellungen.stille_s
    assert gelaufen >= mindestens - 0.3, (
        f"nach {gelaufen:.1f} s beendet, erwartet frühestens {mindestens:.1f} s")


def test_anlaufzeit_deckt_das_vad_fenster_ab():
    """Sie ist keine Bequemlichkeit, sondern eine Messgrenze: Vor Ablauf des
    VAD-Fensters ist „keine Sprache" keine Aussage über den Sprecher."""
    from fleech.freihand import ANLAUF_S, VAD_FENSTER_S

    assert ANLAUF_S >= VAD_FENSTER_S


def test_wer_redet_haelt_die_aufnahme_trotzdem_offen():
    """Die Anlaufzeit darf nichts verlängern, was ohnehin läuft."""
    lau = _aufnehmender_lauscher()
    lau._vad = lambda a: True
    for i in range(40):
        assert lau.verarbeite(block(0.2), jetzt=100.2 + i * 0.2) is None
    assert lau.zustand is Zustand.AUFNAHME


def test_abbrechen_ins_leere_wird_protokolliert(caplog):
    """Der Klick kam an, aber es lief nichts mehr — genau dieser Fall stand
    nirgends und wurde deshalb als „Knopf kaputt" erlebt."""
    import logging
    import types

    from fleech.ui.desktop import DesktopApp

    fake = types.SimpleNamespace(
        _freihand=None,
        controller=types.SimpleNamespace(cancel=lambda: None),
    )
    fake._freihand_lauscher = types.MethodType(DesktopApp._freihand_lauscher, fake)
    with caplog.at_level(logging.INFO, logger="fleech.ui.desktop"):
        DesktopApp._cancel_recording(fake)
    assert any("nichts zu verwerfen" in r.message for r in caplog.records)
