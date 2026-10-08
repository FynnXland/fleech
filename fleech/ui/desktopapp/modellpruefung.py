"""Modellpruefung — einmal pro Woche nachsehen, ob es ein neueres KI-Modell gibt.

Der Befund kommt vom Modellberater (`fleech/llm/modellberater.py`), der Weg ist
derselbe wie bei der Update-Pruefung: Netz nur im Hintergrund-Thread, Ergebnis
ueber den StateBus (`modell_hinweis`) in den UI-Thread. Dort wird es in den
Einstellungen vermerkt (Einstellungen → KI zeigt es mit „Übernehmen") und einmal
als Benachrichtigung gemeldet. Umgestellt wird nie von selbst: Ein neueres Modell
kann groesser, langsamer oder teurer sein — das entscheidet der Nutzer.

Wer das abschaltet (Einstellungen → KI), bei dem fragt Fleech nicht nach.

Mixin statt eigener Klasse: siehe `desktopapp/__init__.py`.
"""

from __future__ import annotations

import datetime
import logging
import threading

log = logging.getLogger(__name__)

TAGE = 7


def faellig(geprueft_am: str, heute: datetime.date | None = None) -> bool:
    """Ist die letzte Pruefung laenger als eine Woche her (oder nie gewesen)?"""
    heute = heute or datetime.date.today()
    try:
        zuletzt = datetime.date.fromisoformat(str(geprueft_am or ""))
    except ValueError:
        return True
    return (heute - zuletzt).days >= TAGE


class ModellpruefungMixin:
    def _pruefe_modelle_async(self, erzwingen: bool = False) -> None:
        ki = self.settings.ki
        if not ki.modelle_pruefen or not self.settings.general.onboarding_done:
            return
        if not erzwingen and not faellig(ki.geprueft_am):
            return
        if getattr(self, "_modellpruefung_laeuft", False):
            return
        self._modellpruefung_laeuft = True
        bus = self.bus
        anbieter_id, adresse = ki.anbieter, ki.adresse
        # Das Modell, das WIRKLICH laeuft — leer in den Einstellungen heisst
        # „was config.yaml sagt", und genau das soll verglichen werden.
        modell = self.config.llm_cleanup.model

        def arbeite():
            befund = None
            try:
                from ...llm import apikeys
                from ...llm import modellberater as berater
                from ...platformpaths import user_data_dir

                daten = berater.katalog(user_data_dir(), netz=True)
                befund = berater.pruefe(anbieter_id, modell, apikeys.lies(anbieter_id),
                                        adresse, daten)
            except Exception:
                log.debug("Modellpruefung fehlgeschlagen.", exc_info=True)
            bus.modell_hinweis.emit(befund)

        threading.Thread(target=arbeite, daemon=True, name="fleech-modelle").start()

    def _on_modell_hinweis(self, befund) -> None:
        """UI-Thread: Befund vermerken und — wenn neu — einmal melden."""
        self._modellpruefung_laeuft = False
        ki = self.settings.ki
        ki.geprueft_am = datetime.date.today().isoformat()
        if befund is None or befund.neuer in (ki.ignoriert or []):
            if befund is None:
                ki.hinweis_modell, ki.hinweis_text = "", ""
            self.settings.save()
            log.info("Modellpruefung: nichts Neueres fuer %s.", ki.anbieter)
            return
        neu = befund.neuer != ki.hinweis_modell
        ki.hinweis_modell, ki.hinweis_text = befund.neuer, befund.grund
        self.settings.save()
        log.info("Modellpruefung: %s → %s vorgeschlagen.", befund.aktuell, befund.neuer)
        if neu:
            self.tray.notify("Fleech — neueres KI-Modell",
                             f"{befund.grund} Übernehmen unter Einstellungen → KI.")
