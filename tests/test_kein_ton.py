"""Kein-Ton-Wache: sagen, dass das Mikrofon nichts liefert — waehrend des Diktats.

Befund H-B2: 198 von 1603 Aufnahmen blieben ohne Transkript, weil kein Ton
ankam; die laengste dauerte 163 Sekunden. Der Pegel war die ganze Zeit bekannt,
diente aber nur der Wellenlinie — und die verstaerkt sich automatisch, sodass
„tot" und „leise" gleich aussehen.

Geprueft wird beides: dass der Recorder den ROHEN Pegel ueber ein Zeitfenster
anbietet (`rohpegel_max`), und dass die Wache daraus genau einmal je Aufnahme
eine Warnung macht — nie in der Pause, nie bei Ton, und ohne die Aufnahme
anzufassen. Dazu der PortAudio-Statuszaehler aus Befund B-6.
"""

import time
import types

import numpy as np
import pytest

from fleech.audio import Recorder
from fleech.ui.overlaypille.konstanten import (
    KEIN_TON_AB_S,
    KEIN_TON_FENSTER_S,
    KEIN_TON_SCHWELLE,
)


class _FakeStream:
    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def _recorder(rate=16000):
    r = Recorder(samplerate=rate)
    r._stream = _FakeStream()
    r._capture_rate = rate
    return r


def _block(wert=0.5, n=160):
    return np.full((n, 1), wert, dtype=np.float32)


# -- Recorder: der rohe Pegelverlauf ---------------------------------------------------


def test_rohpegel_max_nimmt_das_lauteste_im_fenster():
    """Eine einzige gesprochene Silbe im Fenster beweist, dass Ton ankommt."""
    r = _recorder()
    r._callback(_block(0.0001), 160, None, None)
    r._callback(_block(0.30), 160, None, None)
    r._callback(_block(0.0001), 160, None, None)
    assert r.rohpegel_max(5.0) == pytest.approx(0.30, abs=1e-4)


def test_rohpegel_max_vergisst_was_aus_dem_fenster_faellt():
    """Sonst wuerde ein lautes Wort von vor einer Minute die Wache ewig beruhigen."""
    r = _recorder()
    r._callback(_block(0.30), 160, None, None)
    # Zeitstempel kuenstlich altern lassen — schneller als zu warten.
    r._rohpegel = type(r._rohpegel)((zeit - 30.0, rms) for zeit, rms in r._rohpegel)
    assert r.rohpegel_max(5.0) == 0.0
    r._callback(_block(0.02), 160, None, None)
    assert r.rohpegel_max(5.0) == pytest.approx(0.02, abs=1e-4)


def test_rohpegel_ist_ungeglaettet_und_ohne_stream_null():
    """`level` faerbt die Anzeige, `rohpegel_max` ist die ungeschminkte Messung."""
    r = _recorder()
    r._callback(_block(0.004), 160, None, None)
    assert r.rohpegel_max(5.0) == pytest.approx(0.004, abs=1e-5)
    r.stop()
    assert r.rohpegel_max(5.0) == 0.0


def test_pause_traegt_nichts_in_den_pegelverlauf_ein():
    r = _recorder()
    r.pause()
    r._callback(_block(0.9), 160, None, None)
    assert r.rohpegel_max(5.0) == 0.0


def test_neue_aufnahme_beginnt_mit_leerem_pegelverlauf(monkeypatch):
    """Sonst zaehlte der Ton der VORIGEN Aufnahme als Lebenszeichen."""
    r = Recorder()
    r._stream = _FakeStream()
    r._callback(_block(0.5), 160, None, None)
    r._status_zaehler = 3
    r._stream = None

    class FakeSD:
        class PortAudioError(Exception):
            pass

        @staticmethod
        def InputStream(**kwargs):
            return _FakeStream()

    monkeypatch.setitem(__import__("sys").modules, "sounddevice", FakeSD)
    monkeypatch.setattr("fleech.audio.resolve_input_device",
                        lambda d, on_fallback=None: None)
    r.start()
    assert r.rohpegel_max(5.0) == 0.0
    assert r.status_zaehler == 0


# -- Recorder: PortAudio-Statuscodes (Befund B-6) --------------------------------------


def test_portaudio_status_meldet_sich_einmal_und_zaehlt_dann(caplog):
    """Overflow oder ein verschwundenes Geraet erklaeren spaeter das leere
    Transkript. Bis 5.10.4 stand das nur in log.debug — im Normalbetrieb also
    nirgends (Befund B-6). Jetzt: eine INFO-Zeile, danach nur noch der Zaehler."""
    r = _recorder()
    with caplog.at_level("INFO", logger="fleech.audio"):
        for _ in range(5):
            r._callback(_block(0.5), 160, None, "input overflow")
    zeilen = [s for s in caplog.messages if "Audio-Status" in s]
    assert len(zeilen) == 1, zeilen
    assert r.status_zaehler == 5


