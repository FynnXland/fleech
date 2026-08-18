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
        if check.ok:
            log.info("Aufnahmegeraet geprueft: %s — in Ordnung.", check.name)
            return
        log.error("⚠ Aufnahmegeraet '%s': %s", check.name, check.reason)
        self.tray.notify("Fleech — Aufnahmegerät", f"„{check.name}“: {check.reason}")

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
        self.settings.save()
        self.hotkeys.stop()
        QApplication.instance().quit()
