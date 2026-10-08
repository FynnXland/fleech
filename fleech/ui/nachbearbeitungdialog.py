"""Der Fortschritt der Nachbearbeitung („Neu bereinigen als …").

Warum das ein eigenes Fenster braucht: Die Nachbearbeitung meldete sich bisher
ueber `_flash_status()`, und das laeuft auf die Pille am Bildschirmrand. Die
zeigt einen Zwischenschritt aber nur, solange der Zustand PROCESSING ist
(`overlaypille/einblendungen.show_progress`) — beim Nachbearbeiten aus dem
Verlauf wechselt der Zustand nie. Jede Rueckmeldung fiel also ins Leere: Der Text
landete in der Zwischenablage, auf dem Bildschirm passierte nichts. Aus Sicht des
Benutzers war die Funktion kaputt, im Protokoll stand „erfolgreich".

Also zeigt das Ergebnis sich jetzt dort, wo der Klick passiert ist. Der Dialog
oeffnet SOFORT — mit dem Rohtext, den er schon hat, und einem laufenden Balken an
der Stelle, an der das Ergebnis erscheinen wird. Das ist der Unterschied zwischen
„es passiert nichts" und „es arbeitet".

Eigene Datei und nicht in `dialogs.py`: Die dortigen Dialoge zeigen etwas, das
bereits feststeht. Dieser hier hat einen Verlauf — warten, gelingen, scheitern —
und damit ein eigenes Thema.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextEdit, QVBoxLayout,
)

from .theme import (
    ACCENT, AMBER, BG, BORDER_HAIRLINE, CARD, MUTED, TEXT, TRACK, style_button,
)


class NachbearbeitungDialog(QDialog):
    """Zeigt Rohtext und das neu bereinigte Ergebnis — Letzteres, sobald es da ist.

    Bewusst NICHT modal und bewusst OHNE das Schliessen-bei-Klick-daneben aus
    `TranscriptDetailDialog`: Hier laeuft etwas. Ein Fenster, das sich waehrend der
    Arbeit selbst wegklickt, waere genau die Rueckmeldung, die gefehlt hat.
    """

    def __init__(self, roh: str, format_name: str, entry: dict | None = None,
                 parent=None):
        super().__init__(parent)
        self._format_name = format_name
        self._text = ""
        self.setWindowTitle(f"Neu bereinigen als {format_name}")
        self.resize(520, 480)
        self.setStyleSheet(f"QDialog {{ background: {BG}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(4)

        kopf = QLabel(f"NEU BEREINIGEN ALS {format_name.upper()}")
        kopf.setStyleSheet(
            f"color: {MUTED}; font-size: 9pt; font-weight: 600; letter-spacing: 0.5px;")
        outer.addWidget(kopf)

        # Alles hier ist Beiwerk: Ein Eintrag ohne Zeitstempel (Altbestand, Test)
        # darf das Fenster nicht verhindern — das Fenster IST die Rueckmeldung.
        teile = []
        if entry and entry.get("ts"):
            teile.append(_dt.datetime.fromtimestamp(entry["ts"]).strftime(
                "%d.%m.%Y · %H:%M"))
        if entry and (entry.get("app") or ""):
            teile.append(entry["app"].removesuffix(".exe"))
        if teile:
            quelle = QLabel("Quelle: " + " · ".join(teile))
            quelle.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
            outer.addWidget(quelle)
        outer.addSpacing(6)

        outer.addWidget(self._abschnitt("BEREINIGT"))
        # Der Balken laeuft unbestimmt: Wie lange das Modell braucht, weiss vorher
        # niemand (0,8 s bis mehrere Sekunden, je nach Laenge und ob das Modell
        # geladen ist). Ein Prozentbalken waere hier eine erfundene Zahl.
        self._balken = QProgressBar()
        self._balken.setRange(0, 0)
        self._balken.setTextVisible(False)
        self._balken.setFixedHeight(4)
        self._balken.setStyleSheet(
            f"QProgressBar {{ background: {TRACK}; border: none; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}")
        outer.addWidget(self._balken)

        self._ergebnis = QTextEdit()
        self._ergebnis.setReadOnly(True)
        self._ergebnis.setPlainText("wird neu bereinigt …")
        self._ergebnis.setStyleSheet(
            f"QTextEdit {{ background: {CARD}; color: {MUTED};"
            f"  border: 1px solid {BORDER_HAIRLINE};"
            f"  border-radius: 8px; padding: 8px; font-size: 10pt; }}")
        outer.addWidget(self._ergebnis, 2)

        roh = (roh or "").strip()
        if roh:
            outer.addSpacing(6)
            outer.addWidget(self._abschnitt("ROH"))
            roh_feld = QTextEdit()
            roh_feld.setReadOnly(True)
            roh_feld.setPlainText(roh)
            roh_feld.setStyleSheet(
                f"QTextEdit {{ background: {CARD}; color: {MUTED};"
                f"  border: 1px solid {BORDER_HAIRLINE};"
                f"  border-radius: 8px; padding: 8px; font-size: 9.5pt; }}")
            outer.addWidget(roh_feld, 1)
        outer.addSpacing(8)

        knoepfe = QHBoxLayout()
        self._hinweis = QLabel("läuft …")
        self._hinweis.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        self._hinweis.setWordWrap(True)
        knoepfe.addWidget(self._hinweis, 1)
        schliessen = style_button(QPushButton("Schließen"), "ghost")
        schliessen.clicked.connect(self.accept)
        self._kopieren = style_button(QPushButton("Kopieren"))
        self._kopieren.setEnabled(False)      # es gibt noch nichts zu kopieren
        self._kopieren.clicked.connect(self._kopiere)
        knoepfe.addWidget(schliessen)
        knoepfe.addWidget(self._kopieren)
        outer.addLayout(knoepfe)

    @staticmethod
    def _abschnitt(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(
            f"color: {MUTED}; font-size: 7.5pt; font-weight: 500; letter-spacing: 1px;")
        return lab

    # -- Ergebnis ----------------------------------------------------------------------

    def zeige_ergebnis(self, text: str) -> None:
        """Der neue Text ist da. Wird im UI-Thread gerufen."""
        self._text = text
        self._balken.hide()
        self._ergebnis.setPlainText(text)
        self._ergebnis.setStyleSheet(
            self._ergebnis.styleSheet().replace(f"color: {MUTED}", f"color: {TEXT}"))
        self._kopieren.setEnabled(True)
        # Kopiert wird ohnehin automatisch (siehe desktopapp/nachbereitung.py) —
        # das aber ungesagt zu lassen war Teil des Problems.
        self._hinweis.setText(
            f"{len(text)} Zeichen · in der Zwischenablage, Strg+V zum Einfügen")

    def zeige_fehler(self, grund: str) -> None:
        """Es kam nichts heraus. Der Grund gehoert hierher, nicht nur ins Protokoll."""
        self._balken.hide()
        self._ergebnis.setPlainText(grund)
        self._ergebnis.setStyleSheet(
            self._ergebnis.styleSheet().replace(f"color: {MUTED}", f"color: {AMBER}"))
        self._hinweis.setText("Der Eintrag im Verlauf bleibt unverändert.")

    def _kopiere(self) -> None:
        from ..clipboard import copy_text   # privat: nicht im Win+V-Verlauf

        if not self._text:
            return
        copy_text(self._text)
        self._kopieren.setText("Kopiert ✓")
