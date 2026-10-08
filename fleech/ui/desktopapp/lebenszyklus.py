"""Fenster, zweite Instanz, Neustart, Beenden — die App als laufender Prozess.

Fleech ist eine Tray-App: Fenster schliessen heisst nicht beenden. Genau daraus
folgt der Rest dieses Moduls — es gibt immer nur EINE Instanz, ein zweiter Start
weckt stattdessen die laufende (`_on_ipc_wake`), und `_quit` ist der einzige Weg
hinaus.

Mixin statt eigener Klasse: siehe `desktopapp/__init__.py`.
"""

from __future__ import annotations

import logging
import os
import sys

from PySide6.QtWidgets import QApplication

from ...audio import list_input_devices

log = logging.getLogger(__name__)

# Name des lokalen IPC-Kanals. Ueber ihn weckt ein Zweitstart die laufende Instanz,
# und `packaging/stop_fleech.py` bittet sie, sich selbst zu beenden — der einzige
# ordentliche Weg, Fleech zu stoppen (ein hartes Kill kann einen laufenden
# settings.save() treffen).
IPC_NAME = "Fleech.ipc"


class LebenszyklusMixin:
    def show_onboarding(self) -> None:
        """Einfuehrungs-Wizard zeigen (Erststart oder aus den Einstellungen).

        Nicht-modal mit gehaltener Referenz: exec() wuerde den Event-Loop
        verschachteln, waehrend Hotkeys/Poll weiterlaufen — unnoetiges Risiko."""
        from ..onboarding import OnboardingDialog

        existing = getattr(self, "_onboarding", None)
        if existing is not None and (existing.isVisible()
                                     or existing.einrichtung_laeuft()):
            # Laeuft noch ein Download aus der letzten Einfuehrung, waere eine
            # zweite Einrichtung ein zweiter, paralleler Download desselben Modells.
            if not existing.isVisible():
                existing.zeige_einrichtung()
                existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        self._onboarding = OnboardingDialog(
            self.settings, list_input_devices, on_changed=self._on_setting_changed,
            einrichtung=self._einrichtungsplan,
            # Fuer die Liste installierter Modelle: das eigene Ollama, auch wenn
            # gerade ein Cloud-Anbieter gewaehlt ist.
            llm_base_url=(self.config.llm_cleanup.base_url if self._ki_lokal()
                          else "http://127.0.0.1:11434"),
            on_ready=self._warm_up_after_setup,
            hotkey_capture_guard=(lambda: self.hotkeys.stop(),
                                  lambda: self.hotkeys.start()),
        )
        self._onboarding.show()
        self._onboarding.raise_()
        self._onboarding.activateWindow()

    def _einrichtungsplan(self) -> tuple:
        """Was die Einfuehrung laden muss — gefragt NACH der KI-Wahl.

        Cloud-Anbieter oder „Ohne KI": nichts Lokales einzurichten — leere
        Adresse heisst fuer die Einrichtung „nur die Spracherkennung"."""
        endpoints = self._llm_endpoints() if self._ki_lokal() else []
        base_url = getattr(endpoints[0], "base_url", "") if endpoints else ""
        return endpoints, getattr(self.config.stt, "model_size", ""), base_url

    def _einfuehrung_offen(self) -> bool:
        """Ist die Einfuehrung zu sehen oder laedt sie noch? Dann haelt sich das
        Warmhalten mit eigenen Downloads zurueck — sonst laedt Fleech das
        Vorgabemodell, bevor der Nutzer ueberhaupt gewaehlt hat."""
        dlg = getattr(self, "_onboarding", None)
        if dlg is None:
            return False
        try:
            return dlg.isVisible() or dlg.einrichtung_laeuft()
        except RuntimeError:                   # Qt-Objekt schon geloescht
            return False

    def _recheck_input_device(self) -> None:
        """Loopback-Pruefung nach einem Geraetewechsel erneuern.

        Der DeviceCheck wurde bisher NUR einmal beim App-Start gemacht: Wer im
        laufenden Betrieb auf „Stereomix" umstellte, bekam weder Warnung noch die
        Formel-Sperre — der Controller trug bis zum Neustart das Urteil ueber das
        ALTE Geraet. Umgekehrt blieb eine einmal gezeigte Warnung stehen, obwohl
        laengst ein echtes Mikrofon gewaehlt war.

        Befund B-3: Das neue Urteil landete auf `self.controller` (dem
        RecordingController) — einem Objekt ohne dieses Feld. Es legte dort still
        ein Attribut an, das niemand liest. Gelesen wird `device_check` allein vom
        AudioFocusController (`may_record`, `status_line`), also `self.focus`."""
        from ...audiofocus import DeviceCheck, DeviceGuard

        device = self.settings.recording.microphone
        blocklist = self.settings.recording.blocked_devices
        try:
            check = DeviceGuard.check(device, blocklist)
        except Exception as exc:
            check = DeviceCheck(ok=True, name=f"<unbekannt: {exc}>")
        if getattr(self, "focus", None) is not None:
            self.focus.device_check = check
        # Die Sperrliste gehoert in die Config, aus der der naechste DeviceGuard
        # gebaut wird — sonst zieht eine gerade ergaenzte Zeile erst nach einem
        # Neustart.
        self.config.audio_focus.blocked_devices = list(blocklist or [])
        self._mikrofon_rueckfall = ""   # neues Geraet → Rueckfall neu bewerten
        if check.ok:
            log.info("Aufnahmegeraet geprueft: %s — in Ordnung.", check.name)
            return
        log.error("⚠ Aufnahmegeraet '%s': %s", check.name, check.reason)
        self.tray.notify("Fleech — Aufnahmegerät", f"„{check.name}“: {check.reason}")

    def _melde_mikrofon_rueckfall(self, benutzt: str) -> None:
        """Das gewaehlte Mikrofon ist weg — aufgenommen wird ueber den Systemstandard.

        Befund B-7: Bisher stand das nur als `log.warning` im Protokoll (dort 86-mal).
        Interface aus, Rechner aus dem Standby, USB-Hub neu enumeriert — ab dann lief
        das Diktat ueber die Webcam, ohne ein Wort darueber; aufgefallen ist es nur an
        schlechter Erkennung.

        Einmal je Geraet melden, nicht bei jedem Diktat: Bis zum naechsten
        Geraetewechsel aendert sich nichts, und eine Meldung bei jedem Aufnahmestart
        waere selbst eine Stoerung. Der Aufruf kommt aus dem pynput-Thread — deshalb
        ueber den StateBus (`_flash_status`) statt direkt an die Pille.

        Die geaenderte Statuszeile bleibt bis zum naechsten Geraetewechsel stehen.
        Das ist richtig so: PortAudio haelt seine Geraeteliste seit dem Start fest,
        ein wieder eingestecktes Mikrofon ist fuer Fleech in dieser Sitzung ohnehin
        nicht vorhanden.
        """
        gewaehlt = self.settings.recording.microphone or "Systemstandard"
        benutzt = benutzt or "Systemstandard"
        if getattr(self, "_mikrofon_rueckfall", "") == benutzt:
            return
        self._mikrofon_rueckfall = benutzt
        log.error("Mikrofon '%s' nicht verfuegbar — aufgenommen wird ueber '%s'.",
                  gewaehlt, benutzt)
        # Die Statuszeile trug den GEWAEHLTEN Namen; hier zaehlt, was wirklich aufnimmt.
        if getattr(self, "focus", None) is not None:
            self.focus.device_check.name = f"{benutzt} (statt „{gewaehlt}“)"
        self._flash_status(f"Mikrofon „{gewaehlt}“ fehlt — nehme über {benutzt} auf")

    def _stelle_lautstaerken_her(self) -> None:
        """Fremde Apps vor dem Beenden wieder laut machen (Befund D-5).

        `_on_record_stop` startet die Wiederherstellung nur als Daemon-Thread
        (Fade ~250 ms). Wer Fleech mitten in einer Aufnahme beendet — der uebliche
        Deploy-Ablauf —, war vorher weg, bevor der Fade durch war: Discord, Spotify
        und Steam blieben auf einem Viertel, auch nach dem Neustart.

        Hier synchron nachziehen. `PlaybackDucker.restore()` haelt dasselbe Schloss
        wie der Fade und ist idempotent — der Aufruf wartet also auf einen schon
        laufenden Fade und laeuft sonst leer.
        """
        try:
            if getattr(self, "focus", None) is not None:
                self.focus.on_recording_stop()
        except Exception:
            log.debug("Lautstaerken beim Beenden nicht zuruecksetzbar.", exc_info=True)

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

    def _quit(self) -> None:
        self._stoppe_freihand()
        self.controller.stop_if_active()
        self._stelle_lautstaerken_her()
        self.settings.save()
        self.hotkeys.stop()
        QApplication.instance().quit()
