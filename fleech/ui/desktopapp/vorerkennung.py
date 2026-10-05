"""Abschnitte schon während der Aufnahme erkennen — die Verdrahtung.

Die Logik steht in `fleech/stt/abschnitte.py`; hier nur, wann der Erkenner
startet, stoppt und sein Ergebnis abgibt. Drei Zeitpunkte, drei Threads:

- Drücken (Tastatur-Hook): Erkenner anlegen. Profil, Sprache und Priming
  bestimmt ein eigener Thread — das Priming fragt das Projekt-Gedächtnis ab,
  und der Hook darf nicht warten (Windows entfernt langsame Hooks still).
- Loslassen (Hook): nur das Stopp-Signal, nie warten.
- Verarbeitung (Worker): auf den Abschnitt in Arbeit warten, Ergebnis abholen.

Nur für Diktate per Taste. Freihand und „neu bereinigen" erkennen weiter am
Stück — dort gibt es keinen laufenden Recorder bzw. kein Sprechen mehr.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


def abschnitte_ergebnis(erkenner):
    """Im Worker: was schon erkannt ist — oder None (dann am Stück).

    Eine Funktion statt einer Methode: `_process_locked` wird in Tests auf
    schlichten Attrappen aufgerufen, die keine Mixin-Methoden haben."""
    if erkenner is None:
        return None
    try:
        return erkenner.ergebnis()
    except Exception:
        log.exception("Abschnitte nicht abholbar — am Stück.")
        return None


def uebergib_abschnitte(app):
    """Beim Loslassen: Erkenner stoppen und an die Verarbeitung weiterreichen.

    Nicht blockierend. Ebenfalls Funktion statt Methode — siehe oben."""
    erkenner = getattr(app, "_abschnitte", None)
    app._abschnitte = None
    if erkenner is not None:
        erkenner.beende()
    return erkenner


def verwirf_abschnitte(app) -> None:
    uebergib_abschnitte(app)


class VorerkennungMixin:
    def _starte_abschnitte(self) -> None:
        self._abschnitte = None
        stt = getattr(getattr(self, "pipeline", None), "stt", None)
        config = getattr(self, "config", None)
        if (not getattr(getattr(config, "stt", None), "abschnitte", False)
                or not hasattr(stt, "transcribe_abschnitt")
                or getattr(stt, "_on_cpu", False)
                or getattr(getattr(config, "audio", None), "samplerate", 0) != 16000):
            return
        from ...stt.abschnitte import AbschnittsErkenner, silero_vad

        erkenner = AbschnittsErkenner(
            snapshot=self.recorder.snapshot,
            erkenne=stt.transcribe_abschnitt,
            vad=silero_vad,
            samplerate=self.config.audio.samplerate,
        )
        self._abschnitte = erkenner

        def vorbereiten():
            try:
                prof = self._app_profile_overrides()
                # Genau wie `_setze_sprache`: "auto" heisst für Whisper leer.
                sprache = (prof.sprache or self.settings.general.language
                           or "de").lower()
                sprache = "" if sprache == "auto" else sprache
                hinweis = self.pipeline.stt_hinweis(
                    getattr(self, "_record_app", ""),
                    getattr(self, "_record_title", ""),
                    not prof.command_allowed(self.settings.output.command_enabled),
                )
                erkenner.start(hinweis, sprache)
            except Exception:
                log.exception("Abschnitts-Erkennung nicht gestartet — am Stück.")

        threading.Thread(target=vorbereiten, name="fleech-abschnitte-start",
                         daemon=True).start()
