"""Gemeinsame STT-Schnittstelle, damit Backends austauschbar bleiben."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class STTEngine(ABC):
    @abstractmethod
    def transcribe(
        self, audio: np.ndarray, samplerate: int, initial_prompt: str | None = None
    ) -> str:
        """Mono-float32-Audio → Roh-Transkript (leer, wenn nichts erkannt).

        initial_prompt: optionaler Vokabular-Hinweis (z. B. Mathe-Grenzwoerter im
        Math-Focus), von Backends ohne Prompt-Support ignorierbar.
        """


def resample_to_16k(audio: np.ndarray, samplerate: int) -> np.ndarray:
    """Whisper erwartet 16 kHz; lineare Interpolation reicht fuer Sprache."""
    if samplerate == 16000 or audio.size == 0:
        return audio
    target_len = int(round(audio.size * 16000 / samplerate))
    x_old = np.linspace(0.0, 1.0, num=audio.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)
