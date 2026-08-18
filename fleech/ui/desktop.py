"""DesktopApp: verdrahtet Engine (Recorder/Pipeline/Fokus/Preview) mit der Qt-UI.

Thread-Modell:
- Qt-Main-Thread: Tray, Overlay, Settings-Fenster.
- pynput-Listener-Thread: uebersetzt Hotkeys via RecordingController in start/stop.
- Worker-Threads: Pipeline-Verarbeitung, Ducking-Fades, Preview-Streamer.
Alle UI-Updates laufen ueber StateBus-Signale (Queued Connections, thread-sicher).
"""

from __future__ import annotations

import logging
import sys
import threading
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ..app import DictationApp
from ..audio import Recorder, list_input_devices
from ..config import load_config
from ..hotkey import HotkeyManager, HotkeySpec
from ..profiles import AUTO_SEND_MODES, REWRITING_FORMATS
from ..recording_control import RecordingController
from ..stt import create_stt
from ..usersettings import UserSettings
from ..history import DictationRecord, HistoryStore
from .main_window import MainWindow
from .notifications import NotificationPolicy, Notifier
from .overlay_qt import OverlayWindow
from .sounds import SoundPlayer
from .state import AppState, StateBus
from .settings_window import SettingsPanel
from .tray import TrayController
from .desktopapp import (
    FreihandMixin, KeinTonMixin, LebenszyklusMixin, LizenzUpdateMixin, ModelleMixin,
    NachbereitungMixin, ProfilMixin,
)
# Der Name des IPC-Kanals gehoert zum Server (desktopapp/lebenszyklus.py). Hier
# re-exportiert, weil `packaging/stop_fleech.py` ihn von `fleech.ui.desktop` holt —
# und weil `_wake_running_instance()` unten die Gegenstelle ist.
from .desktopapp.lebenszyklus import IPC_NAME  # noqa: F401
from .windowsfocus import MAX_TITLE_LEN, FocusProbe

log = logging.getLogger(__name__)


