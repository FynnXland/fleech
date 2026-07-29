from .base import STTEngine


def create_stt(cfg) -> STTEngine:
    """Baut das konfigurierte STT-Backend (stt.backend in config.yaml).

    Seit v3.6.0 gibt es nur noch den lokalen Weg — der Groq-Cloud-Fallback ist
    entfallen. Eine alte `config.yaml` mit `backend: groq` laeuft trotzdem weiter,
    statt den Start zu verweigern; sie bekommt lokale Erkennung und einen Hinweis.
    """
    if cfg.backend and cfg.backend != "faster_whisper":
        import logging

        logging.getLogger(__name__).warning(
            "STT-Backend %r gibt es nicht mehr (nur noch lokal) — nutze faster_whisper.",
            cfg.backend,
        )
    from .faster_whisper_stt import FasterWhisperSTT

    return FasterWhisperSTT(cfg)
