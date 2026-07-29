"""Echter faster-whisper-Lauf auf einer TTS-Fixture-Datei.

Laeuft nur, wenn FLEECH_STT_TEST=1 gesetzt ist (laedt beim ersten Mal das
Whisper-Modell herunter). Fixture erzeugen mit: pwsh tests/fixtures/make_fixture.ps1
"""

import os
import wave
from pathlib import Path

import numpy as np
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "diktat_de.wav"

pytestmark = pytest.mark.skipif(
    os.environ.get("FLEECH_STT_TEST") != "1",
    reason="FLEECH_STT_TEST=1 setzen, um den echten STT-Lauf zu aktivieren",
)


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        assert wav.getsampwidth() == 2 and wav.getnchannels() == 1
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        return pcm.astype(np.float32) / 32768.0, wav.getframerate()


def test_faster_whisper_transcribes_fixture():
    if not FIXTURE.is_file():
        pytest.skip("Fixture fehlt — erst make_fixture.ps1 ausfuehren")

    from fleech.config import STTConfig
    from fleech.stt.faster_whisper_stt import FasterWhisperSTT

    cfg = STTConfig(model_size=os.environ.get("FLEECH_STT_TEST_MODEL", "base"))
    audio, samplerate = load_wav(FIXTURE)
    text = FasterWhisperSTT(cfg).transcribe(audio, samplerate).lower()

    # TTS→STT-Roundtrip ist nie perfekt; Kernwoerter reichen als Beleg.
    assert "projekt" in text
    assert "zeitplan" in text

