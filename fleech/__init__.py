"""Fleech — lokale Diktat-Engine (Push-to-Talk → STT → LLM-Cleanup → Text-Injection)."""

from .portaudio_bootstrap import ensure_portaudio
from .version import APP_VERSION as __version__

# Muss vor dem ersten sounddevice-Import laufen (Linux ohne libportaudio2-Systempaket).
ensure_portaudio()

__all__ = ["__version__"]