def test_stop_meldet_die_summe_der_statuscodes(caplog):
    r = _recorder()
    for _ in range(4):
        r._callback(_block(0.5), 160, None, "input overflow")
    with caplog.at_level("INFO", logger="fleech.audio"):
        r.stop()
    assert any("4x" in s for s in caplog.messages), caplog.messages


def test_ohne_status_bleibt_das_protokoll_still(caplog):
    r = _recorder()
    with caplog.at_level("INFO", logger="fleech.audio"):
        r._callback(_block(0.5), 160, None, None)
        r.stop()
    assert not [s for s in caplog.messages if "Audio-Status" in s or "PortAudio" in s]


# -- Die Wache: aus Pegel wird eine Warnung --------------------------------------------


class _FakeRecorder:
    """Recorder-Doppel mit vorgegebenen Pegeln — kein Mikrofon noetig."""

    def __init__(self, pegel=0.0, position=10.0, recording=True, paused=False):
        self.pegel = pegel
        self.position = position
        self.recording = recording
        self.paused = paused
        self.level = pegel

    def rohpegel_max(self, sekunden=5.0):
        return self.pegel


class _FakeOverlay:
    def __init__(self):
        self.verlauf = []
        self.warnt = False

    def set_kein_ton(self, an):
        if an != self.warnt:      # dieselbe Idempotenz wie die echte Pille
            self.warnt = an
            self.verlauf.append(an)


def _app(**kwargs):
    """DesktopApp-Doppel: nur die Felder, die die Wache anfasst.

    `_pruefe_kein_ton` wird bewusst mit angehaengt — `_pegel_fuer_pille` ruft die
    Methode ueber `self` auf und schluckt Fehler; ohne sie liefe der Test ins
    Leere statt in eine Aussage.
    """
    from fleech.ui.desktop import DesktopApp

    fake = types.SimpleNamespace(
        recorder=_FakeRecorder(**kwargs),
        overlay=_FakeOverlay(),
        _kein_ton_gemeldet=False,
        _freihand_level=lambda: 0.0,
    )
    fake._pruefe_kein_ton = lambda: DesktopApp._pruefe_kein_ton(fake)
    return fake


def _pruefe(fake):
    fake._pruefe_kein_ton()


def test_stille_warnt_nach_der_wartezeit():
    fake = _app(pegel=0.00005, position=KEIN_TON_AB_S + 0.5)
    _pruefe(fake)
    assert fake.overlay.warnt is True
    assert fake._kein_ton_gemeldet is True


def test_am_anfang_wird_nicht_gewarnt():
    """Die ersten Sekunden sind still: Taste gedrueckt, Luft geholt."""
    fake = _app(pegel=0.0, position=KEIN_TON_AB_S - 0.5)
    _pruefe(fake)
    assert fake.overlay.warnt is False
    assert fake._kein_ton_gemeldet is False


def test_bei_ton_wird_nicht_gewarnt():
    fake = _app(pegel=KEIN_TON_SCHWELLE * 10, position=60.0)
    _pruefe(fake)
    assert fake.overlay.warnt is False


def test_die_warnung_kommt_nur_einmal_je_aufnahme():
    """Ein Dauerfeuer waere schlimmer als gar keine Meldung."""
    fake = _app(pegel=0.0, position=10.0)
    for _ in range(50):
        _pruefe(fake)
    assert fake.overlay.verlauf == [True]


def test_ton_nimmt_die_warnung_zurueck_und_sie_kehrt_nicht_wieder():
    fake = _app(pegel=0.0, position=10.0)
    _pruefe(fake)
    fake.recorder.pegel = 0.05           # es kommt wieder Ton
    _pruefe(fake)
    assert fake.overlay.warnt is False
    fake.recorder.pegel = 0.0            # danach wieder still
    for _ in range(10):
        _pruefe(fake)
    assert fake.overlay.verlauf == [True, False]


def test_in_der_pause_wird_nie_gewarnt():
    """Pause heisst „ich rede gerade absichtlich nicht"."""
    fake = _app(pegel=0.0, position=60.0, paused=True)
    _pruefe(fake)
    assert fake.overlay.warnt is False
    assert fake._kein_ton_gemeldet is False


def test_ohne_laufenden_recorder_wird_nicht_gewarnt():
    """Beim Freihand-Diktat laeuft der Recorder nicht — sein Pegel ist dann 0."""
    fake = _app(pegel=0.0, position=60.0, recording=False)
    _pruefe(fake)
    assert fake.overlay.warnt is False


