"""Der KI-Austausch eines Diktats: was die KI bekam und was sie zurueckgab.

Geoeffnet aus dem Transkript-Dialog des Verlaufs („KI-Austausch …"). Je Aufruf ein
Block: Modell und Dauer, die Eingabe (eingerahmtes Transkript bzw. ein Block davon),
die Antwort so, wie sie kam — VOR den Guards. Gerade das ist der Punkt: Hat ein
Guard verworfen, steht hier, was verworfen wurde. Der System-Prompt ist lang und
meist derselbe, deshalb erst auf Knopfdruck.

Eigene Datei wie `nachbearbeitungdialog.py`: In `dialogs.py` liegen Dialoge mit
einem Text; dieser hier zeigt eine Folge von Aufrufen.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTextEdit,
    QVBoxLayout, QWidget,
)

from .theme import AMBER, BG, BORDER_HAIRLINE, CARD, MUTED, TEXT, style_button


def kopfzeile(aufruf: dict, gesamt: int) -> str:
    """„Aufruf 1 von 2 · gemma3:4b (ollama) · 1,2 s" — ohne Qt pruefbar."""
    teile = [f"Aufruf {aufruf.get('nr', 1)} von {gesamt}" if gesamt > 1 else "Aufruf"]
    modell, anbieter = aufruf.get("modell", ""), aufruf.get("anbieter", "")
    if modell:
        teile.append(f"{modell} ({anbieter})" if anbieter else modell)
    ms = int(aufruf.get("ms", 0) or 0)
    if ms:
        teile.append(f"{ms / 1000:.1f} s".replace(".", ","))
    return " · ".join(teile)


def _abschnitt(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(f"color: {MUTED}; font-size: 7.5pt; font-weight: 500;"
                      f" letter-spacing: 1px;")
    return lab


def _textfeld(text: str, farbe: str = TEXT) -> QTextEdit:
    feld = QTextEdit()
    feld.setReadOnly(True)
    feld.setPlainText(text)
    feld.setStyleSheet(
        f"QTextEdit {{ background: {CARD}; color: {farbe};"
        f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px; padding: 6px;"
        f"  font-size: 9pt; }}")
    # Hoehe nach Inhalt, gedeckelt — der Dialog scrollt als Ganzes.
    zeilen = max(2, min(14, text.count("\n") + 1 + len(text) // 70))
    feld.setFixedHeight(18 * zeilen + 16)
    return feld


class KiAustauschDialog(QDialog):
    def __init__(self, aufrufe: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("KI-Austausch")
        self.resize(620, 640)
        self.setStyleSheet(f"QDialog {{ background: {BG}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(6)
        kopf = QLabel("KI-AUSTAUSCH")
        kopf.setStyleSheet(
            f"color: {MUTED}; font-size: 9pt; font-weight: 600; letter-spacing: 0.5px;")
        outer.addWidget(kopf)
        hinweis = QLabel("Was die KI bekam und wie ihre Antwort lautete, bevor Fleech "
                         "sie geprüft hat. Liegt verschlüsselt im Verlauf.")
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        outer.addWidget(hinweis)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        halter = QWidget()
        box = QVBoxLayout(halter)
        box.setContentsMargins(0, 4, 8, 0)
        box.setSpacing(4)
        self._prompt_felder: list[QTextEdit] = []
        for aufruf in aufrufe:
            self._baue_aufruf(box, aufruf, len(aufrufe))
        box.addStretch(1)
        scroll.setWidget(halter)
        outer.addWidget(scroll, 1)

        knoepfe = QHBoxLayout()
        knoepfe.addStretch(1)
        schliessen = style_button(QPushButton("Schließen"), "ghost")
        schliessen.clicked.connect(self.accept)
        knoepfe.addWidget(schliessen)
        outer.addLayout(knoepfe)

    def _baue_aufruf(self, box: QVBoxLayout, aufruf: dict, gesamt: int) -> None:
        titel = QLabel(kopfzeile(aufruf, gesamt))
        titel.setStyleSheet(f"color: {TEXT}; font-size: 9.5pt; font-weight: 600;"
                            f" margin-top: 8px;")
        box.addWidget(titel)
        fehler = str(aufruf.get("fehler", "") or "")
        if aufruf.get("abgeschnitten"):
            fehler = fehler or "Antwort am Kontextfenster abgeschnitten"
        if fehler:
            zeile = QLabel(fehler)
            zeile.setWordWrap(True)
            zeile.setStyleSheet(f"color: {AMBER}; font-size: 8.5pt;")
            box.addWidget(zeile)
        box.addWidget(_abschnitt("EINGABE"))
        box.addWidget(_textfeld(aufruf.get("eingabe", ""), MUTED))
        if aufruf.get("antwort"):
            box.addWidget(_abschnitt("ANTWORT"))
            box.addWidget(_textfeld(aufruf["antwort"]))
        system = aufruf.get("system", "")
        if system:
            feld = _textfeld(system, MUTED)
            feld.setFixedHeight(260)
            feld.hide()
            knopf = style_button(QPushButton("System-Prompt ein-/ausblenden"), "ghost")
            knopf.setCheckable(True)
            # Gebundene Methode statt Lambda: kein Python-Zyklus ueber Qt-Objekte.
            knopf.toggled.connect(feld.setVisible)
            reihe = QHBoxLayout()
            reihe.addWidget(knopf)
            reihe.addStretch(1)
            box.addLayout(reihe)
            box.addWidget(feld)
            self._prompt_felder.append(feld)
