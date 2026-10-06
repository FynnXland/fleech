"""KI — wer bereinigt den Text: lokal, ein Cloud-Anbieter oder niemand.

Lokal (Ollama) ist der Standard und bleibt oben in der Liste. Wer einen
Cloud-Anbieter waehlt, traegt einen eigenen API-Schluessel ein; der landet im
Schluesselbund des Systems, nie in `settings.json`. Die Seite sagt bei jeder Wahl
in einem Satz, wohin der Text geht — eine Datenschutz-Entscheidung darf nicht in
einem Tooltip versteckt sein.

Netzwerk (Modellliste, Testaufruf) laeuft im Hintergrund-Thread; Ergebnisse
kommen ueber Signale zurueck in den UI-Thread.
"""

from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from ...llm import apikeys
from ...llm.providers import ANBIETER, AUS, EIGENER, OLLAMA, anbieter, modell_vorschlag, modelle_abrufen
from .common import hint

log = logging.getLogger(__name__)

_GRAU = "color: #808088; font-size: 8pt;"
_GRUEN = "color: #4CC38A; font-size: 8pt;"
_ROT = "color: #E5484D; font-size: 8pt;"
_GELB = "color: #E8A13C; font-size: 9pt;"


class _Bruecke(QObject):
    """Thread → UI. Nur dieses Objekt wird in Worker-Closures gefangen, nie die
    Seite oder das Panel (Referenzzyklus-Falle, siehe CLAUDE.md)."""

    modelle = Signal(list, str)        # (Namen, Fehlertext)
    test = Signal(bool, str)           # (ok, Meldung)


def datenschutz_satz(ident: str) -> tuple[str, str]:
    """(Satz, Stil) — wohin geht der Text bei dieser Wahl?"""
    eintrag = anbieter(ident)
    if eintrag.id == OLLAMA:
        return ("Alles bleibt auf diesem Rechner — kein Konto, keine Kosten.", _GRUEN)
    if eintrag.id == AUS:
        return ("Nur Spracherkennung: Füllwörter wie „äh“ entfernt Fleech weiterhin, "
                "aber keine KI glättet den Text. Befehle (Safe-Word) und Formate wie "
                "E-Mail oder KI-Prompt ruhen.", _GRAU)
    ziel = "deinen eigenen Server" if eintrag.id == EIGENER else eintrag.name
    return (f"Dein diktierter Text — nicht die Tonaufnahme — wird zum Bereinigen an "
            f"{ziel} gesendet und dort nach dessen Bedingungen verarbeitet. Die "
            f"Kosten rechnet der Anbieter über deinen Schlüssel ab (pro Diktat "
            f"meist Bruchteile eines Cents).", _GELB)


def fehlertext(exc: Exception) -> str:
    """Netz- und HTTP-Fehler in einen Satz, der sagt, was zu tun ist."""
    code = getattr(exc, "code", None)
    if code in (401, 403):
        return "Schlüssel abgelehnt — bitte prüfen."
    if code == 404:
        return "Adresse oder Modell nicht gefunden."
    if code == 429:
        return "Kontingent erschöpft oder zu viele Anfragen."
    if code:
        return f"Der Dienst antwortete mit Fehler {code}."
    return "Keine Verbindung — Internet oder Adresse prüfen."


