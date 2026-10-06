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
import sys

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QPainter
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

from ..profiles import APP_STANDARD
from .theme import ACCENT, TEXT

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
        self._wache = None      # QTimer — sieht Klicks in fremde Fenster

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
        self._starte_fremdklick_wache()

    # -- Schliessen ---------------------------------------------------------------

    def hide(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        if self._wache is not None:
            self._wache.stop()      # nicht weiterpollen, wenn nichts zu sehen ist
        super().hide()

    def eventFilter(self, obj, event) -> bool:
        """Klick daneben oder Escape schliesst — ohne etwas zu waehlen.

        Faengt nur, was FLEECH empfaengt. Der Normalfall ist ein Klick in eine
        fremde Anwendung — dafuer siehe `_pruefe_fremdklick`.
        """
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

    # -- Klick in eine FREMDE Anwendung --------------------------------------------
    #
    # Der eventFilter oben sieht davon nichts: Die Liste nimmt bewusst nie den
    # Fokus (sonst waere das Textfeld weg, in das gleich eingefuegt werden soll),
    # also gehen Klicks daneben direkt an die andere Anwendung und Qt erfaehrt es
    # nie. Gemeldet als „bleibt die ganze Zeit dort, bis was gedrueckt wird".
    #
    # Bewusst KEIN Qt.Popup: Das wuerde zwar global schliessen, aber den Mausklick
    # abfangen — man muesste zweimal klicken, und der erste Klick landete nicht
    # dort, wo man hinwollte. Bewusst auch kein Maus-Hook: Ein kurzes Polling der
    # Tastenzustaende reicht fuer ein Fenster, das Sekunden offen ist, und kommt
    # ohne zusaetzlichen Thread aus.

    _POLL_MS = 90          # unter der Wahrnehmungsschwelle, weit ueber dem Aufwand
    _MAUSTASTEN = (0x01, 0x02, 0x04)   # links, rechts, mitte

    def _starte_fremdklick_wache(self) -> None:
        if sys.platform != "win32":
            return          # X11: kein Aequivalent ohne zusaetzlichen Hook
        if self._wache is None:
            self._wache = QTimer(self)
            self._wache.setInterval(self._POLL_MS)
            self._wache.timeout.connect(self._pruefe_fremdklick)
        # Beim Start einmal leer lesen: GetAsyncKeyState meldet mit dem
        # Niederbit auch Druecke SEIT DEM LETZTEN AUFRUF. Ohne dieses Abholen
        # wuerde die Liste am Klick sterben, der sie gerade geoeffnet hat.
        self._gedrueckt()
        self._wache.start()

    @staticmethod
    def _gedrueckt() -> bool:
        import ctypes

        user32 = ctypes.windll.user32
        treffer = False
        for taste in ProfilePicker._MAUSTASTEN:
            if user32.GetAsyncKeyState(taste) & 0x0001:
                treffer = True
        return treffer

    def _pruefe_fremdklick(self) -> None:
        try:
            if not self._gedrueckt():
                return
        except Exception:
            log.debug("Maus-Abfrage fehlgeschlagen — Wache aus.", exc_info=True)
            if self._wache is not None:
                self._wache.stop()
            return
        # Auf der Liste selbst schliesst der Knopf-Klick ohnehin (mit Auswahl) —
        # hier nur schliessen, wenn wirklich daneben geklickt wurde.
        if not self.geometry().contains(QCursor.pos()):
            log.debug("Profil-Liste geschlossen (Klick daneben).")
            self.hide()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        from PySide6.QtGui import QColor, QPen

        p.setBrush(QColor(24, 24, 28, 238))
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
