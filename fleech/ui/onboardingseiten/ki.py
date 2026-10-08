"""KI-Schritt der Einfuehrung: wer raeumt den Text auf — und mit welchem Modell?

Drei Wege, als grosse Auswahl statt als Combo, weil die Wahl Folgen hat, die man
sehen soll (Download-Groesse, wohin der Text geht, Kosten):

  Lokal   — Ollama auf diesem Rechner. Die Modellliste kommt aus dem Katalog
            (`fleech/llm/modelle.json`), ergaenzt um bereits Installiertes und
            eine neue Generation aus der Ollama-Registry.
  Cloud   — eigener API-Schluessel. Sobald einer da ist, fragt die Seite den
            Anbieter, welche Modelle er nutzen darf, und markiert ein neueres
            derselben Klasse.
  Ohne KI — nur Spracherkennung.

Gespeichert wird erst beim „Weiter" (`commit`), damit ein Durchklicken der
Optionen nicht dreimal Modelle umsteckt. Ausnahme: der Schluessel — der landet
sofort im Schluesselbund, wie auf der Einstellungsseite.

Netz laeuft im Hintergrund-Thread; die Ergebnisse kommen ueber `_Bruecke`. Die
Worker fangen nur die Bruecke, nie die Seite (Referenzzyklus-Falle, CLAUDE.md).
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QLineEdit, QRadioButton, QVBoxLayout, QWidget,
)

from ...llm import apikeys
from ...llm import modellberater as berater
from ...llm.providers import ANBIETER, AUS, EIGENER, OLLAMA, anbieter, modelle_abrufen
from ..settings.ki import datenschutz_satz, fehlertext
from .bausteine import GELB, GRUEN, NOTIZ_STIL, ROT, auswahl, notiz, text, titel

log = logging.getLogger(__name__)

CLOUD = tuple(a for a in ANBIETER if a.id not in (OLLAMA, AUS))


class _Bruecke(QObject):
    lokal = Signal(list)               # [Wahl]
    cloud = Signal(str, list, str)     # (Anbieter, Namen, Fehlertext)


def keine_grafikkarte() -> bool:
    """Keine NVIDIA-Karte gefunden? Dann laeuft lokal alles auf dem Prozessor."""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() == 0
    except Exception:
        return False                   # unbekannt — dann nicht warnen


class KiSeite(QWidget):
    """settings: UserSettings. netz=False: keine Abrufe (Tests, Render)."""

    def __init__(self, settings, parent=None, netz: bool = True,
                 cache_ordner=None, ollama_adresse: str = "http://127.0.0.1:11434"):
        super().__init__(parent)
        self.settings = settings
        self._netz = netz
        self._cache = cache_ordner
        self._ollama = ollama_adresse
        self._katalog = berater.katalog(cache_ordner, netz=False)
        self._lokal_geladen = False
        self._cloud_geladen = ""           # fuer welchen Anbieter die Liste kam
        self._bruecke = _Bruecke(self)
        self._bruecke.lokal.connect(self._lokale_liste_da)
        self._bruecke.cloud.connect(self._cloud_liste_da)
        self._baue()
        self._vorbelegen()

    # -- Aufbau -------------------------------------------------------------------

    def _baue(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.addWidget(titel("Wer räumt deinen Text auf?"))
        lay.addWidget(text("Eine KI entfernt Füllwörter und Versprecher und setzt die "
                           "Zeichen — deine Worte bleiben deine Worte."))
        self._gruppe = QButtonGroup(self)
        self._lokal = self._option(lay, "Lokal auf diesem Rechner (empfohlen)",
                                   "Kostenlos, kein Konto, nichts verlässt den PC. "
                                   "Lädt einmal ein Modell (ab etwa 3 GB).")
        if keine_grafikkarte():
            hinweis = notiz("Keine NVIDIA-Grafikkarte erkannt: Lokal rechnet dann der "
                            "Prozessor — mehrere Sekunden je Diktat. Ein "
                            "Cloud-Anbieter ist hier meist die bessere Wahl.")
            hinweis.setStyleSheet(GELB)
            hinweis.setContentsMargins(26, 0, 0, 0)
            lay.addWidget(hinweis)
        self._lokal_box = self._baue_lokal(lay)
        self._cloud = self._option(lay, "Cloud-Anbieter mit eigenem API-Schlüssel",
                                   "OpenAI, Anthropic, Google, Mistral, Groq … Kein "
                                   "großer Download; pro Diktat meist Bruchteile "
                                   "eines Cents.")
        self._cloud_box = self._baue_cloud(lay)
        self._aus = self._option(lay, "Ohne KI — nur Spracherkennung",
                                 "Füllwörter fallen trotzdem weg, sonst bleibt der "
                                 "Text, wie er erkannt wurde.")
        self._satz = notiz("")
        lay.addWidget(self._satz)
        self._fehler = QLabel("")
        self._fehler.setStyleSheet(ROT)
        self._fehler.setWordWrap(True)
        self._fehler.hide()
        lay.addWidget(self._fehler)
        lay.addStretch(1)
        self._gruppe.buttonToggled.connect(self._weg_gewechselt)

    def _option(self, lay, kopf: str, unterzeile: str) -> QRadioButton:
        radio = QRadioButton(kopf)
        radio.setStyleSheet("font-weight: 600;")
        self._gruppe.addButton(radio)
        lay.addWidget(radio)
        zeile = notiz(unterzeile)
        zeile.setContentsMargins(26, 0, 0, 0)
        lay.addWidget(zeile)
        return radio

    def _baue_lokal(self, lay) -> QWidget:
        box = QWidget()
        spalte = QVBoxLayout(box)
        spalte.setContentsMargins(26, 2, 0, 4)
        spalte.setSpacing(4)
        self._lokal_modell = auswahl()
        self._lokal_modell.currentIndexChanged.connect(self._lokales_modell_gewaehlt)
        spalte.addWidget(self._lokal_modell)
        self._lokal_notiz = notiz("")
        spalte.addWidget(self._lokal_notiz)
        lay.addWidget(box)
        return box

    def _baue_cloud(self, lay) -> QWidget:
        box = QWidget()
        spalte = QVBoxLayout(box)
        spalte.setContentsMargins(26, 2, 0, 4)
        spalte.setSpacing(6)
        self._anbieter = auswahl()
        for eintrag in CLOUD:
            self._anbieter.addItem(eintrag.name, eintrag.id)
        self._anbieter.currentIndexChanged.connect(self._anbieter_gewechselt)
        spalte.addWidget(self._anbieter)

        reihe = QHBoxLayout()
        self._schluessel = QLineEdit()
        self._schluessel.setEchoMode(QLineEdit.Password)
        self._schluessel.setPlaceholderText("API-Schlüssel einfügen und Enter drücken")
        self._schluessel.editingFinished.connect(self._schluessel_gesetzt)
        reihe.addWidget(self._schluessel, 1)
        spalte.addLayout(reihe)
        self._schluessel_status = QLabel("")
        self._schluessel_status.setTextFormat(Qt.RichText)
        self._schluessel_status.setOpenExternalLinks(True)
        self._schluessel_status.setWordWrap(True)
        self._schluessel_status.setStyleSheet(NOTIZ_STIL)
        spalte.addWidget(self._schluessel_status)

        self._adresse = QLineEdit(self.settings.ki.adresse)
        self._adresse.setPlaceholderText("Server-Adresse, z. B. http://127.0.0.1:1234/v1")
        self._adresse.editingFinished.connect(self._lade_cloud)
        spalte.addWidget(self._adresse)

        self._cloud_modell = auswahl()
        self._cloud_modell.currentIndexChanged.connect(self._cloud_modell_gewaehlt)
        spalte.addWidget(self._cloud_modell)
        self._cloud_status = notiz("")
        spalte.addWidget(self._cloud_status)
        lay.addWidget(box)
        return box

    def _vorbelegen(self) -> None:
        wahl = anbieter(self.settings.ki.anbieter)
        if wahl.id == OLLAMA:
            self._lokal.setChecked(True)
        elif wahl.id == AUS:
            self._aus.setChecked(True)
        else:
            self._anbieter.blockSignals(True)
            self._anbieter.setCurrentIndex(max(0, self._anbieter.findData(wahl.id)))
            self._anbieter.blockSignals(False)
            self._cloud.setChecked(True)
        self._fuelle_lokal(berater.lokale_auswahl(self._katalog))
        self._anbieter_gewechselt(self._anbieter.currentIndex())
        self._weg_gewechselt()

    # -- Was ist gewaehlt? -----------------------------------------------------------

    def weg(self) -> str:
        if self._lokal.isChecked():
            return OLLAMA
        if self._aus.isChecked():
            return AUS
        return str(self._anbieter.currentData() or "openai")

    def modell(self) -> str:
        if self._lokal.isChecked():
            return str(self._lokal_modell.currentData() or "")
        if self._cloud.isChecked():
            return str(self._cloud_modell.currentData() or "")
        return ""

    def fehler(self) -> str:
        """Was fehlt noch fuer „Weiter"? Leer = nichts."""
        eintrag = anbieter(self.weg())
        if eintrag.id == EIGENER and not self._adresse.text().strip():
            return "Bitte die Adresse deines Servers eintragen."
        if eintrag.braucht_schluessel and not apikeys.lies(eintrag.id):
            return (f"Bitte einen API-Schlüssel für {eintrag.name} eintragen — "
                    f"oder „Lokal“ wählen.")
        return ""

    def zeige_fehler(self, meldung: str) -> None:
        self._fehler.setText(meldung)
        self._fehler.setVisible(bool(meldung))

    def commit(self) -> bool:
        """Wahl in die Einstellungen schreiben. True = etwas hat sich geaendert."""
        ki = self.settings.ki
        vorher = (ki.anbieter, ki.modell, ki.adresse)
        eintrag = anbieter(self.weg())
        ki.anbieter = eintrag.id
        modell = self.modell()
        # Die Empfehlung nicht festschreiben: Leer heisst „was Fleech empfiehlt" —
        # so greift ein spaeter geaenderter Katalog auch ohne Zutun.
        ki.modell = "" if modell == eintrag.modell else modell
        if eintrag.id == EIGENER:
            ki.adresse = self._adresse.text().strip()
        return (ki.anbieter, ki.modell, ki.adresse) != vorher

    # -- Reaktionen ------------------------------------------------------------------

    def _weg_gewechselt(self, *_args) -> None:
        weg = self.weg()
        self._lokal_box.setVisible(weg == OLLAMA)
        self._cloud_box.setVisible(weg not in (OLLAMA, AUS))
        satz, stil = datenschutz_satz(weg)
        self._satz.setText(satz)
        self._satz.setStyleSheet(stil.replace("8pt", "9pt"))
        self.zeige_fehler("")
        if weg == OLLAMA and not self._lokal_geladen:
            self._lade_lokal()
        elif weg not in (OLLAMA, AUS) and self._cloud_geladen != weg:
            self._lade_cloud()

    def _anbieter_gewechselt(self, _index: int) -> None:
        eintrag = anbieter(self._anbieter.currentData())
        self._schluessel.clear()
        self._schluessel.setVisible(eintrag.braucht_schluessel or eintrag.id == EIGENER)
        self._adresse.setVisible(eintrag.id == EIGENER)
        self._zeige_schluessel_stand(eintrag)
        self._cloud_modell.blockSignals(True)
        self._cloud_modell.clear()
        empfohlen = berater.empfohlenes_modell(eintrag.id, self._katalog)
        if empfohlen:
            self._cloud_modell.addItem(f"{empfohlen} · empfohlen", empfohlen)
        self._cloud_modell.blockSignals(False)
        self._cloud_modell_gewaehlt(0)
        self._cloud_geladen = ""
        self._weg_gewechselt()

    def _zeige_schluessel_stand(self, eintrag) -> None:
        vorhanden = apikeys.lies(eintrag.id) if eintrag.braucht_schluessel else ""
        if vorhanden:
            self._schluessel_status.setText(
                f"Schlüssel gespeichert ({apikeys.maskiert(vorhanden)}).")
            self._schluessel_status.setStyleSheet(GRUEN)
        elif eintrag.schluessel_url:
            self._schluessel_status.setText(
                f'Noch kein Schlüssel. <a href="{eintrag.schluessel_url}">Schlüssel bei '
                f'{eintrag.name} anlegen</a> — ein Abo wie ChatGPT Plus zählt nicht.')
            self._schluessel_status.setStyleSheet(NOTIZ_STIL)
        else:
            self._schluessel_status.setText("Schlüssel optional — nur, wenn dein "
                                            "Server einen verlangt.")
            self._schluessel_status.setStyleSheet(NOTIZ_STIL)

    def _schluessel_gesetzt(self) -> None:
        eintrag = anbieter(self._anbieter.currentData())
        neu = self._schluessel.text().strip()
        if not neu:
            return
        if not apikeys.speichere(eintrag.id, neu):
            self._schluessel_status.setText(
                "Kein Schlüsselbund verfügbar — bitte die Umgebungsvariable "
                f"{eintrag.umgebung or 'FLEECH_' + eintrag.id.upper() + '_API_KEY'} "
                "setzen.")
            self._schluessel_status.setStyleSheet(ROT)
            return
        self._schluessel.clear()
        self._zeige_schluessel_stand(eintrag)
        self.zeige_fehler("")
        self._lade_cloud()

    def _lokales_modell_gewaehlt(self, index: int) -> None:
        wahl = self._lokal_modell.itemData(index, Qt.UserRole + 1)
        self._lokal_notiz.setText(str(wahl or ""))

    def _cloud_modell_gewaehlt(self, index: int) -> None:
        wahl = self._cloud_modell.itemData(index, Qt.UserRole + 1)
        if wahl:
            self._cloud_status.setText(str(wahl))
            self._cloud_status.setStyleSheet(NOTIZ_STIL)

    # -- Listen fuellen ------------------------------------------------------------------

    def _fuelle_lokal(self, eintraege: list) -> None:
        vorher = self._lokal_modell.currentData()
        if not vorher and anbieter(self.settings.ki.anbieter).id == OLLAMA:
            vorher = self.settings.ki.modell
        box = self._lokal_modell
        box.blockSignals(True)
        box.clear()
        for wahl in eintraege:
            box.addItem(wahl.label, wahl.modell)
            box.setItemData(box.count() - 1, wahl.notiz, Qt.UserRole + 1)
        index = box.findData(vorher) if vorher else -1
        box.setCurrentIndex(index if index >= 0 else 0)
        box.blockSignals(False)
        self._lokales_modell_gewaehlt(box.currentIndex())

    def _lokale_liste_da(self, eintraege: list) -> None:
        if eintraege:
            self._fuelle_lokal(eintraege)

    def _cloud_liste_da(self, ident: str, namen: list, fehler: str) -> None:
        if ident != self._anbieter.currentData():
            return                         # Antwort fuer einen laengst abgewaehlten
        if fehler:
            self._cloud_status.setText(fehler)
            self._cloud_status.setStyleSheet(ROT)
            return
        if not namen:
            return
        eintraege, empfohlen, neuer = berater.cloud_auswahl(ident, namen, self._katalog)
        gespeichert = (self.settings.ki.modell
                       if anbieter(self.settings.ki.anbieter).id == ident else "")
        box = self._cloud_modell
        box.blockSignals(True)
        box.clear()
        for wahl in eintraege:
            box.addItem(wahl.label, wahl.modell)
            box.setItemData(box.count() - 1, wahl.notiz, Qt.UserRole + 1)
        index = box.findData(gespeichert) if gespeichert else -1
        box.setCurrentIndex(index if index >= 0 else 0)
        box.blockSignals(False)
        if neuer:
            self._cloud_status.setText(f"Neueres Modell verfügbar: {neuer} — in der "
                                       f"Liste wählbar. {len(namen)} Modelle insgesamt.")
            self._cloud_status.setStyleSheet(GELB)
        else:
            self._cloud_status.setText(f"Schlüssel funktioniert — {len(namen)} Modelle "
                                       f"verfügbar.")
            self._cloud_status.setStyleSheet(GRUEN)

    def _lade_lokal(self) -> None:
        """Katalog von GitHub, installierte Modelle, neue Generation — im Hintergrund."""
        self._lokal_geladen = True
        if not self._netz:
            return
        bruecke, cache, adresse = self._bruecke, self._cache, self._ollama
        empfohlen = berater.empfohlenes_modell(OLLAMA, self._katalog)

        def arbeite():
            try:
                from ...llm.client import ollama_installed_models

                daten = berater.katalog(cache, netz=True)
                installiert = ollama_installed_models(adresse, timeout=3.0)
                nachfolger = berater.ollama_nachfolger(empfohlen)
                bruecke.lokal.emit(berater.lokale_auswahl(daten, installiert, nachfolger))
            except Exception:
                log.info("Lokale Modellliste nicht ergaenzbar.", exc_info=True)

        threading.Thread(target=arbeite, daemon=True, name="fleech-ob-lokal").start()

    def _lade_cloud(self) -> None:
        eintrag = anbieter(self._anbieter.currentData())
        if not self._netz or not self._cloud.isChecked():
            return
        schluessel = apikeys.lies(eintrag.id)
        adresse = self._adresse.text().strip()
        if (eintrag.braucht_schluessel and not schluessel) or \
                (eintrag.id == EIGENER and not adresse):
            return
        self._cloud_geladen = eintrag.id
        self._cloud_status.setText(f"Frage {eintrag.name} nach den Modellen …")
        self._cloud_status.setStyleSheet(NOTIZ_STIL)
        bruecke = self._bruecke

        def arbeite():
            try:
                namen = modelle_abrufen(eintrag, schluessel, adresse)
                bruecke.cloud.emit(eintrag.id, namen, "")
            except Exception as exc:
                log.info("Modellliste von %s nicht abrufbar: %s", eintrag.id, exc)
                bruecke.cloud.emit(eintrag.id, [], fehlertext(exc))

        threading.Thread(target=arbeite, daemon=True, name="fleech-ob-cloud").start()
