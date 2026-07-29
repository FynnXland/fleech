"""Segment-Filter gegen Musik/Geraeusch im Mikrofon.

Braucht KEIN echtes Whisper-Modell (anders als test_stt_integration.py) — die
Segmente werden vorgegeben, geprueft wird allein die Filter-Entscheidung.
"""


class _Seg:
    def __init__(self, text, no_speech_prob):
        self.text = text
        self.no_speech_prob = no_speech_prob


def _stt_mit_segmenten(segmente):
    """FasterWhisperSTT mit vorgegebenen Segmenten — ohne echtes Modell."""
    import types

    from fleech.stt.faster_whisper_stt import FasterWhisperSTT

    stt = FasterWhisperSTT(types.SimpleNamespace(
        language="de", vad_filter=True, model_size="x", device="cpu", compute_type="int8"))
    stt._model = types.SimpleNamespace(
        transcribe=lambda *a, **k: (iter(segmente), None))
    return stt


def test_musik_segmente_werden_verworfen():
    """Der reale Anlass: Spotify laeuft, das Mikrofon hoert es mit, Whisper macht
    daraus mehrsprachigen Wortsalat. Whisper markiert solche Segmente selbst mit
    hoher `no_speech_prob` — der eingebaute Filter verwirft sie aber nur, wenn die
    Erkennung ZUSAETZLICH unsicher ist, und davon ist das Modell hier oft ueberzeugt.
    """
    import numpy as np

    stt = _stt_mit_segmenten([
        _Seg("Analysiere bitte das Plugin.", 0.02),
        _Seg("Und so weiter und so fort.", 0.11),
        _Seg("Denn Sie ладно, da sind schon mal ein bisschen más schnell.", 0.94),
    ])
    text = stt._run(np.zeros(16000, dtype=np.float32))

    assert "Analysiere bitte das Plugin." in text
    assert "Und so weiter und so fort." in text
    assert "ладно" not in text


def test_echte_sprache_wird_nie_verschluckt():
    """Die Gegenprobe ist die wichtigere: Ein verschlucktes Wort waere schlimmer als
    ein Musikfetzen zu viel — den faengt danach der Fremdschrift-Guard."""
    import numpy as np

    # Auch unsicher erkannte, aber echte Sprache (leise gesprochen, genuschelt)
    # liegt deutlich unter der Schwelle.
    stt = _stt_mit_segmenten([
        _Seg("Das erste Stück.", 0.0),
        _Seg("Undeutlich genuschelt hier.", 0.45),
        _Seg("Ganz leise gesprochen.", 0.79),
    ])
    text = stt._run(np.zeros(16000, dtype=np.float32))

    assert "Das erste Stück." in text
    assert "Undeutlich genuschelt hier." in text
    assert "Ganz leise gesprochen." in text     # 0.79 < 0.8 → bleibt


def test_fehlendes_attribut_bricht_nichts():
    """Aeltere/andere faster-whisper-Versionen liefern das Feld womoeglich nicht —
    dann wird NICHT gefiltert, statt alles zu verwerfen."""
    import numpy as np
    import types

    stt = _stt_mit_segmenten([types.SimpleNamespace(text="Ohne Attribut.")])
    assert stt._run(np.zeros(16000, dtype=np.float32)) == "Ohne Attribut."
