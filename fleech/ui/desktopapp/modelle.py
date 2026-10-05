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

# Wie lange nach einem Spielende das Modell NICHT im Hintergrund zurueckgeholt
# wird. Fuenf Minuten: Im Log lagen 609 von 729 Neuladevorgaengen nach einem Spiel
# unter dieser Schwelle — genau die Alt-Tab-Pendelei. Wer diktiert, bekommt das
# Modell trotzdem sofort: Der Aufnahmestart laedt es parallel zum Sprechen vor.
SPIELPAUSE_S = 300

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
        from ..focusrestore import restore_focus_target, ziel_ist_vorn

        self.pipeline.injector.focus_restorer = restore_focus_target
        self.pipeline.injector.vordergrund_pruefer = ziel_ist_vorn
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
            # Aus der Konfiguration — bis 5.12.3 stand hier fest „small", und der
            # Takt aus `config.yaml` (interval_ms) erreichte die Desktop-App nie:
            # Sie dekodierte mit dem Standard von 0,5 s, 1,3-mal pro Sekunde
            # Aufnahme (20 818 Vorschau-Laeufe bei 454 Diktaten im Log).
            self._preview_model = PreviewModel(
                model_size=self.config.overlay.model_size,
                language=self.settings.general.language,
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
                    interval=max(0.3, self.config.overlay.interval_ms / 1000),
                    window_seconds=self.config.overlay.window_seconds,
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
        # Zweites Netz zum Stopp-Signal der Vorschau: Seit die Vorschau beim
        # Aufnahme-Ende nicht mehr gejoint wird, kann ein letzter Lauf knapp nach
        # dem Stopp noch Text liefern. Der gehoert nicht mehr in die Pille.
        if getattr(getattr(self, "bus", None), "state", AppState.LISTENING)                 is not AppState.LISTENING:
            return
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
        seit_spiel = time.monotonic() - getattr(self, "_spiel_ende", float("-inf"))
        if getattr(self, "_llms_unloaded", False) and seit_spiel < SPIELPAUSE_S:
            # Kurz aus dem Spiel getabbt ist kein Arbeitsbeginn. Das Modell bleibt
            # entladen; diktiert jemand, laedt der Aufnahmestart es vor.
            return
        threading.Thread(target=self._keep_llm_warm, daemon=True).start()

    def _llm_endpoints(self) -> list:
        models = {self.config.llm_cleanup.model: self.config.llm_cleanup}
        models.setdefault(self.config.llm_command.model, self.config.llm_command)
        # Der schnelle Endpunkt gehoert seit 5.11.0 fest dazu (Befund E-4: der
        # Schalter „Adaptive Geschwindigkeit" stand ohnehin bei jedem auf „an").
        # `setdefault` sorgt dafuer, dass daraus kein zweites Warmhalten wird,
        # solange `cleanup_fast` dasselbe Modell nennt wie `cleanup`.
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
            self._pruefe_ki_auf_grafikkarte(endpoints[0] if endpoints else None)
        except Exception:
            log.debug("Keep-Warm fehlgeschlagen.", exc_info=True)

    def _pruefe_ki_auf_grafikkarte(self, endpoint) -> None:
        """Warnen, wenn Ollama auf dem Prozessor rechnet, obwohl eine Grafikkarte da ist.

        Nur dann: Laeuft Whisper selbst auf der CPU, gibt es keine Grafikkarte zu
        finden, und die Meldung waere bloss Laerm. Einmal je Auftreten — kommt
        Ollama wieder auf die Grafikkarte, darf ein spaeterer Rueckfall erneut
        gemeldet werden."""
        from ...llm.client import ollama_auf_cpu

        if endpoint is None:
            return
        stt = getattr(getattr(self, "pipeline", None), "stt", None)
        if getattr(stt, "_on_cpu", True):
            return
        auf_cpu = ollama_auf_cpu(endpoint)
        if auf_cpu is False:
            self._ki_cpu_gemeldet = False
            return
        if not auf_cpu or getattr(self, "_ki_cpu_gemeldet", False):
            return
        self._ki_cpu_gemeldet = True
        log.warning("Ollama rechnet %s auf dem PROZESSOR, nicht auf der Grafikkarte — "
                    "jede Bereinigung dauert dadurch ein Vielfaches. Abhilfe: Ollama "
                    "neu starten.", endpoint.model)
        self.bus.hinweis.emit(
            "Die lokale KI rechnet gerade auf dem Prozessor statt auf der "
            "Grafikkarte — Diktate dauern dadurch 10–30 Sekunden. Abhilfe: Ollama "
            "im Infobereich beenden und neu starten.")

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
        # Nicht mitten in ein Diktat hinein entladen. Im Log lag das Entladen
        # siebenmal zwischen Spracherkennung und Bereinigung — die Bereinigung
        # musste das Modell dann neu laden (einmal 28 s, einmal Zeitueberschreitung).
        # Aufgeschoben, nicht verworfen: `_llms_unloaded` bleibt unveraendert,
        # der naechste Takt versucht es wieder.
        sperre = getattr(self, "_process_lock", None)
        zustand = getattr(getattr(self, "bus", None), "state", None)
        if (sperre is not None and sperre.locked()) or                 zustand in (AppState.LISTENING, AppState.PROCESSING):
            log.info("Entladen (%s) aufgeschoben — ein Diktat laeuft.", reason)
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

    def _wechsle_stt_modell(self) -> None:
        """Erkennungsmodell umstellen (Einstellung „Spracherkennung") — ohne Neustart.

        Fehlt das Modell, wird es zuerst geladen; bis dahin erkennt das bisherige
        weiter. Erst wenn das neue vollständig da ist, wird umgesteckt — ein
        abgebrochener Download hinterlässt nie eine Erkennung, die nicht startet.
        """
        from ... import provisioning
        from ...stt import create_stt
        from ...stt.modellwahl import modell_fuer

        ziel = modell_fuer(self.settings.advanced.stt_modell, self.config.stt.model_size)
        if ziel == self.config.stt.model_size:
            return
        name = "deutsche" if self.settings.advanced.stt_modell == "deutsch" else "allgemeine"

        def lauf():
            if not provisioning.whisper_present(ziel):
                self.bus.hinweis.emit(f"Lade {name} Spracherkennung (1,6 GB) …")
                if not provisioning.ensure_whisper(ziel, on_progress=log.info):
                    self.bus.hinweis.emit(
                        "Spracherkennung konnte nicht geladen werden — die bisherige "
                        "bleibt aktiv. Internetverbindung prüfen.")
                    return
            self.controller.stop_if_active()
            self.config.stt.model_size = ziel
            self.pipeline.stt = create_stt(self.config.stt)
            self._warm_up_stt()
            log.info("Erkennungsmodell gewechselt: %s", ziel)
            self.bus.hinweis.emit(f"Jetzt aktiv: {name} Spracherkennung.")

        threading.Thread(target=lauf, name="fleech-sttwechsel", daemon=True).start()
