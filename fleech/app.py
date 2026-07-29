"""App-Verdrahtung: globaler Push-to-Talk-Listener + Pipeline-Threads."""

from __future__ import annotations

import logging
import threading

from .audio import Recorder
from .audiofocus import (
    AudioFocusController, DeviceCheck, DeviceGuard, FocusMode, PlaybackDucker,
)
from .config import AppConfig
from .hotkey import keys_equal, parse_key
from .injection import TextInjector
from .llm import ChatClient
from .pipeline import Pipeline
from .prompts import load_command_prompt, load_prompt
from .stt import create_stt

log = logging.getLogger(__name__)


class DictationApp:
    def __init__(self, config: AppConfig):
        self.config = config
        self.recorder = Recorder(config.audio.samplerate, config.audio.device)
        self.pipeline = Pipeline(
            stt=create_stt(config.stt),
            cleanup_llm=ChatClient(config.llm_cleanup),
            injector=TextInjector(
                config.injection.restore_clipboard, config.injection.paste_delay_ms
            ),
            cleanup_prompt=load_prompt(config.prompts_dir, "cleanup"),
            trigger_word=config.command.trigger_word,
            command_llm=ChatClient(config.llm_command),
            command_prompt=load_command_prompt(
                config.prompts_dir, config.command.trigger_word
            ),
        )
        self.focus = self._build_focus_controller(config)
        self._dictate_key = parse_key(config.hotkey.dictate)
        self._active: str | None = None  # None | "dictate"

        # M4: Live-Overlay — additiver Best-Effort-Pfad, unabhaengig vom Commit-Pfad.
        self.overlay = None
        self.preview = None
        if config.overlay.enabled:
            try:
                from .overlay import OverlayWindow, PreviewModel, PreviewStreamer

                self.overlay = OverlayWindow()
                self._preview_model = PreviewModel(
                    config.overlay.model_size, config.stt.language, config.audio.samplerate
                )
                self.preview = PreviewStreamer(
                    snapshot_fn=self.recorder.snapshot,
                    transcribe_fn=self._preview_model.transcribe_segments,
                    on_text=self.overlay.set_text,
                    samplerate=config.audio.samplerate,
                    interval=config.overlay.interval_ms / 1000,
                    window_seconds=config.overlay.window_seconds,
                )
            except Exception:
                log.exception("Overlay-Setup fehlgeschlagen — Diktat laeuft ohne Vorschau.")
                self.overlay = None
                self.preview = None

    @staticmethod
    def _build_focus_controller(config: AppConfig) -> AudioFocusController:
        fc = config.audio_focus
        try:
            mode = FocusMode(fc.mode)
        except ValueError:
            log.warning("Unbekannter audio_focus.mode %r — nutze soft_duck.", fc.mode)
            mode = FocusMode.SOFT_DUCK

        try:
            check = DeviceGuard.check(config.audio.device, fc.blocked_devices)
        except Exception as exc:
            check = DeviceCheck(ok=True, name=f"<unbekannt: {exc}>")
        if not check.ok:
            log.error("⚠ Input-Geraet '%s': %s", check.name, check.reason)

        ducker = None
        if mode is not FocusMode.PURE_MIC:
            level = fc.hard_duck_level if mode is FocusMode.HARD_FOCUS else fc.duck_level
            try:
                ducker = PlaybackDucker(level, fc.fade_ms, fc.hard_mute)
            except Exception:
                log.exception("Ducker-Init fehlgeschlagen — Fokus-Modus ohne Ducking.")

        # Die Mikrofon-Pegel-Anhebung gab es nur fuer lange Formeldiktate ueber den
        # Cloud-Pfad; beides ist mit v3.0.0 entfallen.
        return AudioFocusController(mode, ducker, check)

    # -- Listener-Callbacks (muessen schnell zurueckkehren) --------------------

    def _on_press(self, key) -> None:
        if self._active is not None:  # Auto-Repeat beim Halten ignorieren
            return
        if keys_equal(key, self._dictate_key):
            self._begin("dictate")

    def _on_release(self, key) -> None:
        if self._active == "dictate" and keys_equal(key, self._dictate_key):
            self._finish()

    def _begin(self, mode: str) -> None:
        allowed, message = self.focus.may_record(math_mode=False)
        if not allowed:
            log.error(message)
            self._flash_overlay(f"⛔ {message}")
            return
        if message:
            log.warning(message)
        try:
            self.recorder.start()
        except Exception:
            log.exception("Mikrofon-Start fehlgeschlagen (audio.device pruefen, --list-devices).")
            return
        self._active = mode
        # Ducking/Mic-Pegel im Hintergrund (Fade blockiert sonst den Key-Listener).
        threading.Thread(target=self.focus.on_recording_start, daemon=True).start()
        if self.preview is not None:
            try:
                self.overlay.show()
                self.overlay.set_text(f"🎤 {self.focus.status_line()}")
            except Exception:
                log.exception("Overlay-Start fehlgeschlagen — Aufnahme laeuft weiter.")
            else:
                try:
                    self.preview.start()
                except Exception:
                    log.exception("Preview-Start fehlgeschlagen — Aufnahme laeuft weiter.")
        log.info("● Aufnahme laeuft (%s) — %s", mode, self.focus.status_line())

    def _flash_overlay(self, text: str, seconds: float = 3.0) -> None:
        if self.overlay is None:
            return
        try:
            self.overlay.show()
            self.overlay.set_text(text)
            threading.Timer(seconds, self.overlay.hide).start()
        except Exception:
            pass

    def _finish(self) -> None:
        self._active = None
        threading.Thread(target=self.focus.on_recording_stop, daemon=True).start()
        if self.preview is not None:
            try:
                self.preview.stop()
                self.overlay.hide()
            except Exception:
                log.exception("Overlay-Stopp fehlgeschlagen — Verarbeitung laeuft weiter.")
        audio = self.recorder.stop()
        log.info("■ Aufnahme beendet (%.1f s).", audio.size / self.config.audio.samplerate)
        threading.Thread(
            target=self.pipeline.process,
            args=(audio, self.config.audio.samplerate),
            daemon=True,
        ).start()

    # --------------------------------------------------------------------------

    def warm_up(self) -> None:
        """STT-Modell schon beim Start laden, nicht erst beim ersten Diktat."""
        import numpy as np

        try:
            self.pipeline.stt.transcribe(
                np.zeros(int(0.5 * 16000), dtype=np.float32), 16000
            )
            log.info("STT-Modell geladen und warm.")
        except Exception:
            log.exception("STT-Warm-up fehlgeschlagen.")
        if self.preview is not None:
            try:
                self._preview_model.load()
            except Exception:
                log.exception("Preview-Modell-Warm-up fehlgeschlagen — Vorschau ggf. verzoegert.")

    def run(self) -> None:
        from pynput import keyboard

        self.warm_up()
        log.info("Audio-Fokus: %s", self.focus.status_line())
        log.info(
            "Bereit. %s halten = diktieren | Strg+C beendet.",
            self.config.hotkey.dictate.upper(),
        )
        with keyboard.Listener(on_press=self._on_press, on_release=self._on_release) as listener:
            listener.join()
