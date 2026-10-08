"""Datenschutz zur Laufzeit: Aufbewahrungsfrist, Protokolltext, Meldung nach der Umstellung.

Die Verschluesselung selbst laeuft unsichtbar (`fleech/tresor`); hier liegt nur,
was die laufende App davon mitbekommt — Einstellungen live anwenden und einmal
sagen, dass umgestellt wurde, samt dem Wiederherstellungscode.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class DatenschutzMixin:
    def _wende_datenschutz_an(self) -> None:
        """Einstellungen → Allgemein/Erweitert: Frist und Protokolltext sofort anwenden."""
        from ...protokolltext import zeige_inhalte

        zeige_inhalte(self.settings.advanced.protokoll_inhalte)
        tage = int(self.settings.general.verlauf_tage or 0)
        if tage != self.store.aufbewahrung_tage:
            self.store.aufbewahrung_tage = tage
            if self.store.aufbewahren():
                self.window.refresh_data()

    def _melde_tresor(self, bericht) -> None:
        """Nach dem Start: einmal sagen, was die Umstellung getan hat."""
        if bericht is None:
            return
        if bericht.fehlgeschlagen:
            self.tray.notify("Fleech", "Die Verschlüsselung deiner Daten konnte nicht "
                                       "abgeschlossen werden. Fleech versucht es beim "
                                       "nächsten Start erneut.")
            return
        if bericht.etwas_getan and not self.settings.general.wiederherstellung_notiert:
            self.zeige_wiederherstellungscode(nach_umstellung=True)

    def zeige_wiederherstellungscode(self, nach_umstellung: bool = False) -> None:
        from ..tresordialoge import CodeDialog

        _ref = self.settings

        def notiert() -> None:
            _ref.general.wiederherstellung_notiert = True
            _ref.save()

        # Ohne Parent: Der Dialog soll auch erscheinen, wenn das Hauptfenster im
        # Tray liegt. Die Referenz haelt ihn am Leben, bis er geschlossen ist.
        self._code_dialog = CodeDialog(nach_umstellung=nach_umstellung,
                                       on_notiert=notiert)
        self._code_dialog.show()
        self._code_dialog.raise_()
        self._code_dialog.activateWindow()
