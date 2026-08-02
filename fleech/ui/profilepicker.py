"""Profil-Auswahl: kleine Liste am Mauszeiger, ausgeloest durch HALTEN des Hotkeys.

Warum zwei Wege auf derselben Taste:

- **Tippen** schaltet zum naechsten Profil. Das ist der Alltagsfall — eine Taste,
  ohne hinzusehen, ohne Auswahl.
- **Halten** oeffnet diese Liste. Reihum durchschalten ist bei zwei Profilen
  praktisch und bei acht eine Zumutung; wer weiss, wohin er will, klickt direkt.

Qt-Regeln wie bei der Pille: Das Fenster nimmt NIE den Fokus (sonst waere das
Ziel-Textfeld weg, in das gleich eingefuegt werden soll), zeigt sich ohne
Aktivierung und schliesst bei Auswahl, Escape oder Klick daneben.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QCursor, QPainter
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from ..usersettings import APP_STANDARD
from .main_window import ACCENT, BORDER_HAIRLINE, MUTED, TEXT

log = logging.getLogger(__name__)

_BG = "rgba(24,24,28,238)"
_ZEILE_H = 30


class ProfilePicker(QWidget):
    """Liste der Profile; `chosen` traegt den Namen ("" = automatisch)."""

    chosen = Signal(str)

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(2)
        self._buttons: list[QPushButton] = []

    # -- Aufbau -------------------------------------------------------------------

    def _button(self, text: str, wert: str, aktiv: bool) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)     # nie Fokus ziehen — Ziel-Textfeld bleibt
        btn.setFixedHeight(_ZEILE_H)
        farbe = ACCENT if aktiv else TEXT
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {farbe};"
            f"  border: none; border-radius: 6px; padding: 4px 12px;"
            f"  text-align: left; font-size: 9.5pt;"
            f"  font-weight: {'600' if aktiv else '500'}; }}"
            f"QPushButton:hover {{ background: rgba(255,255,255,0.08); }}"
        )
        # setProperty + sender() statt Lambda mit self-Fang: ein Lambda, das `self`
        # faengt und im Kind-Widget liegt, baut einen Referenzzyklus (Qt-Falle).
        btn.setProperty("profil", wert)
        btn.clicked.connect(self._on_clicked)
        return btn

    def _on_clicked(self) -> None:
        knopf = self.sender()
        if knopf is None:
            return
        self.hide()
        self.chosen.emit(str(knopf.property("profil") or ""))

    def show_at_cursor(self, namen: list, aktiv: str = "") -> None:
        """Liste am Mauszeiger oeffnen. `aktiv` wird hervorgehoben."""
        for btn in self._buttons:
            btn.setParent(None)
        self._buttons = []
        eintraege = [(n, n) for n in namen] + [(APP_STANDARD, "")]
        for text, wert in eintraege:
            btn = self._button(text, wert, wert == aktiv)
            self._layout.addWidget(btn)
            self._buttons.append(btn)
        self.adjustSize()
        self.setFixedWidth(max(190, self.sizeHint().width()))

        pos = QCursor.pos()
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        bereich = screen.availableGeometry() if screen else None
        x, y = pos.x() + 12, pos.y() + 12
        if bereich is not None:
            # Nie ueber den Rand: sonst steht die Liste halb im Nichts, genau dann,
            # wenn man am Bildschirmrand arbeitet.
            x = min(x, bereich.right() - self.width() - 4)
            y = min(y, bereich.bottom() - self.height() - 4)
            x, y = max(x, bereich.left() + 4), max(y, bereich.top() + 4)
        self.move(x, y)
        self.show()
        self.raise_()
        QApplication.instance().installEventFilter(self)

    # -- Schliessen ---------------------------------------------------------------

    def hide(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hide()

    def eventFilter(self, obj, event) -> bool:
        """Klick daneben oder Escape schliesst — ohne etwas zu waehlen."""
        if not self.isVisible():
            return False
        if event.type() == QEvent.MouseButtonPress:
            globale = getattr(event, "globalPosition", None)
            punkt = (globale().toPoint() if callable(globale)
                     else QPoint(event.globalX(), event.globalY()))
            if not self.geometry().contains(punkt):
                self.hide()
        elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.hide()
        return False

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        from PySide6.QtGui import QColor, QPen

        p.setBrush(QColor(24, 24, 28, 238))
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
