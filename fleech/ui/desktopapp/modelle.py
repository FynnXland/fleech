"""Modelle: bauen, warmhalten, entladen — und die Live-Vorschau.

Der teuerste Teil des Starts und der einzige, der im Leerlauf weiterarbeitet.
Warmhalten spart den ~8 s Kaltstart, kostet aber VRAM; deshalb der
Smart-Modus mit Leerlauf-Fenster (`_idle_unload_window_s`) und das
sofortige Entladen, sobald ein Spiel im Vordergrund steht.

Mixin statt eigener Klasse: Der Zustand (settings, overlay, pipeline, recorder)
liegt weiter auf EINEM Objekt. Ein eigenes Controller-Objekt haette neue
Referenzen in den Qt-Objektgraphen gelegt — genau die Konstellation, die in
diesem Projekt schon zu GC-Reihenfolge-Abstuerzen gefuehrt hat.
"""

from __future__ import annotations

import logging
import threading
import time

from ...app import DictationApp
from ...audio import Recorder
from ...pipeline_factory import build_pipeline
from ..state import AppState, StateBus

log = logging.getLogger(__name__)

class ModelleMixin:
    def _build_engine(self) -> None:
        cfg = self.config
        s = self.settings
        self.recorder = Recorder(cfg.audio.samplerate, cfg.audio.device)
        # Faellt das gewaehlte Mikrofon weg, wird still der Systemstandard genommen —
        # das muss sichtbar werden (Befund B-7).
        self.recorder.on_device_fallback = self._melde_mikrofon_rueckfall
        # status: laengere Zwischenschritte gehen ueber den Bus an die Pille
        # (thread-sicher via Queued Connection — der Aufruf kommt aus dem Worker).
        self.pipeline = build_pipeline(cfg, s, status=self.bus.progress.emit)
        # Rohtranskript direkt in die Pille — der Weg ueber den Bus ist Pflicht,
        # die Pipeline laeuft im Worker-Thread.
        self.pipeline.raw_callback = self.bus.raw_ready.emit
        # Cursor-Rueckkehr: Restorer in den Injector einhaengen (plattformabhaengig,
        # damit injection.py portabel bleibt). Das Ziel-Feld wird pro Aufnahme gesetzt.
        from ..focusrestore import restore_focus_target

        self.pipeline.injector.focus_restorer = restore_focus_target
        self.focus = DictationApp._build_focus_controller(cfg)

    def _warm_up(self) -> None:
        import numpy as np

        try:
            self.pipeline.stt.transcribe(np.zeros(8000, dtype=np.float32), 16000)
            log.info("STT warm. %s", self.focus.status_line())
        except Exception:
            log.exception("STT-Warm-up fehlgeschlagen.")

    def _warm_up_stt(self) -> None:
        import numpy as np

        try:
            self.pipeline.stt.transcribe(np.zeros(8000, dtype=np.float32), 16000)
            log.info("STT neu geladen (device=%s) und warm.", self.config.stt.device)
        except Exception:
            log.exception("STT-Neuladen fehlgeschlagen.")

    def _warm_up_after_setup(self) -> None:
        """Nach erfolgreicher Kaltstart-Einrichtung sofort aufwaermen.

        Beim allerersten Start lief der Warm-up ins Leere (Modelle fehlten noch).
        Ohne diesen Nachzieher waere das erste Diktat trotz fertiger Einrichtung
        das langsamste — Whisper und Ollama laden erst beim Zugriff."""
        threading.Thread(target=self._warm_up, daemon=True).start()
        self._keep_warm_tick()

    def _ensure_preview_model(self):
        from ...overlay import PreviewModel

        if self._preview_model is None:
            self._preview_model = PreviewModel(
                model_size="small", language=self.settings.general.language,
                samplerate=self.config.audio.samplerate,
            )
        try:
            self._preview_model.load()
        except Exception:
            log.exception("Preview-Modell konnte nicht geladen werden.")
        return self._preview_model

    def _start_preview_async(self) -> None:
        self._preview_gen += 1
        gen = self._preview_gen

        def worker():
            from ...overlay import PreviewStreamer

            model = self._ensure_preview_model()
            if self._preview is None:
                self._preview = PreviewStreamer(
                    snapshot_fn=self._laufendes_audio,
                    transcribe_fn=model.transcribe_segments,
                    on_text=self.bus.preview_text.emit,  # Signal = thread-sicher zur UI
                    samplerate=self.config.audio.samplerate,
                )
            # Aufnahme koennte waehrend des Modell-Ladens schon beendet worden sein.
            if gen == self._preview_gen and self.bus.state is AppState.LISTENING:
                self._preview.start()

        threading.Thread(target=worker, daemon=True).start()

    def _stop_preview(self) -> None:
        self._preview_gen += 1  # entwertet einen evtl. noch laufenden Start-Worker
        if self._preview is not None:
            self._preview.stop()

    def _on_preview_text(self, text: str) -> None:
        """Live-Vorschau anzeigen + Signalwort-Erkennung: faellt das Safe-Word,
        faerbt sich die Pille (sichtbares "Befehl erkannt")."""
        self.overlay.show_live_text(text)
        trigger = (self.pipeline.trigger_word or "").lower()
        if trigger and trigger in (text or "").lower():
            self.overlay.set_command_armed(True)

    def _idle_unload_window_s(self) -> float:
        return max(0, int(self.settings.advanced.llm_idle_unload_minutes)) * 60

    def _keep_warm_tick(self) -> None:
        mode = self.settings.advanced.llm_keep_warm
        if mode == "off":
            return
        gaming = False
        try:
            gaming = self.notifier.policy.gaming_active(self.notifier.context)
        except Exception:
            log.debug("Gaming-Check fuer Keep-Warm fehlgeschlagen.", exc_info=True)
        idle = time.monotonic() - self._last_dictation > self._idle_unload_window_s()
        if mode == "smart" and (gaming or idle):
            self._unload_llms_async("Spiel erkannt" if gaming else "Leerlauf")
            return
        threading.Thread(target=self._keep_llm_warm, daemon=True).start()

    def _llm_endpoints(self) -> list:
        models = {self.config.llm_cleanup.model: self.config.llm_cleanup}
        models.setdefault(self.config.llm_command.model, self.config.llm_command)
        if self.settings.advanced.adaptive_cleanup:
            models.setdefault(
                self.config.llm_cleanup_fast.model, self.config.llm_cleanup_fast
            )
        return list(models.values())

    def _keep_llm_warm(self) -> None:
        from ...llm.client import ensure_ollama_models, ollama_preload

        try:
            # Fehlt das Sprachmodell (frische Installation, Modell umkonfiguriert),
            # holt Fleech es selbst — sonst scheitert das erste Diktat mit einer
            # Fehlermeldung, die nur weiterhilft, wenn man Ollama kennt.
            endpoints = self._llm_endpoints()
            ensure_ollama_models(endpoints, on_progress=self._report_model_download)
            for endpoint in endpoints:
                ollama_preload(endpoint)
            self._llms_unloaded = False  # wieder warm → naechstes Entladen erlaubt
        except Exception:
            log.debug("Keep-Warm fehlgeschlagen.", exc_info=True)

    def _report_model_download(self, text: str) -> None:
        """Download-Fortschritt sichtbar machen — mehrere GB duerfen nicht wie eine
        eingefrorene App aussehen. Laeuft im Worker-Thread → nur ueber den StateBus."""
        try:
            self.bus.progress.emit(text)
        except Exception:
            log.debug("Fortschrittsmeldung fehlgeschlagen.", exc_info=True)

    def _melde_ki_offline(self) -> None:
        """Einmal je Sitzung sagen, dass die lokale KI gar nicht laeuft (Befund E-13).

        Wer die Einfuehrung ueberspringt, ueberspringt die Einrichtung von Ollama.
        Danach kommt jedes Diktat als Roh-Transkript an — sichtbar nur als
        „eingefügt (Fallback — Log prüfen)". Der Weg zurueck (Einstellungen →
        Allgemein → „Einführung erneut zeigen") stand nirgends.

        Nur ueber die Pille, nicht per Toast: Der Aufruf kommt aus dem
        Verarbeitungs-Thread, und der StateBus ist der einzige thread-sichere Weg
        zur Oberflaeche.
        """
        if getattr(self, "_ki_offline_gemeldet", False):
            return
        self._ki_offline_gemeldet = True
        text = ("Lokale KI läuft nicht — Einstellungen → Allgemein → "
                "„Einführung erneut zeigen“")
        log.error("%s", text)
        try:
            self.bus.progress.emit(text)
        except Exception:
            log.debug("Hinweis auf die fehlende lokale KI nicht zustellbar.",
                      exc_info=True)

    def _unload_llms_async(self, reason: str) -> None:
        """Alle lokalen Ollama-Modelle SOFORT entladen (RAM/VRAM frei) — idempotent:
        nach einem Entladen passiert bis zum naechsten Aufwaermen nichts mehr (kein
        Request-Spam alle 4 min gegen ein ohnehin leeres Ollama)."""
        if getattr(self, "_llms_unloaded", False):
            return
        self._llms_unloaded = True
        from ...llm.client import ollama_unload

        def work():
            try:
                log.info("LLM-Modelle entladen (%s) — RAM/VRAM wird freigegeben.", reason)
                for endpoint in self._llm_endpoints():
                    ollama_unload(endpoint)
            except Exception:
                log.debug("LLM-Entladen fehlgeschlagen.", exc_info=True)

        threading.Thread(target=work, daemon=True).start()
