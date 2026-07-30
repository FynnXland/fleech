"""Pause waehrend der Aufnahme: nichts sammeln, aber das Diktat nicht verlieren.

Der Zweck ist ein sozialer, kein technischer: mitten im Diktat spricht jemand
dazwischen. Danach muss dasselbe Diktat weitergehen — mit einer sauberen Naht.
"""

import numpy as np

from fleech.audio import _RESUME_GAP_S, Recorder


class _FakeStream:
    """Ersetzt den sounddevice-Stream: der Recorder soll ihn NICHT schliessen."""

    def __init__(self):
        self.stopped = False

    def start(self):
        pass

    def stop(self):
        self.stopped = True

    def close(self):
        pass


def _recorder(rate=16000):
    r = Recorder(samplerate=rate)
    r._stream = _FakeStream()
    r._capture_rate = rate
    return r


def _block(wert=0.5, n=160):
    return np.full((n, 1), wert, dtype=np.float32)


def test_pausierte_bloecke_landen_nicht_im_diktat():
    r = _recorder()
    r._callback(_block(0.5), 160, None, None)
    r.pause()
    for _ in range(10):                       # waehrend der Pause gesprochen
        r._callback(_block(0.9), 160, None, None)
    r.resume()
    r._callback(_block(0.5), 160, None, None)

    audio = r.stop()
    # 2 echte Bloecke + die Naht-Stille — nichts aus der Pause.
    erwartet = 320 + int(16000 * _RESUME_GAP_S)
    assert len(audio) == erwartet
    assert not np.any(np.isclose(audio, 0.9))


def test_naht_bekommt_eine_kurze_stille():
    """Ohne Stille klebt die Erkennung das letzte und das erste Wort zusammen."""
    r = _recorder()
    r._callback(_block(0.5), 160, None, None)
    r.pause()
    r.resume()
    r._callback(_block(0.5), 160, None, None)
    audio = r.stop()
    stille = audio[160:160 + int(16000 * _RESUME_GAP_S)]
    assert np.all(stille == 0.0)
    assert len(stille) > 1000                 # hoerbar, nicht nur ein paar Samples


def test_pegel_ruht_waehrend_der_pause():
    """Ein zappelnder Balken waehrend der Pause waere ein falsches Signal."""
    r = _recorder()
    r._callback(_block(0.9), 160, None, None)
    assert r.level > 0.5
    r.pause()
    r._callback(_block(0.9), 160, None, None)
    assert r.level == 0.0


def test_stream_bleibt_waehrend_der_pause_offen():
    """Schliessen und neu oeffnen kostet Zeit und kann das Geraet wechseln."""
    r = _recorder()
    r.pause()
    assert r.recording is True
    assert r._stream.stopped is False


def test_resume_ohne_pause_tut_nichts():
    r = _recorder()
    r._callback(_block(0.5), 160, None, None)
    r.resume()
    assert len(r.stop()) == 160               # keine Stille eingefuegt


def test_neue_aufnahme_beginnt_nie_pausiert(monkeypatch):
    r = Recorder()
    r._paused = True                          # Rest einer vorherigen Aufnahme

    class FakeSD:
        class PortAudioError(Exception):
            pass

        @staticmethod
        def InputStream(**kwargs):
            return _FakeStream()

    monkeypatch.setitem(__import__("sys").modules, "sounddevice", FakeSD)
    monkeypatch.setattr("fleech.audio.resolve_input_device", lambda d: None)
    r.start()
    assert r.paused is False


def test_stop_loest_die_pause():
    r = _recorder()
    r.pause()
    r.stop()
    assert r.paused is False