def test_die_wache_fasst_die_aufnahme_nicht_an():
    """Sie zeigt nur. Wer sie stoppen laesst, verliert genau das Diktat, das er
    retten wollte."""
    import inspect

    from fleech.ui.desktop import DesktopApp

    quelle = inspect.getsource(DesktopApp._pruefe_kein_ton)
    # Bewusst auf AUFRUFE geprueft, nicht auf blosse Woerter: „stoppt nichts"
    # steht ja gerade im Docstring.
    for verboten in ("recorder.stop(", "recorder.pause(", "recorder.resume(",
                     "_cancel_recording", "_finish_recording", "set_state"):
        assert verboten not in quelle, f"die Wache greift ein: {verboten}"


def test_der_pegel_fuer_die_pille_traegt_die_wache_mit():
    """Kein eigener Timer: Die Pruefung haengt am 50-ms-Takt der Wellenlinie."""
    from fleech.ui.desktop import DesktopApp

    fake = _app(pegel=0.0, position=10.0)
    fake.recorder.level = 0.0
    assert DesktopApp._pegel_fuer_pille(fake) == 0.0
    assert fake.overlay.warnt is True


def test_ein_fehler_der_wache_kostet_nicht_die_anzeige():
    fake = _app(pegel=0.0, position=10.0)

    def kaputt(sekunden=5.0):
        raise RuntimeError("kaputt")

    fake.recorder.rohpegel_max = kaputt
    fake.recorder.level = 0.42
    from fleech.ui.desktop import DesktopApp

    assert DesktopApp._pegel_fuer_pille(fake) == pytest.approx(0.42)


# -- Die Pille zeigt es --------------------------------------------------------------


def test_pille_zeigt_warnung_und_nimmt_sie_zurueck(qapp):
    pytest.importorskip("PySide6")
    from fleech.ui.overlay_qt import OverlayWindow
    from fleech.ui.state import AppState
    from fleech.usersettings import UserSettings

    s = UserSettings().overlay
    s.visibility = "always"
    o = OverlayWindow(s)
    o.set_app_state(AppState.LISTENING)

    o.set_kein_ton(True)
    assert o._kein_ton is True
    assert o._math_dot._kein_ton is True
    assert not o._caption.isHidden()
    assert "Kein Ton" in o._caption._label.text()

    o.set_kein_ton(False)
    assert o._math_dot._kein_ton is False
    assert o._caption.isHidden()
    o.close()


def test_pille_raeumt_die_warnung_beim_zustandswechsel_weg(qapp):
    """Die Warnung gehoert zur laufenden Aufnahme — danach nie stehen lassen."""
    pytest.importorskip("PySide6")
    from fleech.ui.overlay_qt import OverlayWindow
    from fleech.ui.state import AppState
    from fleech.usersettings import UserSettings

    s = UserSettings().overlay
    s.visibility = "always"
    o = OverlayWindow(s)
    o.set_app_state(AppState.LISTENING)
    o.set_kein_ton(True)
    o.set_app_state(AppState.PROCESSING)
    assert o._kein_ton is False
    assert o._math_dot._kein_ton is False
    o.close()


def test_pause_gewinnt_gegen_die_warnung(qapp):
    """Zwei Blasen um denselben Platz — und in der Pause ist die Warnung falsch."""
    pytest.importorskip("PySide6")
    from fleech.ui.overlay_qt import OverlayWindow
    from fleech.ui.state import AppState
    from fleech.usersettings import UserSettings

    s = UserSettings().overlay
    s.visibility = "always"
    o = OverlayWindow(s)
    o.set_app_state(AppState.LISTENING)
    o.set_kein_ton(True)
    o.set_paused(True)
    assert o._kein_ton is False
    assert "Pause" in o._caption._label.text()
    o.close()


def test_die_schwelle_liegt_unter_jedem_echten_mikrofon():
    """Kalibrierung in Zahlen festgehalten: Die real gemessenen Leerfaelle lagen
    bei RMS 0,0000–0,0001, ein leises Scarlett rauscht mit ~0,02. Wer die
    Schwelle anhebt, muss an dieser Stelle vorbei."""
    assert 0.0002 < KEIN_TON_SCHWELLE < 0.01
    assert KEIN_TON_AB_S >= 3.0        # nicht mitten in der Denkpause warnen
    assert KEIN_TON_FENSTER_S >= 5.0   # laenger als jede Sprechpause


def test_die_wache_laeuft_nicht_in_einem_eigenen_thread():
    """Sie haengt bewusst im vorhandenen GUI-Takt der Wellenlinie."""
    import inspect

    from fleech.ui.desktopapp import keinton

    quelle = inspect.getsource(keinton)
    assert "threading" not in quelle
    assert "QTimer" not in quelle


def test_rohpegel_kostet_kaum_zeit():
    """Die Wache laeuft 20-mal pro Sekunde — sie darf nichts kosten."""
    r = _recorder()
    for _ in range(400):
        r._callback(_block(0.05), 160, None, None)
    start = time.perf_counter()
    for _ in range(200):
        r.rohpegel_max(5.0)
    assert (time.perf_counter() - start) < 0.5