def build(panel) -> None:
    s = panel.settings
    _, form = panel._page()
    form.addRow("", hint(
        "Wer bereinigt deinen Text? Lokal ist der Standard. Ein Cloud-Anbieter "
        "braucht einen eigenen API-Schlüssel — ein Abo wie ChatGPT Plus oder "
        "Claude Pro lässt sich dafür nicht verwenden."))
    bruecke = _Bruecke(panel)
    panel._ki_bruecke = bruecke

    box = QComboBox()
    for eintrag in ANBIETER:
        box.addItem(eintrag.name, eintrag.id)
    box.setCurrentIndex(max(0, box.findData(anbieter(s.ki.anbieter).id)))
    label_w, _ = panel._row_label(
        "Anbieter", "Lokal: Ollama auf diesem Rechner (empfohlen). Cloud: OpenAI, "
                    "Anthropic, Google, Mistral, Groq, OpenRouter oder ein eigener "
                    "OpenAI-kompatibler Server. „Ohne KI“: nur Spracherkennung.")
    form.addRow(label_w, box)

    satz = QLabel("")
    satz.setWordWrap(True)
    form.addRow("", satz)

    schluessel_w, schluessel_feld, schluessel_status = _schluessel_zeile(panel)
    form.addRow(panel._row_label(
        "API-Schlüssel", "Wird im Schlüsselbund des Systems abgelegt (Windows: "
                         "Anmeldeinformationsverwaltung), nie in einer Datei.")[0],
        schluessel_w)

    adresse = QLineEdit(s.ki.adresse)
    adresse.setPlaceholderText("http://127.0.0.1:1234/v1")
    form.addRow(panel._row_label(
        "Server-Adresse", "Basis-Adresse eines OpenAI-kompatiblen Servers "
                          "(LM Studio, vLLM, llama.cpp …), meist mit /v1 am Ende.")[0],
        adresse)

    modell_w, modell_box, modell_status = _modell_zeile(panel, bruecke)
    form.addRow(panel._row_label(
        "Modell", "Leer = Vorschlag des Anbieters. „Liste laden“ fragt den Anbieter, "
                  "welche Modelle dein Schlüssel nutzen darf.")[0], modell_w)

    test_w, test_status = _test_zeile(panel, bruecke)
    form.addRow("", test_w)

    def aktuell():
        return anbieter(box.currentData())

    def anzeigen():
        eintrag = aktuell()
        text, stil = datenschutz_satz(eintrag.id)
        satz.setText(text)
        satz.setStyleSheet(stil)
        form.setRowVisible(schluessel_w, eintrag.id not in (OLLAMA, AUS))
        form.setRowVisible(adresse, eintrag.id == EIGENER)
        form.setRowVisible(modell_w, eintrag.id != AUS)
        form.setRowVisible(test_w, eintrag.id != AUS)
        schluessel_feld.clear()
        _zeige_schluessel_stand(eintrag, schluessel_status)
        modell_box.blockSignals(True)
        modell_box.clear()
        if s.ki.modell:
            modell_box.addItem(s.ki.modell)
        modell_box.setEditText(s.ki.modell)
        modell_box.lineEdit().setPlaceholderText(eintrag.modell or "Modellname")
        modell_box.blockSignals(False)
        modell_status.setText("")
        test_status.setText("")

    def anbieter_gewechselt(_index):
        s.ki.anbieter = aktuell().id
        s.ki.modell = ""                      # Modellnamen gelten je Anbieter
        anzeigen()
        panel._changed("ki")

    def schluessel_gesetzt():
        eintrag = aktuell()
        neu = schluessel_feld.text().strip()
        if not neu:
            return
        if not apikeys.speichere(eintrag.id, neu):
            schluessel_status.setText(
                f"Kein Schlüsselbund verfügbar — bitte die Umgebungsvariable "
                f"{eintrag.umgebung or 'FLEECH_' + eintrag.id.upper() + '_API_KEY'} setzen.")
            schluessel_status.setStyleSheet(_ROT)
            return
        schluessel_feld.clear()
        _zeige_schluessel_stand(eintrag, schluessel_status)
        panel._changed("ki")

    def adresse_gesetzt():
        s.ki.adresse = adresse.text().strip()
        panel._changed("ki")

    def modell_gesetzt():
        wert = modell_box.currentText().strip()
        if wert != s.ki.modell:
            s.ki.modell = wert
            panel._changed("ki")

    def modelle_da(namen, fehler):
        if fehler:
            modell_status.setText(fehler)
            modell_status.setStyleSheet(_ROT)
            return
        if not namen:
            modell_status.setText("Der Anbieter nannte keine Modelle.")
            modell_status.setStyleSheet(_GRAU)
            return
        vorher = modell_box.currentText().strip()
        modell_box.blockSignals(True)
        modell_box.clear()
        modell_box.addItems(namen)
        wahl = vorher if vorher in namen else modell_vorschlag(aktuell(), namen)
        modell_box.setEditText(wahl)
        modell_box.blockSignals(False)
        modell_status.setText(f"{len(namen)} Modelle verfügbar.")
        modell_status.setStyleSheet(_GRUEN)
        modell_gesetzt()

    def test_da(ok, meldung):
        test_status.setText(meldung)
        test_status.setStyleSheet(_GRUEN if ok else _ROT)

    box.currentIndexChanged.connect(anbieter_gewechselt)
    schluessel_feld.editingFinished.connect(schluessel_gesetzt)
    adresse.editingFinished.connect(adresse_gesetzt)
    modell_box.lineEdit().editingFinished.connect(modell_gesetzt)
    modell_box.activated.connect(lambda _i: modell_gesetzt())
    bruecke.modelle.connect(modelle_da)
    bruecke.test.connect(test_da)
    anzeigen()


