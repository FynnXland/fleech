"""--pipeline-selftest: Fixture-Handling und Statusauswertung (ohne echte Provider)."""

import wave
from pathlib import Path

import numpy as np

from fleech.config import load_config
from fleech.pipelinetest import run_pipeline_selftest


def _write_wav(path: Path, seconds: float = 1.0, sr: int = 16000) -> None:
    pcm = np.zeros(int(seconds * sr), dtype=np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def test_no_fixtures_found_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEECH_LLM_MODEL", "irrelevant")  # kein echter Call noetig
    cfg = load_config(tmp_path / "leer.yaml")
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert run_pipeline_selftest(cfg, str(empty_dir)) == 1


def test_missing_individual_fixtures_are_skipped(tmp_path, capsys):
    cfg = load_config(tmp_path / "leer.yaml")
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    # Nur eine Fixture vorhanden (zu kurzes Audio -> "too_short", kein Netzwerk noetig)
    _write_wav(fixtures / "diktat_de.wav", seconds=0.05)
    run_pipeline_selftest(cfg, str(fixtures))
    out = capsys.readouterr().out
    assert "diktat_de.wav" not in out or "uebersprungen" not in out  # vorhanden -> nicht uebersprungen
    assert "command_safeword.wav" in out and "uebersprungen" in out
    assert "math_quadratisch.wav" in out and "uebersprungen" in out
