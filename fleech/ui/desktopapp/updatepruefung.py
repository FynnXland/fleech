"""Update-Pruefung — der einzige Weg, auf dem Fleech von sich aus ins Netz geht.

Regel: Sie darf den Diktat-Pfad nie blockieren. Pruefen und Laden laufen im
Hintergrund-Thread; die UI erfaehrt das Ergebnis nur ueber `bus.update_ready`.

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

class UpdateMixin:
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
            from ..updates import check_for_updates, download_update
            from ..updatedialog import UPDATE_DIR

            try:
                info = check_for_updates(settings.advanced.update_feed_url or None)
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
                    dateiname=str(info.get("name") or ""),
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
        )
        self._update_dialog.show()
        self._update_dialog.raise_()
        self._update_dialog.activateWindow()