def _zeige_schluessel_stand(eintrag, status: QLabel) -> None:
    vorhanden = apikeys.lies(eintrag.id) if eintrag.braucht_schluessel else ""
    if vorhanden:
        status.setText(f"Gespeichert ({apikeys.maskiert(vorhanden)}).")
        status.setStyleSheet(_GRUEN)
    elif eintrag.schluessel_url:
        status.setText(f'Noch kein Schlüssel. <a href="{eintrag.schluessel_url}">'
                       f'Schlüssel bei {eintrag.name} anlegen</a>')
        status.setStyleSheet(_GRAU)
    else:
        status.setText("Optional — nur, wenn dein Server einen verlangt.")
        status.setStyleSheet(_GRAU)


def _schluessel_zeile(panel):
    w = QWidget()
    spalte = QHBoxLayout(w)
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
    return w, feld, status


def _modell_zeile(panel, bruecke):
    w = QWidget()
    spalte = QHBoxLayout(w)
    spalte.setContentsMargins(0, 0, 0, 0)
    box = QComboBox()
    box.setEditable(True)
    knopf = QPushButton("Liste laden")
    status = QLabel("")
    status.setStyleSheet(_GRAU)
    spalte.addWidget(box, 2)
    spalte.addWidget(knopf)
    spalte.addWidget(status, 1)
    ki = panel.settings.ki

    def laden():
        eintrag = anbieter(ki.anbieter)
        adresse = ki.adresse
        status.setText("Frage den Anbieter …")
        status.setStyleSheet(_GRAU)

        def arbeite():
            try:
                namen = modelle_abrufen(eintrag, apikeys.lies(eintrag.id), adresse)
                bruecke.modelle.emit(namen, "")
            except Exception as exc:
                log.info("Modellliste von %s nicht abrufbar: %s", eintrag.id, exc)
                bruecke.modelle.emit([], fehlertext(exc))

        threading.Thread(target=arbeite, daemon=True, name="fleech-ki-modelle").start()

    knopf.clicked.connect(laden)
    return w, box, status


def _test_zeile(panel, bruecke):
    w = QWidget()
    spalte = QHBoxLayout(w)
    spalte.setContentsMargins(0, 0, 0, 0)
    knopf = QPushButton("Verbindung testen")
    status = QLabel("")
    status.setWordWrap(True)
    spalte.addWidget(knopf)
    spalte.addWidget(status, 1)
    settings = panel.settings

    def testen():
        status.setText("Teste …")
        status.setStyleSheet(_GRAU)
        from ...config import load_config
        from ...llm import ChatClient

        konfig = load_config()
        settings.apply_to(konfig)
        endpunkt = konfig.llm_cleanup

        def arbeite():
            t0 = time.perf_counter()
            try:
                antwort = ChatClient(endpunkt).complete(
                    "Antworte nur mit dem Wort OK.", "Test")
                dauer = time.perf_counter() - t0
                sekunden = f"{dauer:.1f}".replace(".", ",")
                bruecke.test.emit(bool(antwort.strip()),
                                  f"Verbunden — {endpunkt.model} antwortete in "
                                  f"{sekunden} s." if antwort.strip()
                                  else "Leere Antwort erhalten.")
            except Exception as exc:
                log.info("KI-Test fehlgeschlagen (%s): %s", endpunkt.provider, exc)
                bruecke.test.emit(False, fehlertext(exc))

        threading.Thread(target=arbeite, daemon=True, name="fleech-ki-test").start()

    knopf.clicked.connect(testen)
    return w, status
