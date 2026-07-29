"""Tests fuer die Streaming-Logik (ohne Tk, ohne Modell, ohne Mikrofon)."""

import numpy as np

from fleech.overlay import PreviewSegment, PreviewStreamer

SR = 16000


def seconds(n: float) -> np.ndarray:
    return np.zeros(int(n * SR), dtype=np.float32)


def make_streamer(snapshot_fn, transcribe_fn, texts, **kwargs):
    # Stille-Gate default AUS: die Fixtures hier sind Null-Audio (RMS 0) und testen
    # die Fenster-Logik, nicht das Gate (das hat eigene Tests weiter unten).
    kwargs.setdefault("silence_rms", 0.0)
    return PreviewStreamer(
        snapshot_fn=snapshot_fn,
        transcribe_fn=transcribe_fn,
        on_text=texts.append,
        samplerate=SR,
        **kwargs,
    )


def test_short_audio_emits_nothing():
    texts = []
    s = make_streamer(lambda: seconds(0.3), lambda w: [], texts)
    s._tick()
    assert texts == []


def test_hypothesis_is_emitted():
    texts = []
    s = make_streamer(
        lambda: seconds(3),
        lambda w: [PreviewSegment("hallo welt", 0.0, 2.5)],
        texts,
    )
    s._tick()
    assert texts == ["hallo welt"]


def test_growing_audio_updates_text():
    texts = []
    audio_holder = {"a": seconds(2)}
    hypotheses = iter([
        [PreviewSegment("das projekt", 0.0, 1.8)],
        [PreviewSegment("das projekt läuft gut", 0.0, 3.6)],
    ])
    s = make_streamer(lambda: audio_holder["a"], lambda w: next(hypotheses), texts)
    s._tick()
    audio_holder["a"] = seconds(4)
    s._tick()
    assert texts == ["das projekt", "das projekt läuft gut"]


def test_sliding_window_freezes_old_segments():
    texts = []
    calls = []

    def transcribe(window):
        calls.append(window.size / SR)
        # 16 s Fenster: zwei alte Segmente + ein aktuelles am Ende
        return [
            PreviewSegment("erster teil", 0.0, 5.0),
            PreviewSegment("zweiter teil", 5.0, 10.0),
            PreviewSegment("aktueller rest", 10.5, 15.5),
        ]

    s = make_streamer(
        lambda: seconds(16), transcribe, texts,
        window_seconds=12.0, freeze_margin_seconds=4.0,
    )
    s._tick()
    # Segmente mit Ende <= 16-4=12 s werden eingefroren, Fenster rueckt auf 10 s vor.
    assert texts == ["erster teil zweiter teil aktueller rest"]
    assert s._frozen == "erster teil zweiter teil"
    assert s._window_start == 10.0

    # Naechster Tick dekodiert nur noch das Rest-Fenster (16-10=6 s) …
    def transcribe2(window):
        calls.append(window.size / SR)
        return [PreviewSegment("aktueller rest geht weiter", 0.5, 5.9)]

    s.transcribe_fn = transcribe2
    s._tick()
    assert calls[-1] == 6.0
    # … und eingefrorener Text bleibt vorangestellt.
    assert texts[-1] == "erster teil zweiter teil aktueller rest geht weiter"


def test_tick_errors_do_not_leak(caplog):
    def boom():
        raise RuntimeError("kaputt")

    s = make_streamer(boom, lambda w: [], [])
    s._loop_once_for_test = s._tick  # nur zur Doku: _loop faengt Exceptions
    # _loop schluckt den Fehler (Best-Effort) — direkt pruefen:
    s._stop.set()
    s._loop()  # darf nicht raisen


def test_silence_gate_skips_decoding():
    """Ohne echtes Sprachsignal darf kein Dekodierlauf starten (Whisper wuerde bei
    Stille Phantomtexte halluzinieren — das Preview-Modell laeuft ohne VAD)."""
    calls = []
    texts = []
    s = PreviewStreamer(
        snapshot_fn=lambda: seconds(3),          # Null-Audio = Stille
        transcribe_fn=lambda w: calls.append(1) or [],
        on_text=texts.append,
        samplerate=SR,
    )  # Default-Gate aktiv
    s._tick()
    assert calls == [] and texts == []           # kein Dekodierlauf, kein Text

    # Echtes Signal (RMS ueber der Schwelle) → Dekodierung laeuft.
    loud = np.full(3 * SR, 0.05, dtype=np.float32)
    s.snapshot_fn = lambda: loud
    s._tick()
    assert calls == [1]


def test_start_resets_state():
    texts = []
    s = make_streamer(lambda: seconds(0.1), lambda w: [], texts)
    s._frozen = "alt"
    s._window_start = 7.5
    s.start()
    s.stop()
    assert s._frozen == ""
    assert s._window_start == 0.0


# -- Auto-Gain der Waveform (v2.2.0) ----------------------------------------------

def _wave():
    """WaveformWidget ohne Qt-Parent — nur die Skalierungslogik wird geprueft."""
    from fleech.ui.overlay_qt import WaveformWidget

    w = WaveformWidget.__new__(WaveformWidget)   # kein QWidget-Init noetig
    w._peak = 0.0
    return w


def test_leises_mikro_schlaegt_sichtbar_aus():
    """Der gemeldete Fall: RMS um 0,02 ergab mit festem Faktor 7 kaum Ausschlag."""
    w = _wave()
    quiet = 0.02
    for _ in range(30):                       # Anzeige laeuft sich ein
        value = w._scaled(quiet, 1.0)
    assert value > 0.4, f"immer noch zu klein: {value}"


def test_lautes_mikro_uebersteuert_nicht():
    w = _wave()
    for _ in range(30):
        value = w._scaled(0.45, 1.0)
    assert value <= 1.0 and value > 0.5


def test_stille_wird_nicht_hochverstaerkt():
    """Ohne Untergrenze wuerde Rauschen auf Vollausschlag skaliert."""
    w = _wave()
    for _ in range(50):
        value = w._scaled(0.0008, 1.0)
    assert value < 0.15, f"Stille zappelt: {value}"


def test_nutzer_gain_wirkt_weiterhin():
    w1, w2 = _wave(), _wave()
    for _ in range(30):
        a = w1._scaled(0.05, 1.0)
        b = w2._scaled(0.05, 2.0)
    assert b > a


def test_spitzenwert_faellt_wieder():
    """Nach einem lauten Wort darf die Anzeige nicht dauerhaft klein bleiben."""
    w = _wave()
    w._scaled(0.5, 1.0)                       # ein lauter Ausschlag
    loud_peak = w._peak
    for _ in range(200):                      # danach normale Lautstaerke
        w._scaled(0.03, 1.0)
    assert w._peak < loud_peak
