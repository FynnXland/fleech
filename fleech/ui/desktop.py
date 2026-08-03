"""DesktopApp: verdrahtet Engine (Recorder/Pipeline/Fokus/Preview) mit der Qt-UI.

Thread-Modell:
- Qt-Main-Thread: Tray, Overlay, Settings-Fenster.
- pynput-Listener-Thread: uebersetzt Hotkeys via RecordingController in start/stop.
- Worker-Threads: Pipeline-Verarbeitung, Ducking-Fades, Preview-Streamer.
Alle UI-Updates laufen ueber StateBus-Signale (Queued Connections, thread-sicher).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ..app import DictationApp
from ..audio import Recorder
from ..config import load_config
from ..hotkey import HotkeyManager, HotkeySpec
from ..pipeline_factory import build_pipeline
from ..recording_control import RecordingController
from ..stt import create_stt
from ..usersettings import APP_STANDARD, UserSettings
from ..history import DictationRecord, HistoryStore
from .main_window import MainWindow
from .notifications import NotificationPolicy, Notifier
from .overlay_qt import OverlayWindow
from .sounds import SoundPlayer
from .state import AppState, StateBus
from .settings_window import SettingsPanel
from .tray import TrayController
from .windowsfocus import FocusProbe

log = logging.getLogger(__name__)

# Ab dieser Haltedauer gilt der Profil-Hotkey als „gehalten" und oeffnet die
# Auswahlliste. 350 ms: lang genug, dass ein zuegiger Tipp nie versehentlich die
# Liste oeffnet, kurz genug, dass Halten sich nicht wie Warten anfuehlt.
_PROFIL_HALTEN_MS = 350


def list_input_devices() -> list[str]:
    # Linux: echte Mikrofone von PipeWire listen (rohe ALSA-hw-Geraete sind dort
    # exklusiv belegt und wuerden nur tote Auswahl-Eintraege erzeugen).
    if sys.platform.startswith("linux"):
        try:
            from ..audio import list_pulse_sources

            return list_pulse_sources()
        except Exception:
            log.exception("PipeWire-Quellen nicht abfragbar — falle auf sounddevice zurueck.")
    try:
        import sounddevice as sd

        names = []
        for dev in sd.query_devices():
            if dev["max_input_channels"] > 0 and dev["name"] not in names:
                names.append(dev["name"])
        return names
    except Exception:
        log.exception("Audio-Geraete nicht abfragbar.")
        return []


def overrides_from(item: dict):
    """Profil-Eintrag → ProfileOverrides.

    Modul-Funktion statt Methode: die Umwandlung braucht kein App-Objekt, und die
    Profil-Tests bauen die App als schlankes Fake nach — eine Methode mehr waere
    dort jedes Mal eine Zeile Attrappe.
    """
    from ..usersettings import ProfileOverrides, profile_command_mode, profile_mode

    mode = str(item.get("intervention", "")).lower()
    tags = [str(t).strip() for t in item.get("tags", []) if str(t).strip()]
    return ProfileOverrides(
        intervention=mode if mode in ("minimal", "standard", "strong") else None,
        style_hints=tags or None,
        mode_slot=profile_mode(item),
        command=profile_command_mode(item),
        auto_send=bool(item.get("auto_send", False)),
    )


class DesktopApp:
    def __init__(self):
        self.settings = UserSettings.load()
        self.config = load_config()
        # Basiswert VOR apply_to merken: leeres Settings-Feld = zurueck zu config.yaml.
        self._base_trigger_word = self.config.command.trigger_word
        self.settings.apply_to(self.config)

        self.bus = StateBus()
        self.sounds = SoundPlayer(self.settings.sounds)
        self._build_engine()

        # UI — Overlay ist die Wispr-Stil-Pille: X (verwerfen), Waveform, ✓ (fertig).
        self.overlay = OverlayWindow(
            self.settings.overlay,
            on_geometry_changed=self.settings.save,
            level_provider=lambda: self.recorder.level,  # late-bound (Mic-Wechsel!)
        )
        self.overlay.cancel_requested.connect(self._cancel_recording)
        self.overlay.finish_requested.connect(lambda: self.controller.stop_if_active())
        self.overlay.pause_requested.connect(self.toggle_pause)
        # Modus-Punkt-Klick: KI-Prompting an/aus.
        self.overlay.profile_cycle_requested.connect(self.cycle_profile)
        self.tray = TrayController({
            "toggle_recording": lambda: self.controller.start_via_ui("dictate"),
            "toggle_overlay": self._toggle_overlay,
            "toggle_freihand": self.toggle_freihand,
            "open_home": lambda: self.window.open_page("home"),
            "open_settings": self._open_settings,
            "reload": self._reload,
            "quit": self._quit,
            "open_update": self.show_update_dialog,
        })
        self.store = HistoryStore()
        self.panel = panel = SettingsPanel(
            self.settings, self._on_setting_changed, list_input_devices,
            test_hooks={
                "toast": lambda: self.notifier.toast(
                    "background_info", "Fleech", "Test-Toast — Kanal funktioniert.",
                    bypass_cooldown=True,
                ),
                "sound": lambda: self.notifier.sound("commit"),
                "open_update": self.show_update_dialog,
                "open_license": self.show_license_dialog,
            },
            # Globale Hotkeys waehrend der Recorder-Erfassung pausieren (lazy —
            # self.hotkeys existiert erst spaeter im __init__).
            hotkey_capture_guard=(
                lambda: self.hotkeys.stop(),
                lambda: self.hotkeys.start(),
            ),
            on_clear_history=self._clear_history,
            overlay_hooks={
                "edit_toggle": self._toggle_overlay_edit,
                "reset": self._reset_overlay,
                "apply_preset": self._apply_overlay_preset,
            },
        )
        self.window = MainWindow(
            self.settings, self.store, panel, self._on_window_closed_to_tray,
            on_reprocess=self._reprocess_entry,
        )
        self.bus.history_changed.connect(self.window.refresh_data)

        self.bus.state_changed.connect(self.tray.set_state)
        self.bus.state_changed.connect(self.overlay.set_app_state)
        self.bus.command_armed.connect(self.overlay.set_command_armed)
        self.bus.feedback.connect(self.overlay.set_feedback)
        # Reihenfolge wichtig: der Fallback-Hinweis muss VOR transcript_ready
        # ankommen, damit die Blase schon amber gerahmt erscheint.
        self.bus.progress.connect(self.overlay.show_progress)
        self.bus.formula_preview.connect(self.overlay.show_formula_preview)
        self.bus.tail_dropped.connect(self.overlay.show_dropped_tail)
        self.bus.injection_fallback.connect(self.overlay.flash_fallback)
        self.bus.transcript_ready.connect(self.overlay.show_transcript)
        self.bus.raw_ready.connect(self.overlay.show_raw_preview)
        self.bus.reprocessed.connect(self._on_reprocessed)
        self.bus.freihand_ereignis.connect(self._on_freihand)
        self.bus.freihand_zustand.connect(self.overlay.set_freihand)
        self.bus.preview_text.connect(self._on_preview_text)
        self.bus.dictionary_suggestion.connect(self._on_dictionary_suggestion)
        self.bus.update_ready.connect(self._on_update_ready)
        self.bus.profile_key.connect(self._on_profile_key)
        self.bus.license_needed.connect(self.show_license_dialog)
        self.bus.paused_changed.connect(self.overlay.set_paused)
        # Live-Vorschau (Opt-in): kleines separates Whisper-Modell + Streamer, beide
        # lazy — wer das Feature nie einschaltet, zahlt keinerlei Kosten.
        self._preview_model = None
        self._preview = None
        if self.settings.overlay.live_preview:
            threading.Thread(target=self._ensure_preview_model, daemon=True).start()
        self._update_mode_line()

        # Windows Focus & Notifications: Policy + Poll-Timer (3 s, billige Win32-Calls).
        self.notifier = Notifier(
            NotificationPolicy(self.settings.focus), self.tray, self.sounds, FocusProbe()
        )
        # WICHTIG: alle Zustaende, die _poll_focus (Gaming-Flanke → Entladen/Aufwaermen)
        # anfasst, MUESSEN vor dem ersten Poll unten stehen — der laeuft noch im
        # Konstruktor (real abgestuerzt: AttributeError _was_gaming beim App-Start).
        self._llms_unloaded = False   # LLMs aktiv entladen (Gaming/Smart-Fenster)
        self._was_gaming = False      # Flanken-Erkennung Spielstart/-ende (Fokus-Poll)
        # Haelt ueberlappende Diktat-Verarbeitungen auseinander (siehe _process).
        self._process_lock = threading.Lock()
        self._last_dictation = time.monotonic()  # App-Start zaehlt als Aktivitaet
        from PySide6.QtCore import QTimer

        self._focus_timer = QTimer()
        self._focus_timer.setInterval(3000)
        self._focus_timer.timeout.connect(self._poll_focus)
        self._focus_timer.start()
        self._poll_focus()

        # Hotkeys (Einzeltasten + Kombinationen via HotkeyManager)
        self.controller = RecordingController(
            self.settings.recording.mode, self._on_record_start, self._on_record_stop
        )
        self._prompt_latched = False  # KI-Prompting-Latch
        self._prompt_oneshot = False  # KI-Prompting NUR fuer die laufende Aufnahme
        # Inline-Formel-Segmente (Umschalten MITTEN in der Aufnahme):
        self.hotkeys = HotkeyManager(
            on_activate=self._on_hotkey_activate, on_deactivate=self._on_hotkey_deactivate
        )
        self._apply_hotkey_bindings()
        self.hotkeys.start()

        threading.Thread(target=self._warm_up, daemon=True).start()
        self._freihand = None
        self._freihand_audio = None
        try:
            self.tray.set_freihand(self.settings.freihand.aktiv,
                                   self.settings.freihand.startwort)
        except Exception:
            log.debug("Tray-Text nicht setzbar.", exc_info=True)
        self._starte_freihand()
        # LLM vorladen + warmhalten (Ollama entlaedt sonst nach 5 min; erstes Diktat
        # zahlte ~8 s Modell-Ladezeit — im Log real gemessen: 12,9 s Cleanup kalt
        # vs. 4,8 s warm). Der Timer-Tick respektiert advanced.llm_keep_warm:
        # "smart" (Default) haelt nur bis 45 min nach dem letzten Diktat warm —
        # danach wird VRAM wieder frei (wichtig beim Zocken), und der naechste
        # Aufnahmestart laedt parallel zum Sprechen vor. (_last_dictation ist oben
        # VOR dem ersten Fokus-Poll initialisiert.)
        self._keep_warm_tick()
        self._llm_warm_timer = QTimer()
        # 60-s-Takt: fein genug, damit auch ein kurzes Idle-Entlade-Fenster (z. B.
        # 3 min) zeitnah greift. Warm = ein billiger lokaler Ping; nach dem Entladen
        # ist der Tick idempotent (kein Request-Spam gegen ein leeres Ollama).
        self._llm_warm_timer.setInterval(60 * 1000)
        self._llm_warm_timer.timeout.connect(self._keep_warm_tick)
        self._llm_warm_timer.start()
        # Update-Pruefung: 45 s nach dem Start (der Start hat Wichtigeres zu tun),
        # danach taeglich. Bewusst KEIN Check bei jedem Start-Sekundentakt — eine
        # neue Version erscheint nicht minuetlich.
        self._pending_update = None       # Ergebnis von check_for_updates()
        self._update_file = None          # geladene, gepruefte Installationsdatei
        self._update_dialog = None
        self._update_timer = QTimer()
        self._update_timer.setInterval(24 * 60 * 60 * 1000)
        self._update_timer.timeout.connect(self._check_updates_async)
        self._update_timer.start()
        QTimer.singleShot(45_000, self._check_updates_async)
        # Initialzustand (inkl. berechneter Overlay-Default-Position) sofort persistieren.
        self.settings.save()
        # Autostart mit dem gespeicherten Nutzerwunsch abgleichen: ein Update entfernt
        # den Run-Eintrag (Inno-Uninstaller), die settings.json ueberlebt es aber —
        # so bleibt „Autostart mit Windows" auch nach Updates erhalten.
        from .autostart import blocked_by_system, is_autostart_enabled, reconcile_autostart

        if not self.settings.general.autostart and is_autostart_enabled():
            # Eintrag existiert, aber settings.json weiss nichts davon (aeltere Version/
            # Installer hat ihn gesetzt): ADOPTIEREN statt loeschen — sonst wuerde der
            # Abgleich den Autostart bei jedem Update wieder entfernen.
            log.info("Autostart-Eintrag vorhanden, aber nicht in den Einstellungen — adoptiert.")
            self.settings.general.autostart = True
            self.settings.save()
        reconcile_autostart(self.settings.general.autostart)
        if self.settings.general.autostart and blocked_by_system():
            # Sichtbar machen, statt still nicht zu starten: Der Run-Eintrag ist da,
            # Windows ignoriert ihn aber wegen einer Deaktivierung im Task-Manager.
            log.warning(
                "Autostart-Eintrag vorhanden, aber im Task-Manager (Autostart) "
                "deaktiviert — Windows startet Fleech deshalb NICHT mit."
            )

    # ------------------------------------------------------------------- Engine --

    def _build_engine(self) -> None:
        cfg = self.config
        s = self.settings
        self.recorder = Recorder(cfg.audio.samplerate, cfg.audio.device)
        # status: laengere Zwischenschritte gehen ueber den Bus an die Pille
        # (thread-sicher via Queued Connection — der Aufruf kommt aus dem Worker).
        self.pipeline = build_pipeline(cfg, s, status=self.bus.progress.emit)
        # Rohtranskript direkt in die Pille — der Weg ueber den Bus ist Pflicht,
        # die Pipeline laeuft im Worker-Thread.
        self.pipeline.raw_callback = self.bus.raw_ready.emit
        # Cursor-Rueckkehr: Restorer in den Injector einhaengen (plattformabhaengig,
        # damit injection.py portabel bleibt). Das Ziel-Feld wird pro Aufnahme gesetzt.
        from .focusrestore import restore_focus_target

        self.pipeline.injector.focus_restorer = restore_focus_target
        self.focus = DictationApp._build_focus_controller(cfg)
        # Kein Preview-Streamer mehr: die Overlay-Pille zeigt den Audiopegel statt
        # Live-Text (Nutzer-Entscheid) — spart das separate Whisper-Preview-Modell
        # (~0,5 GB VRAM + Warmup). Streaming-Vorschau gibt es weiter im --cli-Modus.

    def _warm_up(self) -> None:
        import numpy as np

        try:
            self.pipeline.stt.transcribe(np.zeros(8000, dtype=np.float32), 16000)
            log.info("STT warm. %s", self.focus.status_line())
        except Exception:
            log.exception("STT-Warm-up fehlgeschlagen.")

    # -- Live-Vorschau (Opt-in) ---------------------------------------------------------

    def _ensure_preview_model(self):
        from ..overlay import PreviewModel

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

    _preview_gen = 0  # Generationszaehler gegen Start/Stop-Races (Load dauert Sekunden)

    def _start_preview_async(self) -> None:
        self._preview_gen += 1
        gen = self._preview_gen

        def worker():
            from ..overlay import PreviewStreamer

            model = self._ensure_preview_model()
            if self._preview is None:
                self._preview = PreviewStreamer(
                    snapshot_fn=lambda: self.recorder.snapshot(),
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

    def _count_dictionary_usage(self, text: str) -> None:
        """Zaehlt, welche Woerterbuch-Begriffe tatsaechlich im eingefuegten Text
        vorkamen. Daraus entscheidet sich, welche Begriffe ueber dem 60er-Limit
        ins Whisper-Priming kommen — die genutzten statt der zufaellig obersten."""
        from ..textutils import find_terms_in_text

        try:
            hits = find_terms_in_text(text, self.pipeline.vocab_terms)
        except Exception:
            log.debug("Woerterbuch-Nutzungszaehlung fehlgeschlagen.", exc_info=True)
            return
        if not hits:
            return
        usage = self.settings.output.dictionary_usage
        for term in hits:
            key = term.lower()
            usage[key] = int(usage.get(key, 0)) + 1
        self.settings.save()

    def _check_dictionary_candidates(self, text: str) -> None:
        """Wahrscheinliche Fehlschreibung eines Woerterbuch-Begriffs erkannt →
        Rueckfrage ausloesen (selbstlernendes Woerterbuch). Nur der erste Treffer
        pro Diktat, abgelehnte Paare werden nie erneut gefragt."""
        import re as _re

        from ..textutils import find_dictionary_candidates

        try:
            candidates = find_dictionary_candidates(
                text, self.pipeline.vocab_terms,
                self.settings.output.dictionary_ignores,
            )
        except Exception:
            log.debug("Woerterbuch-Kandidaten-Suche fehlgeschlagen.", exc_info=True)
            return
        if not candidates:
            return
        recognized, meant = candidates[0]
        sentence = next(
            (s.strip() for s in _re.split(r"(?<=[.!?])\s+", text)
             if recognized in s),
            text[:160],
        )
        self.bus.dictionary_suggestion.emit(recognized, meant, sentence)

    def _on_dictionary_suggestion(self, recognized: str, meant: str, sentence: str) -> None:
        from .main_window import DictionarySuggestionDialog

        def learn(rec: str, target: str) -> None:
            self.settings.output.dictionary.append(f"{rec} => {target}")
            self.settings.save()
            self.pipeline.set_dictionary(self.settings.output.dictionary,
                                         self.settings.output.dictionary_usage)
            self.tray.notify("Fleech", f"Gelernt: „{rec}“ → „{target}“.")

        def ignore(rec: str, target: str) -> None:
            self.settings.output.dictionary_ignores.append(
                f"{rec.lower()} => {target.lower()}"
            )
            self.settings.save()

        self._dict_dialog = DictionarySuggestionDialog(
            recognized, meant, sentence, learn, ignore
        )
        self._dict_dialog.show()
        self._dict_dialog.raise_()

    def _on_preview_text(self, text: str) -> None:
        """Live-Vorschau anzeigen + Signalwort-Erkennung: faellt das Safe-Word,
        faerbt sich die Pille (sichtbares "Befehl erkannt")."""
        self.overlay.show_live_text(text)
        trigger = (self.pipeline.trigger_word or "").lower()
        if trigger and trigger in (text or "").lower():
            self.overlay.set_command_armed(True)

    # Smart-Modus: solange nach dem letzten Diktat aktiv warmhalten. Laeuft das
    # (einstellbare) Idle-Fenster ab ODER laeuft ein Spiel (Gaming-Erkennung), werden
    # die Modelle AKTIV entladen (keep_alive=0) — statt bis zu 30 min keep_alive
    # nachlaufen zu lassen. Beim Zocken zaehlt jedes GB: Ollama haelt sonst ~9 GB im
    # Speicher, obwohl waehrenddessen nicht diktiert wird.

    def show_onboarding(self) -> None:
        """Einfuehrungs-Wizard zeigen (Erststart oder aus den Einstellungen).

        Nicht-modal mit gehaltener Referenz: exec() wuerde den Event-Loop
        verschachteln, waehrend Hotkeys/Poll weiterlaufen — unnoetiges Risiko."""
        from .onboarding import OnboardingDialog

        existing = getattr(self, "_onboarding", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        endpoints = self._llm_endpoints()
        self._onboarding = OnboardingDialog(
            self.settings, list_input_devices, on_changed=self._on_setting_changed,
            endpoints=endpoints, stt_model=getattr(self.config.stt, "model_size", ""),
            llm_base_url=getattr(endpoints[0], "base_url", "") if endpoints else "",
            on_ready=self._warm_up_after_setup,
        )
        self._onboarding.show()
        self._onboarding.raise_()
        self._onboarding.activateWindow()

    def _warm_up_after_setup(self) -> None:
        """Nach erfolgreicher Kaltstart-Einrichtung sofort aufwaermen.

        Beim allerersten Start lief der Warm-up ins Leere (Modelle fehlten noch).
        Ohne diesen Nachzieher waere das erste Diktat trotz fertiger Einrichtung
        das langsamste — Whisper und Ollama laden erst beim Zugriff."""
        threading.Thread(target=self._warm_up, daemon=True).start()
        self._keep_warm_tick()

    def _recheck_input_device(self) -> None:
        """Loopback-Pruefung nach einem Geraetewechsel erneuern.

        Der DeviceCheck wurde bisher NUR einmal beim App-Start gemacht: Wer im
        laufenden Betrieb auf „Stereomix" umstellte, bekam weder Warnung noch die
        Formel-Sperre — der Controller trug bis zum Neustart das Urteil ueber das
        ALTE Geraet. Umgekehrt blieb eine einmal gezeigte Warnung stehen, obwohl
        laengst ein echtes Mikrofon gewaehlt war."""
        from ..audiofocus import DeviceCheck, DeviceGuard

        device = self.settings.recording.microphone
        blocklist = self.settings.recording.blocked_devices
        try:
            check = DeviceGuard.check(device, blocklist)
        except Exception as exc:
            check = DeviceCheck(ok=True, name=f"<unbekannt: {exc}>")
        self.controller.device_check = check
        self.config.audio_focus.blocked_devices = list(blocklist or [])
        if check.ok:
            log.info("Aufnahmegeraet geprueft: %s — in Ordnung.", check.name)
            return
        log.error("⚠ Aufnahmegeraet '%s': %s", check.name, check.reason)
        self.tray.notify("Fleech — Aufnahmegerät", f"„{check.name}“: {check.reason}")

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
        from ..llm.client import ensure_ollama_models, ollama_preload

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

    def _unload_llms_async(self, reason: str) -> None:
        """Alle lokalen Ollama-Modelle SOFORT entladen (RAM/VRAM frei) — idempotent:
        nach einem Entladen passiert bis zum naechsten Aufwaermen nichts mehr (kein
        Request-Spam alle 4 min gegen ein ohnehin leeres Ollama)."""
        if getattr(self, "_llms_unloaded", False):
            return
        self._llms_unloaded = True
        from ..llm.client import ollama_unload

        def work():
            try:
                log.info("LLM-Modelle entladen (%s) — RAM/VRAM wird freigegeben.", reason)
                for endpoint in self._llm_endpoints():
                    ollama_unload(endpoint)
            except Exception:
                log.debug("LLM-Entladen fehlgeschlagen.", exc_info=True)

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ Aufnahme --

    def _on_record_start(self, kind: str) -> None:
        # Lizenz zuerst: ohne gueltigen Schluessel wird nicht aufgenommen. Bewusst
        # HIER und nicht tiefer in der Pipeline — es soll gar nichts erst ins
        # Mikrofon gehen, und der Nutzer bekommt sofort den Dialog statt einer
        # Fehlermeldung nach dem Sprechen.
        if not self._license_ok():
            self.controller.stop_if_active()
            # NICHT direkt aufrufen: diese Methode laeuft im pynput-Listener-Thread.
            self.bus.license_needed.emit()
            return
        allowed, message = self.focus.may_record(math_mode=False)
        if not allowed:
            log.error(message)
            self.bus.set_state(AppState.ERROR, message)
            self.sounds.play("error")
            self.controller.stop_if_active()
            return
        if message:
            log.warning(message)
        strom = getattr(self, "_freihand", None)
        if strom is not None:
            strom.pausiere(True)     # nie zwei sammelnde Wege gleichzeitig
        try:
            self.recorder.start()
        except Exception:
            log.exception("Mikrofon-Start fehlgeschlagen.")
            self.bus.set_state(AppState.ERROR, "Mikrofon-Start fehlgeschlagen")
            self.sounds.play("error")
            self.controller.stop_if_active()
            return
        # Ziel-App + Titel JETZT festhalten, nicht aus dem 3-s-Poll: Der Text
        # landet spaeter in genau diesem Fenster, und davon haengt ab, welches
        # Profil ihn formt. Wer in eine App tabbt und sofort den Hotkey drueckt,
        # bekaeme sonst bis zu drei Sekunden lang das Profil der VORIGEN App —
        # gemeldet, und beim Einfuegen die teuerste Sorte Fehler: Der Text ist
        # dann im richtigen Fenster, aber im falschen Format.
        from .windowsfocus import foreground_now

        prozess, titel = foreground_now()
        self._record_app = prozess or (self.notifier.context.foreground_process or "")
        self._record_title = titel or getattr(
            self.notifier.context, "foreground_title", "") or ""
        # Cursor-Rueckkehr: JETZT das Ziel-Feld merken (Fenster + Caret-Position),
        # damit der Text auch nach Wegklicken/Feldwechsel dort landet. Aus = None →
        # Text geht an den aktuellen Fokus.
        if self.settings.output.restore_focus:
            from .focusrestore import capture_focus_target

            self.pipeline.injector.set_focus_target(capture_focus_target())
        else:
            self.pipeline.injector.set_focus_target(None)
        threading.Thread(target=self.focus.on_recording_start, daemon=True).start()
        # Smart-/Off-Warmhaltung: Modelle koennten kalt sein — parallel zum Sprechen
        # vorladen, dann ist die Ladezeit beim Stop schon (teilweise) absolviert.
        self._last_dictation = time.monotonic()
        if self.settings.advanced.llm_keep_warm != "always":
            threading.Thread(target=self._keep_llm_warm, daemon=True).start()
        self._prompt_oneshot = False    # One-Shot gilt immer nur fuer EINE Aufnahme
        self.notifier.sound("start")
        self.bus.set_state(AppState.LISTENING)
        if kind == "command":
            # Befehls-Aufnahme per »-Button: Pille sofort in Befehls-Optik (cyan) armen.
            self.bus.command_armed.emit(True)
        if self.settings.overlay.live_preview:
            self._start_preview_async()

    def _on_record_stop(self, kind: str) -> None:
        self._last_dictation = time.monotonic()  # haelt das Smart-Warm-Fenster offen
        strom = getattr(self, "_freihand", None)
        if strom is not None:
            strom.pausiere(False)
        self._stop_preview()
        threading.Thread(target=self.focus.on_recording_stop, daemon=True).start()
        audio = self.recorder.stop()
        # One-Shot-Prompt-Modus hier (UI-Thread) einsammeln + zuruecksetzen — der
        # Verarbeitungs-Thread bekommt den Schnappschuss; die Pille faellt sofort
        # auf den persistenten Latch-Zustand zurueck.
        prompt_oneshot, self._prompt_oneshot = self._prompt_oneshot, False
        if prompt_oneshot:
            self.overlay.set_prompt_latched(self._prompt_latched)
        self.notifier.sound("stop")
        self.bus.set_state(AppState.PROCESSING)
        threading.Thread(
            target=self._process, args=(audio,),
            kwargs={"force_command": kind == "command",
                    "prompt_oneshot": prompt_oneshot},
            daemon=True,
        ).start()

    def _cancel_recording(self) -> None:
        """Overlay-X: Aufnahme verwerfen — kein STT, kein LLM, kein Paste."""
        kind = self.controller.cancel()
        if kind is None:
            return
        self._prompt_oneshot = False
        self.overlay.set_prompt_latched(self._prompt_latched)
        self._stop_preview()
        threading.Thread(target=self.focus.on_recording_stop, daemon=True).start()
        self.recorder.stop()  # Audio bewusst verwerfen
        self.bus.set_state(AppState.IDLE, "verworfen")
        log.info("Aufnahme verworfen (%s).", kind)

    def _app_profile_overrides(self):
        """App-Profil der Ziel-App aufloesen → ProfileOverrides.

        Kein zugewiesenes Profil → Standardprofil ("Alle") als Fallback; Profile
        global aus → leere Overrides = Verhalten wie in den Einstellungen."""
        from ..usersettings import (
            ProfileOverrides, app_rule_matches, parse_app_rule, profile_command_mode,
            profile_mode,
        )

        prof = self.settings.profiles
        if not prof.enabled:
            return ProfileOverrides()
        # Von Hand gewaehltes Profil (Punkt in der Pille) sticht die App-Zuordnung.
        # Ob dieses Diktat eine Mail wird, weiss nur der Sprecher — keine Regel
        # ueber Prozessnamen kann das wissen.
        gewaehlt = getattr(self.settings.profiles, "active", "")
        if gewaehlt:
            for item in prof.items or []:
                if isinstance(item, dict) and item.get("name") == gewaehlt:
                    return overrides_from(item)
            log.info("Gewaehltes Profil %r gibt es nicht mehr — zurueck auf automatisch.",
                     gewaehlt)
            self._set_profile("")
        app = getattr(self, "_record_app", "") or ""
        title = getattr(self, "_record_title", "") or ""

        # Zwei Durchlaeufe nach Spezifitaet: Eintraege MIT Titel-Bedingung gewinnen
        # immer gegen den blossen Prozessnamen. Sonst haenge die Zuordnung an der
        # Reihenfolge der Profile — „Code.exe" in einem Profil wuerde
        # „Code.exe :: Fleech" in einem anderen je nach Listenposition verdecken,
        # und der Nutzer haette keine Handhabe, das zu steuern.
        chosen = None
        default_item = None
        candidates = []
        for item in prof.items or []:
            if not isinstance(item, dict):
                continue
            if item.get("default"):
                default_item = item
                continue
            candidates.append(item)

        for want_title in (True, False):
            for item in candidates:
                for entry in item.get("apps", []):
                    if bool(parse_app_rule(entry)[1]) != want_title:
                        continue
                    if app and app_rule_matches(entry, app, title):
                        chosen = item
                        break
                if chosen is not None:
                    break
            if chosen is not None:
                break

        if chosen is None:
            chosen = default_item
        if chosen is None:
            return ProfileOverrides()
        return overrides_from(chosen)

    # -- Profil-Umschaltung (Punkt in der Pille) --------------------------------------

    def current_app(self) -> str:
        """Prozessname der App, in die gerade diktiert wird bzw. wuerde.

        Waehrend einer Aufnahme der beim Start festgehaltene Wert — sonst waere die
        Auswahlliste eine andere als die, fuer die das Diktat gilt (der Fokus kann
        zwischendurch wandern). Sonst der laufende Fokus-Poll.
        """
        if getattr(self, "recorder", None) is not None and self.recorder.recording:
            gemerkt = getattr(self, "_record_app", "")
            if gemerkt:
                return gemerkt
        # Ausserhalb der Aufnahme: frisch abfragen. Der 3-s-Poll haette hier
        # dieselbe Verzoegerung wie oben — die Auswahlliste zeigte dann die
        # Profile der App, aus der man gerade gekommen ist.
        from .windowsfocus import foreground_now

        prozess = foreground_now()[0]
        if prozess:
            return prozess
        try:
            return self.notifier.context.foreground_process or ""
        except Exception:
            return ""

    def profile_names(self) -> list:
        """Profile fuer den Schnellwechsel (Punkt, Hotkey, Liste).

        Nicht alle Profile: Wer viele pflegt, schaltet im Alltag nur zwischen
        zweien um — der Rest laesst sich auf der Profilseite global ausblenden,
        und auf der Apps-Seite je Anwendung noch einmal enger fassen. In Claude
        will man zwischen „KI-Prompt" und „Stichpunkte" wechseln, nicht durch
        „E-Mail" und „Formeln" hindurchtippen.
        """
        from ..usersettings import quickswitch_for_app

        return quickswitch_for_app(
            self.settings.profiles.items,
            getattr(self.settings.profiles, "app_quick", {}) or {},
            self.current_app(),
        )

    def active_profile_name(self) -> str:
        """Profil, das fuer das naechste Diktat gilt — gewaehlt oder automatisch."""
        gewaehlt = getattr(self.settings.profiles, "active", "")
        if gewaehlt:
            return gewaehlt
        for item in self.settings.profiles.items or []:
            if isinstance(item, dict) and item.get("default"):
                return str(item.get("name", "Standard"))
        return "Standard"

    def cycle_profile(self) -> None:
        """Naechstes Profil waehlen; hinter dem letzten wieder „App-Standard".

        Die Wahl bleibt bestehen, bis sie geaendert wird — auch ueber Diktate
        hinweg. Waehrend einer laufenden Aufnahme gilt sie fuer GENAU dieses
        Diktat (die Aufloesung passiert erst beim Verarbeiten).
        """
        namen = self.profile_names()
        if not namen:
            return
        stationen = namen + [""]        # "" = automatisch (App-Zuordnung)
        jetzt = getattr(self.settings.profiles, "active", "")
        try:
            naechste = stationen[(stationen.index(jetzt) + 1) % len(stationen)]
        except ValueError:
            naechste = stationen[0]
        self._set_profile(naechste)

    def _set_profile(self, name: str) -> None:
        """Profil festlegen, merken und kurz anzeigen. "" = automatisch nach App."""
        self.settings.profiles.active = name
        self.settings.save()
        anzeige = name or f"{APP_STANDARD} ({self.active_profile_name()})"
        log.info("Profil gewaehlt: %s", anzeige)
        try:
            self.overlay.show_profile(anzeige)
        except Exception:
            log.debug("Profil-Anzeige fehlgeschlagen.", exc_info=True)

    # -- Profil-Hotkey: tippen = weiterschalten, halten = Auswahlliste --------------

    def _on_profile_key(self, gedrueckt: bool) -> None:
        """UI-Thread: Profil-Taste gedrueckt (True) bzw. losgelassen (False)."""
        if gedrueckt:
            self._on_profile_key_down()
        else:
            self._on_profile_key_up()

    def _on_profile_key_down(self) -> None:
        """Taste gedrueckt: Timer starten. Ob Tippen oder Halten, entscheidet sich
        erst beim Loslassen — deshalb passiert hier bewusst noch nichts."""
        self._profile_key_held = True
        QTimer.singleShot(_PROFIL_HALTEN_MS, self._maybe_open_profile_picker)

    def _maybe_open_profile_picker(self) -> None:
        if not getattr(self, "_profile_key_held", False):
            return                      # war ein Tipp — schon losgelassen
        self._profile_picker_open = True
        self.show_profile_picker()

    def _on_profile_key_up(self) -> None:
        war_gehalten = getattr(self, "_profile_picker_open", False)
        self._profile_key_held = False
        self._profile_picker_open = False
        if not war_gehalten:
            self.cycle_profile()        # kurzer Tipp → naechstes Profil

    def show_profile_picker(self) -> None:
        """Auswahlliste am Mauszeiger (Hotkey halten)."""
        from .profilepicker import ProfilePicker

        picker = getattr(self, "_profile_picker", None)
        if picker is None:
            picker = self._profile_picker = ProfilePicker()
            picker.chosen.connect(self._set_profile)
        picker.show_at_cursor(self.profile_names(),
                              getattr(self.settings.profiles, "active", ""))

    def _process(self, audio, force_command: bool = False,
                 prompt_oneshot: bool = False) -> None:
        """Verarbeitung eines Diktats — global serialisiert.

        Aus Nutzersicht sind Diktate ohnehin sequenziell, technisch koennen sich zwei
        Laeufe aber ueberlappen (Diktat 2 endet, waehrend Diktat 1 noch am LLM haengt).
        Dann wuerden beide auf denselben DocumentTracker schreiben und der Bezugspunkt
        fuer Safe-Word-Ersetzungen waere falsch. Das Lock haelt die Reihenfolge; es
        blockiert nur Worker-Threads, die UI bleibt bedienbar."""
        if self._process_lock.locked():
            log.info("Vorheriges Diktat laeuft noch — Verarbeitung wird eingereiht.")
            self.bus.progress.emit("Vorheriges Diktat wird noch verarbeitet …")
        with self._process_lock:
            if self._llms_unloaded:
                # Modelle wurden entladen (Leerlauf/Spiel) → der erste Aufruf zahlt
                # die Ladezeit (~13 s statt ~5 s). Das sichtbar machen, sonst wirkt
                # die App haengengeblieben.
                self.bus.progress.emit("KI-Modell wird geladen …")
            self._process_locked(audio, force_command,
                                 prompt_oneshot)

    def _process_locked(self, audio, force_command: bool = False,
                        prompt_oneshot: bool = False) -> None:
        import time as _time

        t0 = _time.monotonic()
        try:
            prof = self._app_profile_overrides()
            override, style_hints = prof.intervention, prof.style_hints
            slot_mode = prof.mode_slot
            # KI-Prompting: Latch, Profil-Slot oder One-Shot (Hotkey WAEHREND der
            # Aufnahme, gilt nur fuer dieses Diktat). Einen Formel-Modus gibt es
            # seit v3.0.0 nicht mehr — Formeln werden vor dem Cleanup determi-
            # nistisch uebersetzt und brauchen kein Umschalten.
            prompt_active = (self._prompt_latched or prompt_oneshot)
            # Ausgabeformat des Profils: „E-Mail"/„KI-Prompt" formulieren das
            # Diktat ueber einen eigenen System-Prompt um, statt es nur zu
            # glaetten. „math" ist kein Umformulieren und laeuft weiter im Parser.
            output_format = slot_mode if slot_mode in ("email", "prompt") else ""
            # Gesprochenes Safe-Word je Profil abschaltbar (Meetings/Grossraum): der
            # »-Knopf bleibt immer nutzbar, nur das laute Wort entfaellt.
            suppress_command = not prof.command_allowed(
                self.settings.output.command_enabled
            )
            result = self.pipeline.process(
                audio, self.config.audio.samplerate,
                intervention_override=override,
                style_hints=style_hints,
                force_command=force_command,
                prompt_mode=prompt_active,
                output_format=output_format,
                suppress_command=suppress_command,
                # Beim Aufnahmestart festgehalten, nicht der aktuelle Fokus: Das
                # Vokabular gehoert zu dem Fenster, in das der Text auch geht.
                app=getattr(self, "_record_app", ""),
                window_title=getattr(self, "_record_title", ""),
            )
        except Exception:
            log.exception("Pipeline-Fehler.")
            result = "error"
        if result in ("ok", "fallback") and self.settings.general.save_history \
                and self.pipeline.last_injected:
            record = DictationRecord(
                ts=_time.time(),
                raw=self.pipeline.last_raw,
                cleaned=self.pipeline.last_injected,
                audio_seconds=len(audio) / max(1, self.config.audio.samplerate),
                app=getattr(self, "_record_app", ""),
                mode=self.pipeline.last_mode,
                tier=self.pipeline.last_tier,
                status=result,
                stt_ms=self.pipeline.last_stt_ms,
                llm_ms=self.pipeline.last_llm_ms,
            )
            self.store.add(record)
            self.bus.history_changed.emit()
        if result in ("ok", "fallback") and self.pipeline.last_injected:
            # Rueckgaengig-Weg vorbereiten: Was steht im Dokument, und was hat der
            # Sprecher wirklich gesagt? Nur wenn sich beides unterscheidet, gibt es
            # ueberhaupt etwas zurueckzunehmen.
            self._undo_candidate = (
                self.pipeline.last_injected, self.pipeline.last_raw, _time.monotonic()
            )
            # Automatisch absenden — nur wo das Profil es ausdruecklich erlaubt und
            # nur bei einem normalen Diktat. Nach einem Befehl oder einem Rohtext-
            # Rueckfall waere es falsch: Dort will man erst sehen, was ankam.
            if prof.auto_send and result == "ok" and self.pipeline.last_mode == "cleanup":
                self._auto_send()
            if result == "fallback":
                # Vor transcript_ready: die Blase soll direkt amber gerahmt kommen.
                self.bus.injection_fallback.emit()
            # Formel-Hinweis MIT dem Transkript, nicht davor: Zwei Blasen kurz
            # hintereinander bedeuten, dass die zweite die erste sofort ueberschreibt
            # — die Vorschau war dadurch nie zu sehen (vom Nutzer gemeldet).
            formulas = list(getattr(self.pipeline, "last_formulas", None) or [])
            self.bus.formula_preview.emit(formulas)
            # Nach der Formel-Vorschau: Wurde etwas VERWORFEN, ist das die
            # gewichtigere Meldung und darf die Formel-Blase ueberschreiben.
            dropped = getattr(self.pipeline, "last_dropped_tail", "") or ""
            if dropped:
                self.bus.tail_dropped.emit(dropped)
            self.bus.transcript_ready.emit(self.pipeline.last_injected)
            self._check_dictionary_candidates(self.pipeline.last_injected)
            self._count_dictionary_usage(self.pipeline.last_injected)
        if result == "ok":
            self.notifier.sound("commit")
            self.bus.set_state(AppState.IDLE, "eingefügt")
            if _time.monotonic() - t0 > 15:
                self.notifier.toast("long_processing", "Fleech", "Verarbeitung abgeschlossen.")
        elif result == "fallback":
            self.notifier.sound("error")
            self.bus.set_state(AppState.IDLE, "eingefügt (Fallback — Log prüfen)")
            if self.pipeline.last_error_kind == "quota":
                self.notifier.toast(
                    "provider_quota", "Fleech",
                    "Formel-Provider meldet Rate-Limit (429) — Text kam als "
                    "Cleanup-Fallback an.",
                )
        elif result in ("empty", "too_short"):
            self.bus.set_state(AppState.IDLE, "nichts erkannt")
        else:
            self.notifier.sound("error")
            self.bus.set_state(AppState.ERROR, "Verarbeitung fehlgeschlagen — Log prüfen")
            self.notifier.toast("critical_error", "Fleech",
                                "Verarbeitung fehlgeschlagen — Details im Log.")

    # -------------------------------------------------------------------- Hotkeys --

    def _on_hotkey_activate(self, name: str) -> None:
        """Hotkey gedrueckt. Die Modus-Hotkeys (Mathe/KI-Prompting) wirken NUR waehrend
        einer laufenden Aufnahme — ausserhalb werden sie bewusst ignoriert, damit
        dieselben Tasten (z. B. Corsair-G-Tasten) ausserhalb von Fleech frei fuer
        andere Dinge belegbar bleiben. Den Modus fuer kuenftige Diktate schaltet man
        ueber den Punkt in der Pille (Klick-Zyklus) oder den Profil-Slot.
        Alles andere geht an die Aufnahme-Steuerung (Hold/Toggle)."""
        recording = self.controller.active and self.recorder.recording
        if name == "undo":
            # Bewusst NICHT waehrend einer Aufnahme: Wer gerade spricht, meint mit
            # dem Griff zur Tastatur nichts, das mitten im Diktat Text loeschen soll.
            if recording:
                log.info("Rueckgaengig-Hotkey ignoriert — Aufnahme laeuft.")
            else:
                self._undo_last_output()
            return
        if name == "profile":
            # NUR melden: dieser Aufruf kommt aus dem pynput-Thread, dort waere
            # jeder QTimer wirkungslos. Die Zeitmessung laeuft im UI-Thread.
            # Bewusst AUCH waehrend der Aufnahme erlaubt: ob dieses Diktat eine
            # Mail wird, entscheidet man oft mitten im Sprechen.
            self.bus.profile_key.emit(True)
            return
        if name == "pause":
            # Nur waehrend einer Aufnahme sinnvoll — ausserhalb bleibt die Taste
            # fuer andere Programme frei (gleiche Regel wie bei den Modus-Hotkeys).
            if recording:
                self.toggle_pause()
            else:
                log.info("Pause-Hotkey ignoriert — keine Aufnahme aktiv.")
            return
        if name == "prompt_toggle":
            if recording:
                self._toggle_prompt_oneshot()
            else:
                log.info("KI-Prompting-Hotkey ignoriert — keine Aufnahme aktiv.")
            return
        self.controller.press(name)

    def _on_hotkey_deactivate(self, name: str) -> None:
        if name == "profile":
            self.bus.profile_key.emit(False)
            return
        if name in ("prompt_toggle", "undo", "pause"):
            return  # wirken beim Druck, nicht beim Loslassen
        self.controller.release(name)

    # Nach dieser Zeit gilt eine Ausgabe als "vom Tisch" — wer eine Minute weiter
    # gearbeitet hat, will nicht, dass ein Tastendruck irgendwo im Text herumloescht.
    _UNDO_MAX_AGE_S = 120

    def _undo_last_output(self) -> None:
        """Die letzte Ausgabe durch das ROH-Transkript ersetzen.

        Kein allgemeines "Rueckgaengig", sondern gezielt der Weg fuer den Fall, dass
        die Bereinigung danebengriff: Es kommt Wort fuer Wort das zurueck, was
        gesprochen wurde. Loeschen kann der Nutzer danach mit dem Undo seiner App.

        Drei harte Bedingungen, alle aus einem echten Datenverlust gelernt (ein Befehl
        loeschte einmal 2701 Zeichen ersatzlos): Es muss eine eigene, frische Ausgabe
        geben, der Cursor muss noch dahinter stehen (`resolve_scope` liefert bei
        gewechseltem Fenster None), und jede Ausgabe laesst sich nur EINMAL ersetzen.
        """
        kandidat = getattr(self, "_undo_candidate", None)
        if not kandidat:
            self._flash_status("Nichts zum Zurücknehmen")
            return
        injected, raw, ts = kandidat
        if time.monotonic() - ts > self._UNDO_MAX_AGE_S:
            self._undo_candidate = None
            self._flash_status("Letzte Ausgabe ist zu lange her")
            return
        raw = (raw or "").strip()
        if not raw or raw == injected:
            self._flash_status("Rohtext ist identisch")
            return
        # Steht der Cursor noch hinter unserem Text? Nach Fensterwechsel oder eigenem
        # Tippen ist die Position unbekannt — dann wird NICHT geloescht.
        if self.pipeline.tracker.resolve_scope("dictated") is None:
            self._undo_candidate = None
            self._flash_status("Cursor nicht mehr an der Stelle")
            return

        if self._process_lock.locked():
            # Ein Diktat wird gerade eingefuegt — dazwischenzufunken hiesse, an einer
            # Stelle zu loeschen, die sich im selben Moment verschiebt.
            self._flash_status("Verarbeitung läuft — bitte kurz warten")
            return

        self._undo_candidate = None          # nur ein Versuch je Ausgabe
        try:
            with self._process_lock:         # nie parallel zu einem laufenden Diktat
                self.pipeline.injector.replace_tail(len(injected), raw)
                self.pipeline.tracker.record_replace(len(injected), raw)
        except Exception:
            log.exception("Rueckgaengig fehlgeschlagen.")
            self._flash_status("Zurücknehmen fehlgeschlagen — Log prüfen")
            return
        log.info("Letzte Ausgabe durch Rohtext ersetzt (%d → %d Zeichen).",
                 len(injected), len(raw))
        self.notifier.sound("commit")
        self._flash_status("Rohtext eingesetzt")

    def _auto_send(self) -> None:
        """Enter nachschicken (Profil-Einstellung „Nachricht absenden").

        Fehler hier duerfen das Diktat nie nachtraeglich zum Fehlschlag machen —
        der Text steht bereits im Feld, nur das Absenden hat nicht geklappt.
        """
        try:
            self.pipeline.injector.send_enter()
            log.info("Automatisch abgeschickt (Profil-Einstellung).")
        except Exception:
            log.exception("Automatisches Absenden fehlgeschlagen — Text steht im Feld.")
            self._flash_status("Absenden fehlgeschlagen")

    # -- Nachbearbeitung aus dem Verlauf (F3) ------------------------------------------

    def _reprocess_entry(self, roh: str, fmt: str, name: str) -> None:
        """Ein gespeichertes Diktat neu bereinigen lassen. Laeuft im Worker-Thread.

        Das Ergebnis geht in die ZWISCHENABLAGE. Wer im Verlauf rechtsklickt, steht
        im Fleech-Fenster — das urspruengliche Zielfeld ist laengst nicht mehr
        fokussiert. Blind dorthin zu schreiben ist genau die Fehlerklasse, aus der
        die Cursor-Regeln stammen (einmal 2701 Zeichen fremder Text geloescht).
        """
        if self._process_lock.locked():
            self._flash_status("Ein Diktat läuft noch")
            return

        def arbeit():
            with self._process_lock:
                self.bus.progress.emit(f"Neu bereinigen als {name} …")
                try:
                    text = self.pipeline.reprocess(roh, fmt)
                except Exception:
                    log.exception("Nachbearbeitung fehlgeschlagen.")
                    text = ""
                self.bus.reprocessed.emit(text, name)

        threading.Thread(target=arbeit, daemon=True).start()

    def _on_reprocessed(self, text: str, name: str) -> None:
        """UI-Thread: Ergebnis in die Zwischenablage und Rueckmeldung geben."""
        if not text:
            self._flash_status(f"{name} fehlgeschlagen — Text unverändert")
            return
        try:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(text)
        except Exception:
            log.exception("Zwischenablage nicht beschreibbar.")
            self._flash_status("Zwischenablage nicht erreichbar")
            return
        log.info("Neu bereinigt als %s (%d Zeichen) — in der Zwischenablage.",
                 name, len(text))
        self._flash_status(f"{name} kopiert — Strg+V zum Einfügen")

    def _flash_status(self, text: str) -> None:
        """Kurze Rueckmeldung ueber die Pille — thread-sicher ueber den StateBus."""
        try:
            self.bus.progress.emit(text)
        except Exception:
            log.debug("Statusmeldung fehlgeschlagen.", exc_info=True)

    def _toggle_prompt_latch(self) -> None:
        """KI-Prompting ein-/ausrasten: alle folgenden Diktate werden zu strukturierten
        Prompts umformuliert. Sichtbar ueber die getoente Overlay-Pille + kurzer Ton;
        Toasts waeren hier der falsche Kanal (Cooldown/DND-/Gaming-Unterdrueckung)."""
        self._prompt_latched = not self._prompt_latched
        self._safe_overlay_latch("prompt", self._prompt_latched)
        self.notifier.sound("start" if self._prompt_latched else "stop")
        log.info("KI-Prompting-Latch %s.", "an" if self._prompt_latched else "aus")

    def _toggle_prompt_oneshot(self) -> None:
        """KI-Prompting NUR fuer die laufende Aufnahme markieren (Hotkey mitten im
        Diktat). Kein persistenter Latch: nach der Verarbeitung (oder Abbruch) faellt
        der Modus automatisch zurueck — die Pille zeigt solange amber."""
        self._prompt_oneshot = not self._prompt_oneshot
        on = self._prompt_oneshot
        self._safe_overlay_latch("prompt", on or self._prompt_latched)
        self.notifier.sound("start" if on else "stop")
        log.info("KI-Prompting fuer DIESES Diktat %s.", "an" if on else "aus")

    def _safe_overlay_latch(self, kind: str, on: bool) -> None:
        try:
            self.overlay.set_prompt_latched(on)
        except Exception:
            log.debug("Overlay-Latch-Anzeige fehlgeschlagen.", exc_info=True)

    def _apply_hotkey_bindings(self) -> None:
        bindings = {}
        # Der dedizierte Halte-Mathe-Hotkey wurde entfernt (Nutzer-Entscheid) —
        # Formeln laufen ueber Mathe-Umschalt (Latch/Inline) und die Auto-Erkennung.
        for name, attr in (("dictate", "hotkey"),
                           ("prompt_toggle", "prompt_toggle_hotkey"),
                           ("undo", "undo_hotkey"),
                           ("pause", "pause_hotkey"),
                           ("profile", "profile_hotkey")):
            raw = getattr(self.settings.recording, attr)
            if not raw:
                continue  # geloeschte Bindung → nicht registrieren
            try:
                bindings[name] = HotkeySpec.parse(raw)
            except ValueError as exc:
                log.warning("Ungueltiger Hotkey %s=%r: %s", name, raw, exc)
        self.hotkeys.set_bindings(bindings)

    # ---------------------------------------------------------- Settings-Reaktionen --

    def _on_setting_changed(self, section: str) -> None:
        if section == "overlay":
            self.overlay.apply_settings()
            if self.settings.overlay.live_preview and self._preview_model is None:
                # Modell im Hintergrund vorladen — das erste Diktat zeigt die
                # Vorschau dann ohne Lade-Verzoegerung.
                threading.Thread(target=self._ensure_preview_model, daemon=True).start()
        elif section == "interface":
            self.window.apply_interface()
        elif section == "recording":
            self.controller.set_mode(self.settings.recording.mode)
        elif section == "hotkeys":
            self._apply_hotkey_bindings()  # aktualisiert die Bindungen live
        elif section == "audio_focus":
            self.config.audio_focus.mode = self.settings.audio_focus.mode
            level = max(0.0, min(1.0, float(self.settings.audio_focus.duck_level)))
            self.config.audio_focus.duck_level = level
            self.config.audio_focus.hard_duck_level = level
            self.focus = DictationApp._build_focus_controller(self.config)
        elif section == "math":
            self.pipeline.auto_latex = (
                self.settings.math.enabled and self.settings.math.auto_latex
            )
        elif section == "output":
            self.pipeline.intervention = self.settings.output.intervention
            self.pipeline.spoken_symbols = self.settings.output.spoken_symbols
            self._apply_trigger_word()
        elif section == "dictionary":
            self.pipeline.set_dictionary(self.settings.output.dictionary,
                                         self.settings.output.dictionary_usage)
        elif section == "onboarding":
            self.show_onboarding()
        elif section == "snippets":
            self.pipeline.set_snippets(self.settings.output.snippets,
                                       self.settings.output.snippet_keyword)
        elif section == "adaptive":
            self.pipeline.adaptive = self.settings.advanced.adaptive_cleanup
            if self.settings.advanced.adaptive_cleanup:
                self._keep_warm_tick()
        elif section == "warmhold":
            self._keep_warm_tick()  # bei "always"/"smart" sofort vorladen
        elif section == "focus":
            self._poll_focus()  # Overlay-Override sofort neu bewerten
        elif section == "microphone":
            self.controller.stop_if_active()
            self.recorder = Recorder(
                self.config.audio.samplerate, self.settings.recording.microphone
            )
            # Overlay-Waveform folgt automatisch (level_provider ist late-bound).
            self._recheck_input_device()
        elif section == "stt_device":
            self.controller.stop_if_active()
            self.config.stt.device = "auto" if self.settings.advanced.prefer_gpu else "cpu"
            self.pipeline.stt = create_stt(self.config.stt)
            threading.Thread(target=self._warm_up_stt, daemon=True).start()
        # Overlay-Tooltip (Bedienmodus/Fokus/Mathe/Eingriff) aktuell halten.
        self._update_mode_line()

    def _warm_up_stt(self) -> None:
        import numpy as np

        try:
            self.pipeline.stt.transcribe(np.zeros(8000, dtype=np.float32), 16000)
            log.info("STT neu geladen (device=%s) und warm.", self.config.stt.device)
        except Exception:
            log.exception("STT-Neuladen fehlgeschlagen.")

    def _apply_trigger_word(self) -> None:
        """Safe-Word live umstecken: Routing + Command-Prompt (⟨TRIGGER⟩) neu setzen.
        Deaktiviert (command_enabled=False) → leeres Trigger-Wort = Routing erkennt
        nie einen Befehl, alles ist normales Diktat."""
        from ..prompts import load_command_prompt

        effective = (self.settings.output.trigger_word.strip()
                     or self._base_trigger_word)
        if not self.settings.output.command_enabled:
            effective = ""
        if effective == self.pipeline.trigger_word:
            return
        self.pipeline.trigger_word = effective
        if effective:
            self.pipeline.command_prompt = load_command_prompt(
                self.config.prompts_dir, effective
            )
            self.config.command.trigger_word = effective
        log.info("Safe-Word ist jetzt: %s", effective or "<deaktiviert>")

    def _update_mode_line(self) -> None:
        s = self.settings
        self.overlay.set_mode_line(
            f"{'Hold' if s.recording.mode == 'hold' else 'Toggle'} | "
            f"Fokus: {s.audio_focus.mode} | "
            f"Eingriff: {s.output.intervention}"
        )

    # ------------------------------------------------------------------ Tray/Fenster --

    def _toggle_overlay(self) -> None:
        o = self.settings.overlay
        o.visibility = "off" if o.visibility != "off" else "during_activity"
        self.settings.save()
        self.overlay.apply_settings()

    def _toggle_overlay_edit(self) -> bool:
        """Bearbeiten-Modus umschalten (Pille dauerhaft + ziehbar). Gibt neuen Zustand."""
        editing = self.overlay.toggle_edit_mode()
        self.settings.save()
        return editing

    def _reset_overlay(self) -> None:
        self.overlay.reset_position()
        self.settings.save()

    def _apply_overlay_preset(self, preset: str) -> None:
        self.overlay.apply_preset(preset)
        self.settings.save()

    def _open_settings(self) -> None:
        self.window.open_page("settings")

    def _clear_history(self) -> None:
        """Verlauf loeschen NUR nach getippter Bestaetigung („Delete") — ein
        versehentlicher Button-Klick darf die Historie nie unwiderruflich leeren."""
        from PySide6.QtWidgets import QInputDialog, QLineEdit

        text, ok = QInputDialog.getText(
            self.window, "Verlauf löschen",
            "Das löscht ALLE aufgezeichneten Diktate unwiderruflich.\n"
            "Zur Bestätigung „Delete“ eintippen:",
            QLineEdit.Normal, "",
        )
        if not ok or text.strip().lower() != "delete":
            if ok:  # bestaetigt, aber falsch getippt → kurz erklaeren statt still nichts
                self.tray.notify("Fleech", "Nicht gelöscht — Bestätigung war nicht „Delete“.")
            return
        self.store.clear()
        self.window.refresh_data()
        self.tray.notify("Fleech", "Diktat-Verlauf gelöscht.")

    def _poll_focus(self) -> None:
        """Alle 3 s: Fokus-Kontext aktualisieren und Overlay-Verhalten anpassen.
        Reagiert auch SOFORT auf Spielstart/-ende (statt auf den 4-min-Warmhalte-Tick
        zu warten): Spiel an → LLMs entladen (RAM frei), Spiel aus → ggf. aufwaermen."""
        ctx = self.notifier.refresh()
        self.overlay.set_focus_override(self.notifier.policy.overlay_override(ctx))
        # Session-Punkt: erinnert sich Fleech an Diktate im gerade fokussierten
        # Fenster? Defensive Kapselung — der Punkt ist reine Information und darf
        # den Poll (traegt auch die Gaming-Erkennung) nie stoeren.
        try:
            self.overlay.set_session_info(self.pipeline.tracker.session_info())
        except Exception:
            log.debug("Session-Info nicht ermittelbar.", exc_info=True)
        gaming = self.notifier.policy.gaming_active(ctx)
        if gaming != self._was_gaming:
            self._was_gaming = gaming
            if self.settings.advanced.llm_keep_warm == "smart":
                if gaming:
                    self._unload_llms_async("Spiel gestartet")
                else:
                    self._keep_warm_tick()  # zurueck am Desktop → ggf. wieder aufwaermen

    def _on_window_closed_to_tray(self) -> None:
        # Overlay nie im Bearbeiten-Modus zurücklassen (sonst bleibt die Pille dauerhaft).
        if self.overlay.is_edit_mode():
            self.overlay.toggle_edit_mode()
            self.panel.set_overlay_editing(False)
            self.settings.save()
        if not self.settings.window.tray_hint_shown:
            shown = self.notifier.toast(
                "background_info", "Fleech",
                "Die App läuft im Hintergrund weiter — Beenden über das Tray-Menü.",
            )
            if shown:
                self.settings.window.tray_hint_shown = True
                self.settings.save()

    def attach_instance_lock(self, lock) -> None:
        self._instance_lock = lock

    def _start_ipc_server(self) -> None:
        """Zweitstart-UX: eine weitere Fleech.exe weckt uns (Settings-Fenster) statt
        parallel zu laufen. Der Instance-Lock verhindert die zweite Instanz, der
        IPC-Kanal macht daraus einen sinnvollen Klick statt eines stillen No-Ops."""
        try:
            from PySide6.QtNetwork import QLocalServer

            QLocalServer.removeServer(IPC_NAME)  # Stale-Socket nach Crash aufraeumen
            self._ipc = QLocalServer()
            if self._ipc.listen(IPC_NAME):
                self._ipc.newConnection.connect(self._on_ipc_wake)
            else:
                log.warning("IPC-Server nicht startbar: %s", self._ipc.errorString())
        except Exception:
            log.exception("IPC-Setup fehlgeschlagen — Zweitstart oeffnet kein Fenster.")

    def _on_ipc_wake(self) -> None:
        """Zwei Befehle: "show" (Zweitstart) und "quit" (Update/Deployment).

        „quit" gibt es, weil ein hartes Beenden von aussen (`taskkill /F`) mitten
        in einem `settings.save()` landen kann. Seit dem atomaren Schreiben ist das
        nicht mehr fatal — aber der ordentliche Weg ist trotzdem der bessere: Die
        App speichert zu Ende, gibt Mutex und Hotkeys frei und geht dann.
        """
        sock = self._ipc.nextPendingConnection()
        befehl = b""
        if sock is not None:
            if sock.waitForReadyRead(300):
                befehl = bytes(sock.readAll()).strip()
            sock.close()
        if befehl == b"quit":
            log.info("Beenden per IPC angefordert (Update/Deployment).")
            self._quit()
            return
        log.info("Zweite Instanz angeklopft — oeffne Hauptfenster.")
        self.window.open_page("home")

    def _reload(self) -> None:
        """App neu laden: sauberer Prozess-Neustart (Modelle, Config, Prompts frisch)."""
        log.info("Neustart …")
        self.settings.save()
        self.hotkeys.stop()
        # Mutex VOR execv freigeben, sonst blockiert der alte Handle den Nachfolger
        # (acquire() im Nachfolger hat zusaetzlich eine Retry-Schleife als Netz).
        if getattr(self, "_instance_lock", None) is not None:
            self._instance_lock.release()
        if getattr(sys, "frozen", False):
            # gepackte EXE: direkt neu starten (kein "-m fleech" verfuegbar)
            os.execv(sys.executable, [sys.executable, "--gui"])
        else:
            os.execv(sys.executable, [sys.executable, "-m", "fleech", "--gui"])

    # -- Pause -----------------------------------------------------------------------

    def toggle_pause(self) -> None:
        """Aufnahme anhalten bzw. fortsetzen (Pillen-Knopf oder Hotkey).

        Zweck: mitten im Diktat kurz mit jemandem sprechen, ohne das bisher
        Gesagte zu verlieren. Der Mikrofon-Stream bleibt offen, es wird nur nichts
        mehr gesammelt — beim Fortsetzen haengt Fleech eine kurze Stille an, damit
        die Erkennung an der Nahtstelle eine Sprechpause sieht statt eines
        Schnitts mitten im Wort.

        Ohne laufende Aufnahme passiert bewusst nichts: ein „Pause" im Leerlauf
        haette keinen Zustand, den man spaeter fortsetzen koennte.
        """
        if not self.recorder.recording:
            log.info("Pause ignoriert — es laeuft keine Aufnahme.")
            return
        if self.recorder.paused:
            self.recorder.resume()
            log.info("Aufnahme fortgesetzt.")
        else:
            self.recorder.pause()
            log.info("Aufnahme pausiert — es wird nichts aufgezeichnet.")
        self.bus.paused_changed.emit(self.recorder.paused)
        # Ueber den Notifier, nicht direkt am SoundPlayer vorbei: sonst piepst es
        # auch im Spiel oder bei „Nicht stoeren" (dieselbe Regel wie Start/Stopp).
        self.notifier.sound("stop" if self.recorder.paused else "start")

    # -- Freihand-Modus (F1) -----------------------------------------------------------

    def _starte_freihand(self) -> None:
        """Dauerlauschen aufbauen — im Hintergrund, weil tiny geladen werden muss.

        Standardmaessig aus: Eine App, die ungefragt dauerhaft mithoert, waere ein
        Vertrauensbruch, auch wenn technisch nichts gespeichert wird.
        """
        if not self.settings.freihand.aktiv:
            return

        def bauen():
            try:
                from ..freihand import (
                    Einstellungen, FreihandStream, Lauscher, baue_erkenner, baue_vad,
                )

                s = self.settings.freihand
                lauscher = Lauscher(
                    Einstellungen(
                        aktiv=True, startwort=s.startwort,
                        abbruchwort=s.abbruchwort, stille_s=s.stille_s,
                        ausgeschlossene_apps=tuple(s.ausgeschlossene_apps or ()),
                    ),
                    vad=baue_vad(),
                    erkenner=baue_erkenner(sprache=self.settings.general.language),
                )
                self._freihand = FreihandStream(
                    lauscher, self._freihand_ereignis,
                    geraet=self.settings.recording.microphone,
                )
                if self._freihand.start():
                    self.bus.freihand_zustand.emit("lauscht")
            except Exception:
                log.exception("Freihand-Modus nicht startbar.")
                self._freihand = None

        threading.Thread(target=bauen, daemon=True).start()

    def _stoppe_freihand(self) -> None:
        strom = getattr(self, "_freihand", None)
        if strom is not None:
            strom.stop()
        self._freihand = None
        self.bus.freihand_zustand.emit("aus")

    def toggle_freihand(self) -> None:
        """Schnellschalter (Tray/Hotkey): sofort aufhoeren mitzuhoeren.

        Der Nutzer muss das Lauschen jederzeit mit einem Griff beenden koennen —
        ohne Einstellungen zu oeffnen und ohne zu suchen.
        """
        an = not self.settings.freihand.aktiv
        self.settings.freihand.aktiv = an
        self.settings.save()
        try:
            self.tray.set_freihand(an, self.settings.freihand.startwort)
        except Exception:
            log.debug("Tray-Text nicht aktualisierbar.", exc_info=True)
        if an:
            self._starte_freihand()
            self._flash_status("Freihand an — sag „%s“" % self.settings.freihand.startwort)
        else:
            self._stoppe_freihand()
            self._flash_status("Freihand aus")

    def _freihand_ereignis(self, ereignis, audio) -> None:
        """AUDIO-THREAD! Nur weiterreichen — alles andere gehoert in den UI-Thread."""
        if audio is not None and len(audio):
            self._freihand_audio = audio
        self.bus.freihand_ereignis.emit(ereignis.value)

    def _on_freihand(self, ereignis: str) -> None:
        """UI-Thread: auf ein Freihand-Ereignis reagieren."""
        if ereignis == "start":
            if not self._freihand_erlaubt():
                return
            self.bus.freihand_zustand.emit("aufnahme")
            self.bus.set_state(AppState.LISTENING)
            self.notifier.sound("start")
            prozess, titel = self._freihand_ziel()
            self._record_app, self._record_title = prozess, titel
            return
        if ereignis == "abbruch":
            self._freihand_audio = None
            self.bus.freihand_zustand.emit("lauscht")
            self.bus.set_state(AppState.IDLE)
            self._flash_status("Verworfen")
            return
        # ENDE: wie ein normales Diktat weiterverarbeiten.
        audio, self._freihand_audio = getattr(self, "_freihand_audio", None), None
        self.bus.freihand_zustand.emit("lauscht")
        if audio is None or not len(audio):
            self.bus.set_state(AppState.IDLE)
            return
        self.notifier.sound("stop")
        self.bus.set_state(AppState.PROCESSING)
        threading.Thread(target=self._process, args=(audio,), daemon=True).start()

    def _freihand_ziel(self):
        from .windowsfocus import foreground_now

        return foreground_now()

    def _freihand_erlaubt(self) -> bool:
        """In dieser App lauschen? Spiele und Meetings stehen auf der Sperrliste."""
        strom = getattr(self, "_freihand", None)
        if strom is None:
            return False
        prozess = self._freihand_ziel()[0]
        if not strom.lauscher.app_erlaubt(prozess):
            log.info("Freihand in %s ausgeschlossen — Aktivierung verworfen.", prozess)
            self.bus.freihand_zustand.emit("lauscht")
            return False
        return True

    # -- Lizenz ----------------------------------------------------------------------

    def _license_ok(self) -> bool:
        """Darf diese Installation diktieren?

        Das Ergebnis wird gemerkt, weil die Pruefung bei JEDEM Aufnahmestart laeuft
        — eine Signaturpruefung kostet zwar nur Mikrosekunden, aber der Hotkey-Pfad
        ist der letzte Ort, an dem man Arbeit sammeln will. Der Merker wird
        zurueckgesetzt, sobald ein Schluessel eingetragen wird.
        """
        gemerkt = getattr(self, "_license_state", None)
        if gemerkt is None:
            from ..licensing import check

            gemerkt = check(self.settings)
            self._license_state = gemerkt
            if not gemerkt.ok:
                log.warning("Fleech ist nicht freigeschaltet: %s", gemerkt.reason)
        return bool(gemerkt.ok)

    def show_license_dialog(self) -> None:
        """Freischalt-Dialog zeigen (nicht-modal, Referenz gehalten)."""
        from .licensedialog import LicenseDialog

        vorhanden = getattr(self, "_license_dialog", None)
        if vorhanden is not None and vorhanden.isVisible():
            vorhanden.raise_()
            vorhanden.activateWindow()
            return
        self._license_dialog = LicenseDialog(
            self.settings, on_changed=self._on_license_changed,
        )
        self._license_dialog.show()
        self._license_dialog.raise_()
        self._license_dialog.activateWindow()

    def _on_license_changed(self, _section: str = "general") -> None:
        self._license_state = None            # neu bewerten
        try:
            self.panel.refresh_license()
        except Exception:
            log.debug("Lizenzzeile liess sich nicht nachziehen.", exc_info=True)
        if self._license_ok():
            self._flash_status("Fleech ist freigeschaltet.")

    # -- Updates ---------------------------------------------------------------------

    def _check_updates_async(self) -> None:
        """Im Hintergrund pruefen und — wenn erlaubt — gleich laden.

        Alles Netz- und Dateiwerk laeuft im Thread; die UI erfaehrt das Ergebnis nur
        ueber `bus.update_ready`. Ein nicht erreichbarer Server ist kein Ereignis:
        gemeldet wird nur, wenn es wirklich eine neue Version gibt.
        """
        if not self.settings.advanced.auto_update_check:
            return
        if self._pending_update is not None:
            return                       # schon gefunden — nicht erneut suchen
        bus, settings = self.bus, self.settings

        def work():
            from .updates import check_for_updates, download_update, update_token
            from .updatedialog import UPDATE_DIR

            marke = update_token(settings)
            try:
                info = check_for_updates(settings.advanced.update_feed_url or None,
                                         token=marke)
            except Exception:
                log.debug("Update-Pruefung fehlgeschlagen.", exc_info=True)
                return
            if info.get("status") != "update_available":
                log.info("Update-Pruefung: %s (installiert %s).",
                         info.get("status"), info.get("current"))
                return
            log.info("Update %s verfuegbar.", info.get("latest"))
            datei = ""
            if settings.advanced.auto_update_download:
                pfad = download_update(
                    info.get("url", ""), UPDATE_DIR,
                    on_progress=lambda p, t: None,      # still: niemand wartet darauf
                    expected_size=int(info.get("size") or 0),
                    expected_sha256=str(info.get("sha256") or ""),
                    token=marke, dateiname=str(info.get("name") or ""),
                )
                datei = str(pfad) if pfad else ""
            bus.update_ready.emit(info, datei)

        threading.Thread(target=work, daemon=True, name="fleech-update-check").start()

    def _on_update_ready(self, info, datei: str) -> None:
        """UI-Thread: Tray-Eintrag zeigen und einmal darauf hinweisen."""
        self._pending_update = dict(info or {})
        self._update_file = Path(datei) if datei else None
        version = self._pending_update.get("latest", "")
        try:
            self.tray.show_update(version, self._update_file is not None)
        except Exception:
            log.debug("Tray-Update-Eintrag fehlgeschlagen.", exc_info=True)
        text = (f"Version {version} ist geladen und kann installiert werden."
                if self._update_file is not None
                else f"Version {version} ist verfügbar.")
        self.notifier.toast("background_info", "Fleech-Update", text)

    def show_update_dialog(self) -> None:
        """Update-Dialog oeffnen (Tray-Eintrag oder Einstellungen)."""
        from .updatedialog import UpdateDialog

        info = getattr(self, "_pending_update", None)
        if not info:
            self._check_updates_async()
            return
        vorhanden = getattr(self, "_update_dialog", None)
        if vorhanden is not None and vorhanden.isVisible():
            vorhanden.raise_()
            vorhanden.activateWindow()
            return
        self._update_dialog = UpdateDialog(
            info, on_quit=self._quit, fertige_datei=self._update_file,
            settings=self.settings,
        )
        self._update_dialog.show()
        self._update_dialog.raise_()
        self._update_dialog.activateWindow()

    def _quit(self) -> None:
        self._stoppe_freihand()
        self.controller.stop_if_active()
        self.settings.save()
        self.hotkeys.stop()
        QApplication.instance().quit()


IPC_NAME = "Fleech.ipc"


def _wake_running_instance() -> bool:
    """Weckt die laufende Instanz (oeffnet dort das Settings-Fenster)."""
    try:
        from PySide6.QtNetwork import QLocalSocket

        sock = QLocalSocket()
        sock.connectToServer(IPC_NAME)
        if not sock.waitForConnected(1500):
            return False
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return True
    except Exception:
        log.debug("Wake der laufenden Instanz fehlgeschlagen.", exc_info=True)
        return False


def _apply_dark_theme(app) -> None:
    """Durchgehender Dark Mode (Fusion + Brand-Palette) — gilt fuer alle Fenster
    inkl. der Standard-Widgets im Settings-Panel."""
    from PySide6.QtGui import QColor, QFont, QPalette

    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))
    pal = QPalette()
    bg, card, text, muted = "#16181C", "#22262E", "#E8E8EC", "#8A8A92"
    pal.setColor(QPalette.Window, QColor(bg))
    pal.setColor(QPalette.WindowText, QColor(text))
    pal.setColor(QPalette.Base, QColor(card))
    pal.setColor(QPalette.AlternateBase, QColor("#1A1D22"))
    pal.setColor(QPalette.Text, QColor(text))
    pal.setColor(QPalette.PlaceholderText, QColor(muted))
    pal.setColor(QPalette.Button, QColor(card))
    pal.setColor(QPalette.ButtonText, QColor(text))
    pal.setColor(QPalette.ToolTipBase, QColor(card))
    pal.setColor(QPalette.ToolTipText, QColor(text))
    pal.setColor(QPalette.Highlight, QColor("#35C0D8"))
    pal.setColor(QPalette.HighlightedText, QColor(bg))
    pal.setColor(QPalette.Link, QColor("#35C0D8"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor("#5A5C64"))
    app.setPalette(pal)
    from .chevron import apply_chevrons

    app.setStyleSheet(apply_chevrons(_GLOBAL_QSS))


# Global gestylte Standard-Widgets: schlanke Scrollbars (ohne Pfeil-Buttons) und
# dunkle Spinbox-Schaltflaechen mit gemalten Dreieck-Pfeilen — gilt fuer ALLE Fenster
# (Home/Insights-Scroll UND Settings), damit das Dark-Design durchgaengig ist.
_GLOBAL_QSS = """
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px 2px 2px 0; }
QScrollBar::handle:vertical {
    background: rgba(255,255,255,0.13); border-radius: 4px; min-height: 34px;
}
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.28); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; width: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 0 2px 2px 2px; }
QScrollBar::handle:horizontal {
    background: rgba(255,255,255,0.13); border-radius: 4px; min-width: 34px;
}
QScrollBar::handle:horizontal:hover { background: rgba(255,255,255,0.28); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; height: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QAbstractSpinBox {
    background: #22262E; color: #E8E8EC; border: 1px solid #2E3742;
    border-radius: 6px; padding: 3px 6px;
}
QAbstractSpinBox:focus { border-color: #219FB8; }
QAbstractSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right; width: 20px;
    border: none; border-left: 1px solid #2E3742; border-top-right-radius: 6px;
}
QAbstractSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right; width: 20px;
    border: none; border-left: 1px solid #2E3742; border-bottom-right-radius: 6px;
}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover { background: #243A40; }
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed { background: #1A1D22; }
QAbstractSpinBox::up-arrow { width: 9px; height: 9px; image: url(__CHEV_UP__); }
QAbstractSpinBox::up-arrow:hover { image: url(__CHEV_UP_HL__); }
QAbstractSpinBox::down-arrow { width: 9px; height: 9px; image: url(__CHEV_DOWN__); }
QAbstractSpinBox::down-arrow:hover { image: url(__CHEV_DOWN_HL__); }
QToolTip {
    background: #1F232B; color: #E8E8EC; border: 1px solid #2E3742;
    border-radius: 6px; padding: 6px 8px; font-size: 9pt;
}
"""


def run_desktop() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Kern des Tray-Modells
    app.setApplicationName("Fleech")
    app.setApplicationDisplayName("Fleech")
    app.setOrganizationName("Fleech")
    _apply_dark_theme(app)

    from ..singleinstance import SingleInstanceLock

    lock = SingleInstanceLock()
    if not lock.acquire():
        woke = _wake_running_instance()
        log.warning(
            "Fleech laeuft bereits — %s",
            "Einstellungen der laufenden Instanz geoeffnet." if woke
            else "zweite Instanz beendet sich.",
        )
        return 0

    from PySide6.QtGui import QIcon

    from ..resources import app_icon_path

    icon = QIcon(str(app_icon_path()))
    if not icon.isNull():
        app.setWindowIcon(icon)

    if sys.platform == "win32":
        # Eigene AppUserModelID → Windows gruppiert Taskbar/Startmenue als "Fleech".
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Fleech.DictationApp")
        except Exception:
            pass

    try:
        desktop = DesktopApp()
        desktop.attach_instance_lock(lock)
        desktop._start_ipc_server()
        # Erststart: Fenster zeigen; danach startet die App still in den Tray.
        if desktop.settings.window.x is None:
            desktop.window.show()
        # Einfuehrung beim ersten Start (bzw. bis sie einmal weggeklickt wurde).
        # Nach app.exec-Start via Timer, damit der Event-Loop schon laeuft.
        if not desktop.settings.general.onboarding_done:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(400, desktop.show_onboarding)
        return app.exec()
    finally:
        lock.release()
