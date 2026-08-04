"""Lizenzschluessel und Update-Pruefung — beides laeuft gegen aussen.

Zusammen in einem Modul, weil beide dieselbe Regel haben: Sie duerfen den
Diktat-Pfad nie blockieren. Die Pruefung laeuft im Hintergrund-Thread, der
Lizenzzustand wird gemerkt statt bei jeder Aufnahme neu berechnet.

Mixin statt eigener Klasse: Der Zustand (settings, overlay, pipeline, recorder)
liegt weiter auf EINEM Objekt. Ein eigenes Controller-Objekt haette neue
Referenzen in den Qt-Objektgraphen gelegt — genau die Konstellation, die in
diesem Projekt schon zu GC-Reihenfolge-Abstuerzen gefuehrt hat.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path


log = logging.getLogger(__name__)

class LizenzUpdateMixin:
    def _license_ok(self) -> bool:
        """Darf diese Installation diktieren?

        Das Ergebnis wird gemerkt, weil die Pruefung bei JEDEM Aufnahmestart laeuft
        — eine Signaturpruefung kostet zwar nur Mikrosekunden, aber der Hotkey-Pfad
        ist der letzte Ort, an dem man Arbeit sammeln will. Der Merker wird
        zurueckgesetzt, sobald ein Schluessel eingetragen wird.
        """
        gemerkt = getattr(self, "_license_state", None)
        if gemerkt is None:
            from ...licensing import check

            gemerkt = check(self.settings)
            self._license_state = gemerkt
            if not gemerkt.ok:
                log.warning("Fleech ist nicht freigeschaltet: %s", gemerkt.reason)
        return bool(gemerkt.ok)

    def show_license_dialog(self) -> None:
        """Freischalt-Dialog zeigen (nicht-modal, Referenz gehalten)."""
        from ..licensedialog import LicenseDialog

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
            from ..updates import check_for_updates, download_update, update_token
            from ..updatedialog import UPDATE_DIR

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
        from ..updatedialog import UpdateDialog

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
