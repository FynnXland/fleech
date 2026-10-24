"""KI-Seite, Abschnitt „Wenn die lokale KI hängt": Cloud-Ausweiche bei Überlastung.

Nur sichtbar, solange lokal bereinigt wird. Standard ist „nicht ausweichen" — dann
verlässt kein Text den Rechner, und ein zu langsames Diktat kommt als Rohtext.
Wer einen Anbieter wählt, trägt dessen Schlüssel ein; Fleech fragt im Hintergrund
die Modellliste ab, nimmt das schnellste Modell (`llm/frist.ausweich_modell`) und
prüft damit gleich den Schlüssel.

Netzwerk im Hintergrund-Thread, Ergebnis über ein Signal — gefangen wird nur die
Brücke, nie Seite oder Panel (Referenzzyklus-Falle, CLAUDE.md).
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QWidget

from ...llm import apikeys
from ...llm.frist import ausweich_modell
from ...llm.providers import ANBIETER, anbieter, modelle_abrufen

log = logging.getLogger(__name__)

_GRAU = "color: #808088; font-size: 8pt;"
_GRUEN = "color: #4CC38A; font-size: 8pt;"
_ROT = "color: #E5484D; font-size: 8pt;"
_GELB = "color: #E8A13C; font-size: 9pt;"

AUS_TEXT = "Nicht ausweichen — der Text bleibt auf diesem Rechner"


class _Bruecke(QObject):
    modell = Signal(str, str)          # (Modellname, Fehlertext)


def cloud_anbieter() -> list:
    """Die Anbieter, auf die ausgewichen werden kann: Cloud mit eigenem Schlüssel."""
    return [a for a in ANBIETER if a.braucht_schluessel]


def satz(ident: str) -> tuple[str, str]:
    """(Satz, Stil) — was passiert bei dieser Wahl?"""
    if not ident:
        return ("Antwortet die lokale KI nicht rechtzeitig, fügt Fleech den erkannten "
                "Text ohne Bereinigung ein. Während der Verarbeitung tut der Haken in "
                "der Pille dasselbe sofort.", _GRAU)
    name = anbieter(ident).name
    return (f"Nur wenn die lokale KI nicht rechtzeitig antwortet oder ausfällt, geht "
            f"der Text dieses einen Diktats — nicht die Tonaufnahme — an {name}. Im "
            f"Verlauf steht dann „in der Cloud bereinigt“.", _GELB)


def build(panel, form, bruecke_eltern):
    """Baut die Zeilen in `form`. Rückgabe: `sichtbar(lokal)` — die KI-Seite ruft
    es bei jedem Anbieterwechsel; der Abschnitt gilt nur für lokale Bereinigung."""
    ki = panel.settings.ki
    bruecke = _Bruecke(bruecke_eltern)
    panel._ki_ausweich_bruecke = bruecke

    box = QComboBox()
    box.addItem(AUS_TEXT, "")
    for eintrag in cloud_anbieter():
        box.addItem(eintrag.name, eintrag.id)
    box.setCurrentIndex(max(0, box.findData(ki.ausweichen or "")))
    label_w, _ = panel._row_label(
        "Wenn die lokale KI hängt",
        "Laufen viele Programme nebenher, kann die lokale KI sehr langsam werden. "
        "Fleech wartet nur begrenzt (je nach Länge des Diktats etwa 6–20 s) und "
        "nimmt dann den Rohtext — oder, wenn hier gewählt, einen Cloud-Anbieter.")
    form.addRow(label_w, box)

    erklaerung = QLabel("")
    erklaerung.setWordWrap(True)
    form.addRow("", erklaerung)

    zeile = QWidget()
    spalte = QHBoxLayout(zeile)
    spalte.setContentsMargins(0, 0, 0, 0)
    feld = QLineEdit()
    feld.setEchoMode(QLineEdit.Password)
    feld.setPlaceholderText("Schlüssel einfügen und Enter drücken")
    status = QLabel("")
    status.setTextFormat(Qt.RichText)
    status.setOpenExternalLinks(True)
    status.setWordWrap(True)
    spalte.addWidget(feld, 1)
    spalte.addWidget(status, 1)
    form.addRow(panel._row_label(
        "Schlüssel dafür", "Wird im Schlüsselbund des Systems abgelegt, nie in einer "
                           "Datei. Derselbe Schlüssel gilt auch, wenn du den Anbieter "
                           "oben als Haupt-KI wählst.")[0], zeile)

    def zeige_stand() -> str:
        """Schlüssel da? — ohne Netz. Gibt den Schlüssel zurück ("" = keiner)."""
        eintrag = anbieter(ki.ausweichen)
        schluessel = apikeys.lies(eintrag.id) if ki.ausweichen else ""
        if schluessel:
            modell = ki.ausweichen_modell or eintrag.modell
            status.setText(f"Gespeichert ({apikeys.maskiert(schluessel)}) — springt "
                           f"mit {modell} ein.")
            status.setStyleSheet(_GRUEN)
        elif eintrag.schluessel_url:
            status.setText(f'Noch kein Schlüssel. <a href="{eintrag.schluessel_url}">'
                           f'Schlüssel bei {eintrag.name} anlegen</a>')
            status.setStyleSheet(_GRAU)
        return schluessel

    def pruefen():
        """Modellliste holen → schnellstes Modell merken. Prüft den Schlüssel mit."""
        eintrag = anbieter(ki.ausweichen)
        schluessel = zeige_stand()
        if not schluessel:
            return
        status.setText(f"Gespeichert ({apikeys.maskiert(schluessel)}) — prüfe …")
        status.setStyleSheet(_GRAU)

        def arbeite():
            try:
                namen = modelle_abrufen(eintrag, schluessel)
                bruecke.modell.emit(ausweich_modell(eintrag, namen), "")
            except Exception as exc:
                log.info("Ausweiche %s nicht pruefbar: %s", eintrag.id, exc)
                from .ki import fehlertext

                bruecke.modell.emit("", fehlertext(exc))

        threading.Thread(target=arbeite, daemon=True, name="fleech-ki-ausweiche").start()

    def modell_da(name, fehler):
        if not ki.ausweichen:
            return
        if fehler:
            status.setText(fehler)
            status.setStyleSheet(_ROT)
            return
        status.setText(f"Bereit — springt mit {name} ein.")
        status.setStyleSheet(_GRUEN)
        if name and name != ki.ausweichen_modell:
            ki.ausweichen_modell = name
            panel._changed("ki")

    lokal_jetzt = [True]

    def anzeigen():
        text, stil = satz(ki.ausweichen)
        erklaerung.setText(text)
        erklaerung.setStyleSheet(stil)
        form.setRowVisible(zeile, lokal_jetzt[0] and bool(ki.ausweichen))
        feld.clear()
        status.setText("")
        zeige_stand()

    def gewechselt(_index):
        ki.ausweichen = box.currentData() or ""
        ki.ausweichen_modell = ""          # Modellnamen gelten je Anbieter
        anzeigen()
        if ki.ausweichen:
            pruefen()
        panel._changed("ki")

    def sichtbar(lokal: bool) -> None:
        lokal_jetzt[0] = bool(lokal)
        form.setRowVisible(box, lokal)
        form.setRowVisible(erklaerung, lokal)
        anzeigen()

    def schluessel_gesetzt():
        neu = feld.text().strip()
        if not neu or not ki.ausweichen:
            return
        if not apikeys.speichere(ki.ausweichen, neu):
            eintrag = anbieter(ki.ausweichen)
            status.setText(f"Kein Schlüsselbund verfügbar — bitte die Umgebungsvariable "
                           f"{eintrag.umgebung} setzen.")
            status.setStyleSheet(_ROT)
            return
        feld.clear()
        pruefen()
        panel._changed("ki")

    box.currentIndexChanged.connect(gewechselt)
    feld.editingFinished.connect(schluessel_gesetzt)
    bruecke.modell.connect(modell_da)
    # Beim Öffnen der Seite nicht ins Netz — geprüft wird bei Wahl oder Schlüssel.
    anzeigen()
    return sichtbar