class DesktopApp(
    ProfilMixin, FreihandMixin, KeinTonMixin, ModelleMixin, NachbereitungMixin,
    LizenzUpdateMixin, LebenszyklusMixin,
):
    """Verdrahtung der App: Aufbau, Aufnahme-Lebenszyklus, Hotkeys, Fenster.

    Die Teilgebiete liegen in `ui/desktopapp/` — dort steht auch, warum sie als
    Mixins und nicht als eigene Controller-Objekte angebunden sind.
    """

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
            # late-bound (Mic-Wechsel!) und BEIDE Aufnahmewege — und im selben
            # 50-ms-Takt laeuft die Kein-Ton-Wache mit (desktopapp/keinton.py).
            level_provider=self._pegel_fuer_pille,
        )
        self.overlay.cancel_requested.connect(self._cancel_recording)
        self.overlay.finish_requested.connect(self._finish_recording)
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
            wortprobe_fn=self.wortprobe,
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
        self.bus.freihand_fehler.connect(self._on_freihand_fehler)
        self.bus.preview_text.connect(self._on_preview_text)
        self.bus.dictionary_suggestion.connect(self._on_dictionary_suggestion)
        self.bus.update_ready.connect(self._on_update_ready)
        self.bus.profile_key.connect(self._on_profile_key)
        self.bus.license_needed.connect(self.show_license_dialog)
        self.bus.paused_changed.connect(self.overlay.set_paused)
        self.bus.prompt_latch_changed.connect(self.overlay.set_prompt_latched)
        self.bus.profil_zuruecksetzen.connect(self._on_profil_zuruecksetzen)
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
            from ..freihand import STILLGELEGT, woerter_als_text

            # Befund E-8: Solange Freihand stillgelegt ist, lauscht nichts — dann
            # darf das Tray auch nicht „Freihand: an" melden. Bei einer Funktion,
            # deren ganzer Sinn Vertrauen ist, ist genau diese Richtung der
            # falschen Anzeige die unangenehme.
            self.tray.set_freihand(self.settings.freihand.aktiv and not STILLGELEGT,
                                   woerter_als_text(self.settings.freihand.startwort))
        except Exception:
            log.debug("Tray-Text nicht setzbar.", exc_info=True)
        self._starte_freihand()
        self._starte_stille_wache()
        # Ring am Punkt gleich beim Start faerben — sonst bliebe er bis zum
        # ersten Profilwechsel grau, obwohl laengst ein Profil gilt.
        self._melde_profilfarbe()
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

        # Kein Preview-Streamer mehr: die Overlay-Pille zeigt den Audiopegel statt
        # Live-Text (Nutzer-Entscheid) — spart das separate Whisper-Preview-Modell
        # (~0,5 GB VRAM + Warmup). Streaming-Vorschau gibt es weiter im --cli-Modus.


    # -- Live-Vorschau (Opt-in) ---------------------------------------------------------


    _preview_gen = 0  # Generationszaehler gegen Start/Stop-Races (Load dauert Sekunden)







    # Smart-Modus: solange nach dem letzten Diktat aktiv warmhalten. Laeuft das
    # (einstellbare) Idle-Fenster ab ODER laeuft ein Spiel (Gaming-Erkennung), werden
    # die Modelle AKTIV entladen (keep_alive=0) — statt bis zu 30 min keep_alive
    # nachlaufen zu lassen. Beim Zocken zaehlt jedes GB: Ollama haelt sonst ~9 GB im
    # Speicher, obwohl waehrenddessen nicht diktiert wird.










    # ------------------------------------------------------------------ Aufnahme --

    def _on_record_start(self, kind: str) -> None:
        # Lizenz zuerst: ohne gueltigen Schluessel wird nicht aufgenommen. Bewusst
        # HIER und nicht tiefer in der Pipeline — es soll gar nichts erst ins
        # Mikrofon gehen, und der Nutzer bekommt sofort den Dialog statt einer
        # Fehlermeldung nach dem Sprechen.
        if not self._license_ok():
            # `cancel()` statt `stop_if_active()` (Befund D-10): Letzteres laeuft in
            # den vollen Stopp-Weg — Stoppton, Zustand PROCESSING und ein Worker mit
            # 0 Samples, der eine Zehntelsekunde spaeter „nichts erkannt" in die
            # Pille schreibt und damit die Meldung ueberdeckt, die weiterhelfen wuerde.
            self.controller.cancel()
            # NICHT direkt aufrufen: diese Methode laeuft im pynput-Listener-Thread.
            self.bus.license_needed.emit()
            return
        # `may_record` blockiert seit v3.0.0 nichts mehr (der Cloud-Formel-Weg ist
        # weg) — es bleibt die Warnung bei einem Loopback-/Mix-Geraet. Der frueher
        # hier stehende Abbruchzweig war damit tot (Befund D-10); die Nahtstelle
        # bleibt, die Warnung auch.
        _, message = self.focus.may_record(math_mode=False)
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
            self.controller.cancel()   # kein Geister-Diktat (Befund D-10)
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
        # Kein-Ton-Wache scharf machen: die Warnung gilt je Aufnahme. Bewusst nur
        # das Flag — die Pille selbst raeumt `set_app_state` auf, denn diese
        # Methode laeuft im pynput-Thread (Befund D-6).
        self._kein_ton_gemeldet = False
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
        # in den Normalzustand zurueck.
        prompt_oneshot, self._prompt_oneshot = self._prompt_oneshot, False
        if prompt_oneshot:
            # Ueber den Bus: im Hold-Modus kommt auch dieser Weg aus dem
            # pynput-Thread, und die Pille ist ein Qt-Widget (Befund D-6).
            self.bus.prompt_latch_changed.emit(False)
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
        lauscher = self._freihand_lauscher()
        if lauscher is not None and lauscher.verwirf_vorzeitig():
            log.info("Freihand-Diktat per Pille verworfen.")
            self._stop_preview()
            return
        kind = self.controller.cancel()
        if kind is None:
            # Der Klick kam an, aber es lief nichts mehr. Das MUSS sichtbar sein:
            # Genau dieser Fall („Pille schon weg, Klick ins Leere") war als
            # „Abbrechen funktioniert nicht" gemeldet — und stand nirgends.
            log.info("Abbrechen ohne laufende Aufnahme — nichts zu verwerfen.")
            return
        self._prompt_oneshot = False
        # Hier ausnahmsweise direkt: dieser Weg haengt am X der Pille, kommt also
        # ohnehin aus dem GUI-Thread (anders als `_on_record_stop`, Befund D-6).
        self.overlay.set_prompt_latched(False)
        self._stop_preview()
        threading.Thread(target=self.focus.on_recording_stop, daemon=True).start()
        self.recorder.stop()  # Audio bewusst verwerfen
        self.bus.set_state(AppState.IDLE, "verworfen")
        log.info("Aufnahme verworfen (%s).", kind)


    # -- Profil-Umschaltung (Punkt in der Pille) --------------------------------------







    # -- Profil-Hotkey: tippen = weiterschalten, halten = Auswahlliste --------------






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
            # KI-Prompting ausserhalb eines Profils: nur noch der One-Shot (Hotkey
            # WAEHREND der Aufnahme, gilt fuer genau dieses Diktat). Dauerhaft
            # macht das heute das Profil „KI-Prompt". Einen Formel-Modus gibt es
            # seit v3.0.0 nicht mehr — Formeln werden vor dem Cleanup determi-
            # nistisch uebersetzt und brauchen kein Umschalten.
            prompt_active = prompt_oneshot
            # Ausgabeformat des Profils: die umformulierenden Formate schreiben das
            # Diktat ueber einen eigenen System-Prompt um, statt es nur zu glaetten.
            # Befund E-3: Hier stand ein hartes ("email", "prompt") — „Stichpunkte"
            # kam spaeter dazu und fiel deshalb still auf normales Cleanup zurueck.
            # Jetzt gilt die EINE Liste, die auch die Pipeline kennt.
            output_format = slot_mode if slot_mode in REWRITING_FORMATS else ""
            # Gesprochenes Safe-Word je Profil abschaltbar (Meetings/Grossraum): der
            # »-Knopf bleibt immer nutzbar, nur das laute Wort entfaellt.
            suppress_command = not prof.command_allowed(
                self.settings.output.command_enabled
            )
            # Diktiersprache: Profil schlaegt Einstellung. Sie steuert dreierlei —
            # die Erkennung, den sprachgebundenen Teil der Guards und die
            # Zielsprache der umformulierenden Formate.
            self._setze_sprache(prof.sprache or self.settings.general.language)
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
                # Warum, unter welchem Profil, in welchem Fenster — und was die
                # Roh-Guards weggeschnitten haben (V-1). Der Titel haengt an
                # derselben Schranke wie der uebrige Verlauf (`save_history`, die
                # Bedingung oben) und wird wie dort gekuerzt: kein zweiter Weg.
                reason=self.pipeline.last_reason,
                profile=prof.name,
                title=(getattr(self, "_record_title", "") or "")[:MAX_TITLE_LEN],
                dropped=self.pipeline.last_dropped_tail,
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
            # Befund E-2: Die Bedingung war auf "cleanup" allein — ausgerechnet in
            # den Profilen, fuer die der Haken gedacht ist (KI-Prompt, Stichpunkte),
            # feuerte er nie. „email" bleibt bewusst draussen: Eine Mail, die sich
            # selbst abschickt, ist ein Versehen mit Folgen — genau davor warnt der
            # Hilfetext am Schalter.
            if prof.auto_send and result == "ok" \
                    and self.pipeline.last_mode in AUTO_SEND_MODES:
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
            if self.pipeline.last_error_kind == "llm_offline":
                self._melde_ki_offline()
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
        """Hotkey gedrueckt. Der Modus-Hotkey (KI-Prompting) wirkt NUR waehrend
        einer laufenden Aufnahme — ausserhalb wird er bewusst ignoriert, damit
        dieselbe Taste (z. B. eine Corsair-G-Taste) ausserhalb von Fleech frei fuer
        andere Dinge belegbar bleibt. Dauerhaft schaltet man den Modus, indem man
        das Profil „KI-Prompt" waehlt — der Punkt in der Pille wechselt seit 5.10.2
        nur noch das Profil, nicht mehr das Prompting selbst (E-19).
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



    # -- Nachbearbeitung aus dem Verlauf (F3) ------------------------------------------



    def _flash_status(self, text: str) -> None:
        """Kurze Rueckmeldung ueber die Pille — thread-sicher ueber den StateBus."""
        try:
            self.bus.progress.emit(text)
        except Exception:
            log.debug("Statusmeldung fehlgeschlagen.", exc_info=True)

    def _toggle_prompt_oneshot(self) -> None:
        """KI-Prompting NUR fuer die laufende Aufnahme markieren (Hotkey mitten im
        Diktat). Kein persistenter Latch: nach der Verarbeitung (oder Abbruch) faellt
        der Modus automatisch zurueck — die Pille zeigt solange amber."""
        self._prompt_oneshot = not self._prompt_oneshot
        on = self._prompt_oneshot
        # Den dauerhaften Latch gab es hier bis 5.10.2 noch als Feld — ohne jeden
        # Aufrufer, seit der Punkt in der Pille das Profil wechselt. Entfernt.
        # Ueber den Bus, nicht direkt ans Overlay: Dieser Weg kommt aus dem
        # pynput-Thread (Befund D-6).
        self.bus.prompt_latch_changed.emit(on)
        self.notifier.sound("start" if on else "stop")
        log.info("KI-Prompting fuer DIESES Diktat %s.", "an" if on else "aus")

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
        if section == "profiles":
            # Farbe oder aktives Profil geaendert — der Ring an der Pille zeigt
            # sonst noch die alte Farbe, bis man das naechste Mal umschaltet.
            self._melde_profilfarbe()
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
            self.recorder.on_device_fallback = self._melde_mikrofon_rueckfall
            # Overlay-Waveform folgt automatisch (level_provider ist late-bound).
            self._recheck_input_device()
        elif section == "stt_device":
            self.controller.stop_if_active()
            self.config.stt.device = "auto" if self.settings.advanced.prefer_gpu else "cpu"
            self.pipeline.stt = create_stt(self.config.stt)
            threading.Thread(target=self._warm_up_stt, daemon=True).start()
        # Overlay-Tooltip (Bedienmodus/Fokus/Mathe/Eingriff) aktuell halten.
        self._update_mode_line()


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
            f"{ {'hold': 'Hold', 'toggle': 'Toggle'}.get(s.recording.mode, 'Anstupsen') } | "
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
        lauscher = self._freihand_lauscher()
        if lauscher is not None:
            # Freihand-Diktat: Der Recorder laeuft hier nicht, der Knopf lief also
            # ins Leere („Pause ignoriert"). Die Stille-Uhr ruht mit — sonst waere
            # das Diktat nach `stille_s` beendet, waehrend man noch spricht.
            an = not lauscher.diktat_pausiert
            if lauscher.pausiere_diktat(an):
                log.info("Freihand-Diktat %s.", "pausiert" if an else "fortgesetzt")
                self.bus.paused_changed.emit(an)
                self.notifier.sound("stop" if an else "start")
            return
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

    def _setze_sprache(self, sprache: str) -> None:
        """Diktiersprache fuer diesen Durchlauf setzen.

        "auto" heisst: Whisper erkennt selbst (`language=None`). Fuer die Guards
        gilt dann Deutsch als Erwartung — das ist die Sprache, in der hier real
        diktiert wird, und ein falsch geratener Guard schneidet lieber nichts als
        zu viel.
        """
        sprache = (sprache or "de").lower()
        stt = "" if sprache == "auto" else sprache
        try:
            self.config.stt.language = stt
            if getattr(self.pipeline, "stt", None) is not None:
                self.pipeline.stt.cfg.language = stt
        except Exception:
            log.debug("STT-Sprache nicht setzbar.", exc_info=True)
        self.pipeline.sprache = "de" if sprache == "auto" else sprache

    def _finish_recording(self) -> None:
        """Overlay-Haken: fertig — je nachdem, welcher Weg gerade aufnimmt."""
        lauscher = self._freihand_lauscher()
        if lauscher is not None and lauscher.beende_vorzeitig():
            log.info("Freihand-Diktat per Pille beendet.")
            return
        self.controller.stop_if_active()

    def _nudge_tick(self) -> None:
        """GUI-Thread. Nur billige Arbeit: VAD auf einer Sekunde Audio (1–4 ms)."""
        try:
            if self.settings.recording.mode != "nudge" or not self.controller.active:
                wache = getattr(self, "_stillewache", None)
                if wache is not None and wache.laeuft:
                    wache.stop()
                return
            wache = self._hole_stillewache()
            if wache is None:
                return
            jetzt = time.monotonic()
            if not wache.laeuft:
                wache.start(jetzt)
                return
            if self.recorder.paused:
                # Pause heisst ausdruecklich „ich rede gerade woanders" — genau
                # dann darf die Stille das Diktat nicht beenden.
                wache.start(jetzt)
                return
            from ..freihand import VAD_FENSTER_S

            if wache.fertig(self.recorder.tail(VAD_FENSTER_S), jetzt):
                log.info("Anstupsen: %.1f s still — Diktat beendet.", wache.stille_s)
                wache.stop()
                self.controller.stop_if_active()
        except Exception:
            log.exception("Stille-Wache fehlgeschlagen — Aufnahme laeuft weiter.")

    def _starte_stille_wache(self) -> None:
        """Timer, der im Anstupsen-Modus auf das Ende der Rede achtet.

        Laeuft DAUERHAFT und prueft selbst, ob gerade etwas zu tun ist — statt
        beim Aufnahmestart gestartet zu werden. Grund: `_on_record_start` laeuft
        im pynput-Listener-Thread, und ein QTimer darf nur aus dem GUI-Thread
        gestartet werden. Ein Tick, der sofort mit „laeuft nichts" zurueckkommt,
        kostet nichts.
        """
        from PySide6.QtCore import QTimer

        self._stillewache = None
        self._stillewache_laedt = False
        # OHNE Parent: `DesktopApp` ist kein QObject, sondern die einfache Klasse,
        # die alles verdrahtet. `QTimer(self)` wirft deshalb beim Start —
        # genau wie die anderen Timer hier steht er ohne Parent und wird ueber
        # das Attribut am Leben gehalten.
        self._nudge_timer = QTimer()
        self._nudge_timer.setInterval(300)
        self._nudge_timer.timeout.connect(self._nudge_tick)
        self._nudge_timer.start()

    def _hole_stillewache(self):
        """Die Wache, oder None solange das VAD noch laedt.

        Silero kommt aus faster-whisper und braucht beim ersten Zugriff einen
        Moment. Das im GUI-Thread zu tun wuerde die Oberflaeche einfrieren —
        genau in dem Augenblick, in dem der Nutzer gerade zu sprechen anfaengt.
        """
        wache = getattr(self, "_stillewache", None)
        if wache is not None:
            wache.stille_s = self.settings.freihand.stille_s
            return wache
        if self._stillewache_laedt:
            return None
        self._stillewache_laedt = True

        def laden():
            try:
                import numpy as _np

                from ..freihand import SAMPLERATE, baue_vad
                from ..stillewache import Stillewache

                vad = baue_vad()
                # Einmal warmlaufen lassen — HIER, im Hintergrund. Gemessen kostet
                # der erste Aufruf 185 ms, jeder weitere 1,4 ms. Diese 185 ms im
                # GUI-Thread waeren ein sichtbarer Hänger, genau in dem Moment, in
                # dem der Nutzer zu sprechen anfaengt.
                vad(_np.zeros(SAMPLERATE, dtype=_np.float32))
                self._stillewache = Stillewache(
                    vad, stille_s=self.settings.freihand.stille_s,
                    samplerate=self.config.audio.samplerate)
                log.info("Stille-Wache bereit (Anstupsen-Modus).")
            except Exception:
                log.exception("Stille-Wache nicht ladbar — Anstupsen endet nur "
                              "per Tastendruck.")
            finally:
                self._stillewache_laedt = False

        threading.Thread(target=laden, daemon=True).start()
        return None

    # -- Freihand-Modus (F1) -----------------------------------------------------------








    # -- Lizenz ----------------------------------------------------------------------




    # -- Updates ---------------------------------------------------------------------









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

    desktop = None
    try:
        try:
            desktop = DesktopApp()
        except Exception:
            # Ein Startfehler MUSS ins Protokoll. Bis 5.8.0 flog der Traceback nur
            # auf stderr — bei der gepackten EXE gibt es dort niemanden, der
            # zusieht. Im Protokoll stand dann bloss, wie weit der Start gekommen
            # war, und alles sah nach einem sauberen Lauf aus. Real passiert:
            # `QTimer(self)` in `_starte_stille_wache` (DesktopApp ist kein
            # QObject) legte den Start lahm, und die Diagnose lief ins Leere.
            log.exception("Fleech konnte nicht starten.")
            # Und der Tastatur-Hook muss weg. `HotkeyManager.start()` laeuft frueh
            # in __init__; bricht es danach ab, haengt ein Low-Level-Hook in einem
            # halbtoten Prozess und schluckt oder verdoppelt Tastendruecke —
            # gemeldet als „komische Tastatureingaben beim Starten". An die
            # halbfertige Instanz kommt hier niemand heran, deshalb die Registry
            # in HotkeyManager.
            try:
                offen = HotkeyManager.stop_all()
                if offen:
                    log.info("%d Tastatur-Listener nach dem Startfehler geschlossen.",
                             offen)
            except Exception:
                log.debug("Hotkeys nicht abraeumbar.", exc_info=True)
            raise
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
        # Positive Startbestaetigung. Ohne sie laesst sich ein geglueckter Start
        # nicht vom abgebrochenen unterscheiden: „Prozess laeuft" und „keine
        # ERROR-Zeile" waren beide erfuellt, WAEHREND die App tot war.
        from ..version import APP_VERSION

        log.info("Fleech %s bereit — Oberflaeche steht.", APP_VERSION)
        return app.exec()
    finally:
        lock.release()
