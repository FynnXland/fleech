"""Die Filterleiste ueber dem Verlauf: suchen, Anwendung waehlen, Zeitraum, ausgeben.

Eigenes Modul und nicht in `home.py`: Die Startseite ist der Verlauf plus die
Kurz-Stats — die Leiste ist ein eigenes Thema mit eigenem Zustand (Suchtext,
Anwendung, Zeitraum) und einem einzigen Signal nach aussen. `home.py` fragt nur
ab, was eingestellt ist, und holt sich die passenden Eintraege.

Warum es sie gibt (V-12/H-4): Der Verlauf zeigte 40 Eintraege. Bei knapp 30
Diktaten am Tag ist damit alles aelter als anderthalb Tage unerreichbar — obwohl
in der Datenbank ein persoenliches Archiv liegt.
"""

from __future__ import annotations

import time as _time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget

from ..theme import ACCENT, MUTED, TEXT, style_button
from ..widgets import _suchfeld

# Zeitraum-Knoepfe nach dem Muster der Insights (`INSIGHT_RANGES`): vier Stueck,
# in derselben Reihenfolge und mit denselben Beschriftungen — wer sie dort gelernt
# hat, muss sie hier nicht neu lernen. Bewusst eine eigene Liste statt eines
# Imports quer ueber die Seiten: Die Insights duerfen ihre Zeitraeume aendern,
# ohne dass sich der Verlauf mitaendert.
VERLAUF_RANGES = (("day", "Heute"), ("week", "7 Tage"),
                  ("month", "30 Tage"), ("all", "Alle"))

_RANGE_DAYS = {"day": 1, "week": 7, "month": 30, "all": None}

# Beschriftung des ersten Combo-Eintrags = kein App-Filter.
ALLE_APPS = "Alle Anwendungen"


class VerlaufFilter(QWidget):
    """Suchfeld · Anwendung · Zeitraum · „Treffer speichern"."""

    geaendert = Signal()
    export_gewuenscht = Signal()

    def __init__(self):
        super().__init__()
        zeile = QHBoxLayout(self)
        zeile.setContentsMargins(0, 0, 8, 0)
        zeile.setSpacing(8)

        self.suche = _suchfeld("Verlauf durchsuchen …")
        self.suche.setToolTip(
            "Sucht im gesprochenen UND im eingefügten Text — auch nach Wörtern, "
            "die die Bereinigung entfernt hat."
        )
        # Erst nach kurzer Pause suchen waere feiner, ist bei ein paar tausend
        # Zeilen aber unnoetig: Die Abfrage laeuft im Millisekundenbereich.
        self.suche.textChanged.connect(self._melde)
        zeile.addWidget(self.suche, 1)

        self.apps = QComboBox()
        self.apps.addItem(ALLE_APPS, "")
        self.apps.setFixedWidth(150)
        self.apps.currentIndexChanged.connect(self._melde)
        zeile.addWidget(self.apps)

        self._range = "all"
        self._range_buttons: dict[str, QPushButton] = {}
        for key, label in VERLAUF_RANGES:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            # Schluessel am Button, KEIN Lambda mit self: Ein Lambda, das `self`
            # faengt und in einem Kind-Widget haengt, baut einen Referenzzyklus
            # (in diesem Projekt schon Ursache sporadischer Abstuerze).
            btn.setProperty("range_key", key)
            btn.clicked.connect(self._on_range_clicked)
            self._range_buttons[key] = btn
            zeile.addWidget(btn)
        self._apply_range_styles()

        self.export_btn = style_button(QPushButton("Treffer speichern …"), "ghost")
        self.export_btn.setToolTip(
            "Schreibt die angezeigten Einträge als Markdown-Datei — Datum, "
            "Anwendung und Text. Achtung: Der volle Wortlaut steht darin "
            "unverschlüsselt und liegt danach dort, wohin du ihn speicherst."
        )
        self.export_btn.clicked.connect(self.export_gewuenscht)
        zeile.addWidget(self.export_btn)

    # -- Zustand ---------------------------------------------------------------------

    def aktiv(self) -> bool:
        """Wird gerade gefiltert? Nur dann ersetzt die Trefferliste die letzten 40."""
        return bool(self.suchtext() or self.app() or self._range != "all")

    def suchtext(self) -> str:
        return self.suche.text().strip()

    def app(self) -> str:
        return str(self.apps.currentData() or "")

    def von(self) -> float | None:
        tage = _RANGE_DAYS.get(self._range)
        return None if not tage else _time.time() - tage * 86400

    def setze_apps(self, namen: list[str]) -> None:
        """Auswahlliste aus den zuletzt gesehenen Anwendungen fuellen — die Auswahl
        bleibt erhalten, auch wenn die Liste neu aufgebaut wird."""
        gewaehlt = self.app()
        vorhanden = [self.apps.itemData(i) for i in range(self.apps.count())]
        if vorhanden == [""] + namen:
            return
        self.apps.blockSignals(True)
        self.apps.clear()
        self.apps.addItem(ALLE_APPS, "")
        for name in namen:
            self.apps.addItem(name, name)
        index = self.apps.findData(gewaehlt)
        self.apps.setCurrentIndex(index if index >= 0 else 0)
        self.apps.blockSignals(False)

    # -- Ereignisse ------------------------------------------------------------------

    def _melde(self, *_args) -> None:
        self.geaendert.emit()

    def _on_range_clicked(self) -> None:
        sender = self.sender()
        key = sender.property("range_key") if sender is not None else None
        if key not in _RANGE_DAYS:
            return
        self._range = key
        self._apply_range_styles()
        self.geaendert.emit()

    def _apply_range_styles(self) -> None:
        for key, btn in self._range_buttons.items():
            aktiv = key == self._range
            btn.setChecked(aktiv)
            btn.setStyleSheet(
                f"QPushButton {{ background: {'#16333a' if aktiv else 'transparent'};"
                f"  color: {ACCENT if aktiv else MUTED}; border: none;"
                f"  border-radius: 7px; padding: 4px 11px; font-size: 8.5pt;"
                f"  font-weight: {'600' if aktiv else '500'}; }}"
                f"QPushButton:hover {{ color: {TEXT}; }}"
            )
