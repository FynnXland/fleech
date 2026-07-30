"""Aufnahme-Overlay im Wispr-Flow-Stil: dunkle Pille mit X · Waveform · Haken.

Design (bewusst ohne Live-Transkriptionstext — clean, unauffaellig, nicht stoerend):
- links:  ✕ = Aufnahme verwerfen (kein Paste, keine Verarbeitung)
- Mitte:  Live-Audiopegel — Punktreihe bei Stille, Balken beim Sprechen,
          sanfte Welle waehrend der Verarbeitung
- rechts: ✓ = Aufnahme beenden und normal verarbeiten/einfuegen
- eigene Inseln aussen: Modus-Punkt (links) und ⏸ Pause (rechts)

Die zentrale Kapsel bleibt bewusst SYMMETRISCH (✕ · Waveform · ✓). Der Pause-Knopf
sass kurzzeitig mit darin und hat die Mitte verschoben — er gehoert auf die rechte
Insel, wo vorher der »-Knopf fuer den Befehls-Modus lag (nie benutzt, deshalb aus
der Pille entfernt; das gesprochene Safe-Word funktioniert unveraendert weiter).

Eigenschaften wie gehabt: frei verschiebbar (Position persistiert), nimmt NIE den
Fokus (WindowDoesNotAcceptFocus → WS_EX_NOACTIVATE: Buttons sind klickbar, ohne dem
Ziel-Textfeld den Fokus zu klauen), Sichtbarkeits-Modi + DND/Gaming-Override,
Transparenz-Regler. Default-Position: rechter Rand, vertikal ~mittig.
"""

from __future__ import annotations

import logging
import math
from collections import deque

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QToolTip, QWidget,
)

from ..usersettings import OverlaySettings
from .state import AppState

log = logging.getLogger(__name__)

# Pillen-Optik: die groessere, randlose „cleane" Pille (bewusste Nutzer-Entscheidung
# NACH dem Design-Import — das Konzept mit Punkt/Buttons bleibt, nur die Kapseln
# tragen KEINEN neutralen Rahmen und die Basishoehe bleibt bei 44).
PILL_WIDTH, PILL_HEIGHT = 272, 44
_BG = QColor(24, 24, 28, 235)
_BG_ARMED = QColor(16, 44, 52, 240)   # Befehls-Modus erkannt: dunkles Cyan
_BG_PROMPT = QColor(56, 42, 16, 240)  # KI-Prompting aktiv: dunkles Amber
_BG_PAUSED = QColor(30, 30, 34, 235)  # Pause: sichtbar matter als die Aufnahme
_PROMPT_ACCENT = QColor(232, 161, 60)  # #E8A13C — Prompting-Akzent (Rahmen + Punkt)
# Auto-Gain der Waveform (rein optisch, beeinflusst die Erkennung NICHT):
# FLOOR = leiseste Lautstaerke, die noch als „da spricht jemand" gilt — darunter
# wird nicht hochskaliert, sonst zappelt Stille auf Vollausschlag.
# DECAY = wie schnell der gemerkte Spitzenwert wieder faellt (pro 50-ms-Tick),
# damit die Anzeige nach einem lauten Wort nicht dauerhaft klein bleibt.
_AGC_FLOOR = 0.035
_AGC_DECAY = 0.985
_AGC_MAX_FACTOR = 45.0

_BAR = QColor(232, 232, 236)
_BAR_DIM = QColor(150, 150, 158)
_ACCENT = QColor(53, 192, 216)  # #35C0D8 — Brand-Akzent (✓, Edit-Modus-Rahmen)
_MARGIN = 24  # Abstand zum Bildschirmrand fuer die Presets
_FALLBACK_FLASH_MS = 3000  # so lange bleibt der Haken nach einem Fallback amber
# Formel-Vorschau: laenger als das normale Transkript, weil man eine Formel
# tatsaechlich LESEN muss — aber ohne Bestaetigungsklick, der den Fluss braeche.
_FORMULA_PREVIEW_MS = 5000


def _guessed_line(formulas: list) -> str:
    """Eine kurze Zeile fuer geratene Formeln — in LESBARER Form.

    In der Pille ist `\\sqrt{x} - c + \\frac{c}{2}` kaum zu pruefen; genau das muss
    man aber auf einen Blick erfassen koennen. Angezeigt wird deshalb `√x - c + c/2`.
    Eingefuegt wird weiterhin das echte LaTeX. Bewusst nur EINE Zeile ohne
    Erklaerung: Der Hinweis erscheint mitten im Schreiben, dort zaehlt Kuerze."""
    from ..formula import readable

    return "⚠ geraten: " + " · ".join(readable(f) for f in formulas)


def _dropped_line(dropped: str) -> str:
    """Eine Zeile fuer den verworfenen Halluzinations-Schwanz.

    Zeigt den ANFANG des Verworfenen, nicht nur die Wortzahl: Nur so kann man
    erkennen, ob der Guard danebenlag und wirklich Gesagtes getroffen hat.
    Kurz gehalten — der Hinweis erscheint mitten im Schreiben."""
    words = dropped.split()
    preview = " ".join(words[:6])
    if len(words) > 6:
        preview += " …"
    return f"⚠ {len(words)} Wörter verworfen: {preview}"

# Groessen-Presets: skalieren Pille, Buttons und Icons gemeinsam.
SIZE_FACTORS = {"compact": 0.85, "normal": 1.0, "large": 1.2}

# Positions-Presets: Schluessel → Anzeigename. "custom" = frei gezogen.
OVERLAY_PRESETS = [
    ("right_center", "Rechts"),
    ("left_center", "Links"),
    ("top_center", "Oben"),
    ("bottom_center", "Unten"),
]


def preset_position(preset: str, geom: QRect, w: int, h: int) -> tuple[int, int]:
    """Berechnet die Pillen-Position fuer ein Preset aus der Bildschirmgeometrie."""
    right = geom.right() - w - _MARGIN
    left = geom.left() + _MARGIN
    top = geom.top() + _MARGIN
    bottom = geom.bottom() - h - _MARGIN
    cx = geom.left() + (geom.width() - w) // 2
    # vertikal „mittig" bewusst leicht oberhalb der Mitte (optisch ruhiger) — so
    # sah die urspruengliche Default-Position aus, die bleibt damit identisch.
    vy = geom.top() + int(geom.height() * 0.42)
    return {
        "right_center": (right, vy),
        "left_center": (left, vy),
        "top_center": (cx, top),
        "bottom_center": (cx, bottom),
        "bottom_right": (right, bottom),
    }.get(preset, (right, vy))


class WaveformWidget(QWidget):
    """Pegelanzeige: scrollende Balken (Aufnahme), Sinus-Welle (Verarbeitung),
    Punktreihe (Stille/idle). level_provider liefert RMS ~0–0.5."""

    BARS = 13
    TICK_MS = 50

    def __init__(self, level_provider, parent=None, gain_provider=lambda: 1.0):
        super().__init__(parent)
        self._provider = level_provider
        self._gain = gain_provider  # Nutzer-Empfindlichkeit (settings.overlay.level_gain)
        self._levels = deque([0.0] * self.BARS, maxlen=self.BARS)
        self._peak = 0.0     # lautester Pegel der laufenden Aufnahme (Auto-Gain)
        self._state = AppState.IDLE
        self._armed = False  # Befehls-Modus erkannt → Balken in Akzentfarbe
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        self.setMinimumWidth(self.BARS * 5)  # Balken skalieren mit der Breite (Gap adaptiv)

    def _scaled(self, raw: float, gain: float) -> float:
        """Rohpegel → Balkenhoehe 0–1, mit automatischer Anpassung an das Mikrofon.

        Das Problem war rein optisch, aber stoerend: Ein leises Mikrofon liefert
        RMS-Werte um 0,02 — mit festem Faktor 7 schlaegt die Waveform dann kaum
        aus, obwohl die Erkennung einwandfrei laeuft. Der manuelle Regler konnte
        das zwar ausgleichen, aber nur, wenn man ihn kennt und pro Mikrofon neu
        einstellt.

        Deshalb merkt sich die Anzeige jetzt den lautesten Pegel der laufenden
        Aufnahme und skaliert darauf. Zwei Sicherungen: Ein Referenzwert unter
        `_AGC_FLOOR` wird ignoriert (sonst wuerde Stille auf Vollausschlag
        verstaerkt und jedes Rascheln zappelt), und der Faktor ist gedeckelt.
        Der Nutzer-Regler wirkt weiterhin obendrauf — Automatik ersetzt ihn nicht,
        sie macht ihn nur meistens ueberfluessig.
        """
        self._peak = max(self._peak * _AGC_DECAY, raw)
        reference = max(self._peak, _AGC_FLOOR)
        factor = min(_AGC_MAX_FACTOR, 0.85 / reference)
        return max(0.0, min(1.0, raw * factor * gain))

    def set_armed(self, armed: bool) -> None:
        if armed != self._armed:
            self._armed = armed
            self.update()

    def set_state(self, state: AppState) -> None:
        self._state = state
        if state is AppState.LISTENING:
            self._levels.extend([0.0] * self.BARS)  # frisch starten
            self._peak = 0.0                        # Auto-Gain je Aufnahme neu
        self._sync_timer()
        self.update()

    def _sync_timer(self) -> None:
        """Animations-Timer nur laufen lassen, wenn wirklich animiert wird.

        Die Idle-Punktreihe ist statisch — bei Sichtbarkeit "immer" wuerde der
        50-ms-Tick sonst dauerhaft (20x/s) feuern, ohne etwas zu bewegen.
        """
        busy = self._state in (AppState.LISTENING, AppState.PROCESSING)
        if busy and self.isVisible():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self) -> None:
        if self._state is AppState.LISTENING:
            try:
                raw = float(self._provider())
            except Exception:
                raw = 0.0
            try:
                gain = float(self._gain())
            except Exception:
                gain = 1.0
            self._levels.append(self._scaled(raw, gain))
            self.update()
        elif self._state is AppState.PROCESSING:
            self._phase += 0.35
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        width, height = self.width(), self.height()
        bar_w = 3.0
        gap = (width - self.BARS * bar_w) / max(1, self.BARS - 1)
        max_h = height - 8.0
        cy = height / 2.0
        for i in range(self.BARS):
            if self._state is AppState.PROCESSING:
                pulse = 0.5 + 0.5 * math.sin(self._phase + i * 0.55)
                h = 3.0 + pulse * 7.0
                painter.setBrush(_BAR_DIM)
            else:
                h = 3.0 + self._levels[i] * max_h
                active = _ACCENT if self._armed else _BAR
                painter.setBrush(active if self._levels[i] > 0.02 else _BAR_DIM)
            x = i * (bar_w + gap)
            painter.drawRoundedRect(QRectF(x, cy - h / 2, bar_w, h), bar_w / 2, bar_w / 2)


def _glyph_icon(kind: str, color: QColor = _BAR) -> QIcon:
    """X-/Haken-Icon per QPainter — fontunabhaengig (✕/✓-Glyphen fehlen je nach
    Font-Stack und rendern sonst als leere Kaestchen)."""
    pm = QPixmap(24, 24)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(color, 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if kind == "x":
        p.drawLine(QPointF(8, 8), QPointF(16, 16))
        p.drawLine(QPointF(16, 8), QPointF(8, 16))
    elif kind == "pause":
        # Zwei Balken. Gefuellt statt gestrichelt: der Knopf soll auch bei 16 px
        # noch eindeutig sein, und Striche wuerden mit der Waveform verschwimmen.
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        # Breiter und weiter auseinander als der erste Entwurf: dort verschmolzen
        # die schmalen Striche mit der Punktreihe der Waveform daneben und sahen
        # aus wie ein Teil der Anzeige statt wie ein Knopf (im Render gesehen).
        p.drawRoundedRect(QRectF(7.6, 7.0, 3.4, 10), 1.4, 1.4)
        p.drawRoundedRect(QRectF(13.0, 7.0, 3.4, 10), 1.4, 1.4)
    elif kind == "resume":
        # Dreieck „weiter". Gleiche optische Masse wie die Pausenbalken, damit der
        # Knopf beim Umschalten nicht zu springen scheint.
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPolygon([QPointF(9, 7), QPointF(17, 12), QPointF(9, 17)])
    else:  # check
        p.drawPolyline([QPointF(7, 12.5), QPointF(10.5, 16), QPointF(17, 8.5)])
    p.end()
    return QIcon(pm)


class _StatusDot(QWidget):
    """Kreis-Indikator links in der Pille — zeigt ZWEI unabhaengige Dinge:

    1. Der KERN: dezenter Ring = normales Diktat, amber gefuellt = KI-Prompting
       eingerastet. Klick schaltet Prompting an/aus.
    2. Der kleine SATELLIT unten rechts (cyan): Fleech erinnert sich an Diktate im
       aktuellen Fenster — nur dann greifen Befehle mit Bezug („mach den letzten
       Satz formeller"). Reine Information, nicht klickbar.

    Bewusst getrennt gehalten: Der eine sagt „welcher Modus", der andere „worauf
    beziehen sich Befehle". Beides in einem Element waere nicht unterscheidbar."""

    clicked = Signal()
    _COLORS = {"prompt": _PROMPT_ACCENT}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = ""  # "" (nichts aktiv) | "prompt"
        self._hover = False
        # Session-Badge: kleiner gedaempfter Satellit unten rechts — „Fleech
        # erinnert sich an Diktate in diesem Fenster". Bewusst im Status-Punkt
        # statt als eigenes Widget: kein neues Layout-/Insel-Geflecht fuer eine
        # reine Information.
        self._session = False
        self._session_readonly = False
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hover = False
        self.update()

    def set_mode(self, mode: str) -> None:
        if mode != self._mode:
            self._mode = mode
            self.update()

    def set_session(self, active: bool, readonly: bool = False) -> None:
        if active != self._session or readonly != self._session_readonly:
            self._session, self._session_readonly = active, readonly
            self.update()

    def paintEvent(self, event) -> None:
        # Cleaner Look: gefuellter Punkt mit weichem Schein in der Modus-Farbe,
        # sonst dezenter Ring (hellt beim Hover leicht auf — klickbar erkennbar).
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2.0, self.height() / 2.0)
        r = min(self.width(), self.height()) * 0.22
        accent = self._COLORS.get(self._mode)
        if accent is not None:
            glow = QColor(accent)
            glow.setAlpha(70)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(c, r * 1.9, r * 1.9)     # weicher Schein
            p.setBrush(accent)
            p.drawEllipse(c, r, r)                  # gefuellter Kern
        else:
            p.setPen(QPen(_BAR if self._hover else _BAR_DIM, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r, r)                  # dezenter Ring
        self._paint_session_badge(p, c, r)

    def _paint_session_badge(self, p, c: QPointF, r: float) -> None:
        """Kleiner gedaempfter Satellit unten rechts: gemerkter Diktat-Kontext.
        Gedaempft (kein Alarm, reine Information) und klar abgesetzt vom
        Modus-Kern, damit er nie mit einem aktiven Modus verwechselt wird."""
        if not self._session:
            return
        badge = QColor(_ACCENT)
        mitte = QPointF(c.x() + r * 1.9, c.y() + r * 1.9)
        radius = r * 0.45
        if self._session_readonly:
            # HOHL = Kontext nur lesbar (nach Fensterwechsel kein Ersetzen). Bewusst
            # dieselbe Farbe und Groesse: Es ist derselbe Sachverhalt in einem
            # anderen Zustand, keine neue Warnung.
            badge.setAlpha(210)
            p.setBrush(Qt.NoBrush)
            pen = QPen(badge)
            pen.setWidthF(max(1.0, r * 0.16))
            p.setPen(pen)
            p.drawEllipse(mitte, radius, radius)
            return
        badge.setAlpha(170)
        p.setPen(Qt.NoPen)
        p.setBrush(badge)
        p.drawEllipse(mitte, radius, radius)


def _button_style(radius: int) -> str:
    return (
        f"QPushButton {{ background: rgba(255,255,255,26); border: none;"
        f"  border-radius: {radius}px; }}"
        "QPushButton:hover { background: rgba(255,255,255,55); }"
        "QPushButton:pressed { background: rgba(255,255,255,80); }"
        "QPushButton:disabled { background: rgba(255,255,255,10); }"
    )


# Glyph-Farben der Pillen-Buttons (Design-System): ✓ traegt den Akzent,
# ✕ neutral, » gedimmt (leuchtet cyan, wenn der Befehls-Modus scharf ist).
_GLYPH_COLORS = {"check": _ACCENT, "x": _BAR,
                 # Pause so hell wie das ✕ (beides neutrale Bedienelemente),
                 # „weiter" im Prompting-Amber — dieselbe Farbe, die die Pille im
                 # Pausenzustand traegt.
                 "pause": _BAR, "resume": _PROMPT_ACCENT}


def _round_button(kind: str, tooltip: str) -> QPushButton:
    btn = QPushButton()
    btn.setIcon(_glyph_icon(kind, _GLYPH_COLORS.get(kind, _BAR)))
    btn.setIconSize(QSize(16, 16))
    btn.setFixedSize(28, 28)
    btn.setToolTip(tooltip)
    btn.setFocusPolicy(Qt.NoFocus)  # nie Fokus ziehen — Ziel-Textfeld bleibt aktiv
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(_button_style(14))
    return btn


class TranscriptCaption(QWidget):
    """Dunkle Sprechblase ueber der Pille — zeigt kurz den erkannten Text bzw. im
    Bearbeiten-Modus einen Ziehen-Hinweis. Reine Anzeige (klick-transparent), klaut
    nie den Fokus."""

    MAX_WIDTH = 420
    LIVE_LABEL_WIDTH = 340  # feste Label-Breite fuer die Live-Vorschau (kein Springen)

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("color: #E8E8EC; font-size: 10pt;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.addWidget(self._label)
        self._accent_color = None  # QColor | None — None = randlos
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def paintEvent(self, event) -> None:
        # Clean: randlose dunkle Blase (Akzent-Rahmen nur im Hervorhebungs-Fall).
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self._accent_color, 1.4) if self._accent_color else Qt.NoPen)
        painter.setBrush(_BG)
        r = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(r, 11, 11)

    def show_above(self, anchor: QRect, text: str, *, sticky: bool = False,
                   accent: bool = False, duration_ms: int = 4200,
                   single_line: bool = False, force_below: bool = False,
                   accent_color=None) -> None:
        text = (text or "").strip()
        if not text:
            self.hide()
            return
        # accent=True → Brand-Cyan (Edit-Hinweis); accent_color uebersteuert die Farbe
        # (z. B. amber bei Rohtext-Fallback).
        self._accent_color = accent_color or (_ACCENT if accent else None)
        fm = QFontMetrics(self._label.font())
        if single_line:
            # Live-Vorschau: EINE Zeile, feste Breite (Blase springt nicht mehr),
            # links elidiert — die zuletzt erkannten Woerter laufen rechts auf.
            width = self.LIVE_LABEL_WIDTH
            self._label.setWordWrap(False)
            # rechtsbuendig: das ZULETZT erkannte Wort steht immer rechts, komplett
            # sichtbar; links faellt aelterer Text mit „…" weg.
            self._label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            # etwas Puffer, damit das rechte Wort nicht am Rand angeschnitten wird.
            text = fm.elidedText(text, Qt.ElideLeft, width - 8)
        else:
            # Breite an den Text anpassen, aber gedeckelt (dann bricht der Text um).
            width = min(self.MAX_WIDTH, fm.horizontalAdvance(text) + 30)
            self._label.setWordWrap(True)
            self._label.setAlignment(Qt.AlignCenter)
        self._label.setFixedWidth(width)
        self._label.setText(text)
        self.adjustSize()
        # Horizontal auf die Pille zentriert. Vertikal: 10 px darueber (Live-Vorschau)
        # oder — force_below/kein Platz oben — 10 px DARUNTER, im selben Abstand.
        x = anchor.center().x() - self.width() // 2
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        avail = screen.availableGeometry()
        x = max(avail.left() + 6, min(x, avail.right() - self.width() - 6))
        y = anchor.top() - self.height() - 10
        if force_below or y < avail.top() + 6:
            y = anchor.bottom() + 10
        self.move(x, y)
        self.show()
        self.raise_()
        if sticky:
            self._timer.stop()
        else:
            self._timer.start(duration_ms)


class OverlayWindow(QWidget):
    cancel_requested = Signal()   # ✕ — verwerfen ohne Verarbeitung
    finish_requested = Signal()   # ✓ — beenden und einfuegen
    mode_toggle_requested = Signal()  # Modus-Punkt geklickt — KI-Prompting an/aus
    pause_requested = Signal()    # ⏸ — Aufnahme anhalten/fortsetzen

    def __init__(self, settings: OverlaySettings, on_geometry_changed=None,
                 level_provider=lambda: 0.0):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus,
        )
        self.settings = settings
        self._on_geometry_changed = on_geometry_changed or (lambda: None)
        self._drag_offset = None
        self._state = AppState.IDLE
        self._focus_override: str | None = None
        self._edit_mode = False
        self._caption = TranscriptCaption()
        # Eigene Blase fuer die Hover-Erklaerungen — dieselbe zentrierte Optik wie die
        # Live-Transkription, nur unterhalb der Pille (statt QToolTip, dessen Breite bei
        # umbrechendem Text nicht exakt zentrierbar ist).
        self._tip_caption = TranscriptCaption()
        self._caption_is_live = False  # zeigt die Blase gerade die Live-Vorschau?
        self._caption_is_status = False  # … oder einen Fortschritts-Hinweis?
        self._command_armed = False    # Signalwort in der Live-Vorschau erkannt
        self._prompt_latched = False   # KI-Prompting-Latch aktiv (exklusiv zu Mathe)
        self._paused = False           # Aufnahme angehalten (Pause-Knopf)

        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._apply_click_through()

        self._layout = layout = QHBoxLayout(self)
        # Margins/Spacing/Luecken werden in _apply_scale aus der Pillenhoehe gesetzt.
        layout.setContentsMargins(9, 8, 9, 8)
        layout.setSpacing(6)
        # Ganz links (eigene Insel, ausserhalb der Waveform): Mathe-Status-Kreis —
        # leuchtet bei aktivem Mathe-Modus. Nur sichtbar, wenn Mathe aktiv ist.
        self._math_dot = _StatusDot()
        self._cancel_btn = _round_button("x", "Aufnahme verwerfen")
        self._finish_btn = _round_button("check", "Fertig — Text einfügen")
        # Ganz rechts (eigene Insel): Aufnahme anhalten/fortsetzen.
        self._pause_btn = _round_button("pause", "Pause — Aufnahme anhalten")
        # Luecken-Widgets trennen die drei Inseln sichtbar (transparenter Zwischenraum,
        # der auch zum Ziehen der Pille dient). Ihre Groesse setzt _apply_scale.
        self._gap_l = QWidget()
        self._gap_r = QWidget()
        # WICHTIG: das Lambda darf NICHT `self` fangen — es liegt als Attribut im
        # Kind-Widget und wuerde einen Python-Referenzzyklus Parent↔Kind erzeugen.
        # Qt-Widgets in GC-Zyklen werden in undefinierter Reihenfolge zerstoert →
        # sporadische Access Violations (real aufgetreten). `settings` ist ein
        # reines Dataclass-Objekt, dieselbe Instanz wie im Settings-UI (live).
        _settings_ref = settings
        self._wave = WaveformWidget(
            level_provider,
            gain_provider=lambda: getattr(_settings_ref, "level_gain", 1.0),
        )
        layout.addWidget(self._math_dot)
        layout.addWidget(self._gap_l)
        layout.addWidget(self._cancel_btn)
        layout.addWidget(self._wave, 1)
        layout.addWidget(self._finish_btn)
        layout.addWidget(self._gap_r)
        layout.addWidget(self._pause_btn)
        self._cancel_btn.clicked.connect(self.cancel_requested.emit)
        self._finish_btn.clicked.connect(self.finish_requested.emit)
        self._pause_btn.clicked.connect(self.pause_requested.emit)
        self._math_dot.clicked.connect(self.mode_toggle_requested.emit)

        # Erklaerende Tooltips — beim laengeren Hover eingeblendet, UNTERHALB der Pille
        # (oben liegt die Live-Transkription). Der Event-Filter faengt das ToolTip-
        # Ereignis ab und positioniert den Hinweis mittig unter der Pille.
        self._cancel_btn.setToolTip("Abbrechen — nichts einfügen")
        self._finish_btn.setToolTip("Fertig — Text einfügen")
        self._dot_tooltip_base = (
            "Modus (Klick wechselt): Aus → Mathe → KI-Prompting. "
            "Violett = Mathe, Amber = KI-Prompting. "
            "Geteilt = beide zugleich (Formel im Prompt, während der Aufnahme)."
        )
        self._math_dot.setToolTip(self._dot_tooltip_base)
        # Tooltips auch bei INAKTIVEM Fenster zeigen: das Overlay ist ein Tool-Fenster
        # ohne Fokus — ohne dieses Attribut unterdrueckt Qt die Tooltips komplett.
        self.setAttribute(Qt.WA_AlwaysShowToolTips, True)
        for w in (self._math_dot, self._cancel_btn, self._pause_btn, self._finish_btn):
            w.setAttribute(Qt.WA_AlwaysShowToolTips, True)
            w.installEventFilter(self)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        # Rohtext-Fallback: Haken kurz amber, danach zurueck auf Akzent.
        self._fallback_active = False
        # Formeln des laufenden Diktats — werden von der Transkript-Blase abgeholt.
        self._pending_formulas: list = []
        # Verworfener Halluzinations-Schwanz, ebenfalls von der Blase abgeholt.
        self._pending_dropped: str = ""
        self._fallback_timer = QTimer(self)
        self._fallback_timer.setSingleShot(True)
        self._fallback_timer.timeout.connect(self._clear_fallback_flash)

        # Pille folgt dem Monitor des Mauszeigers (Setting) — leichter Poll, laeuft
        # nur solange die Pille sichtbar ist (showEvent/hideEvent syncen).
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(700)
        self._follow_timer.timeout.connect(self._follow_mouse_screen_tick)

        self.apply_settings()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Befehls-Modus erkannt (Signalwort in der Live-Vorschau): Pille faerbt sich
        # dunkel-cyan mit Akzent-Rahmen — sichtbares "Ich habe verstanden, das ist
        # ein Befehl", bevor die Verarbeitung startet.
        # Der vertikale Rand ist Teil des HINTERGRUNDS: die Buttons sind per
        # contentsMargins eingerueckt, der Hintergrund fuellt die volle Fensterhoehe.
        h = self.height()
        pl = getattr(self, "_pill_pad_l", 4)
        pr = getattr(self, "_pill_pad_r", 4)
        fill = _BG_ARMED if self._command_armed else _BG
        border = _ACCENT if self._command_armed else None
        if self._paused:
            # Pause gewinnt gegen jeden Modus-Zustand: waehrend der Pause laeuft
            # nichts ins Diktat, das muss die Pille auf einen Blick sagen.
            fill, border = _BG_PAUSED, _BAR_DIM
        # isHidden() statt isVisible(): spiegelt den expliziten Zeige-Zustand,
        # unabhaengig davon, ob das Fenster gerade sichtbar ist.
        math_on = not self._math_dot.isHidden()
        pause_on = not self._pause_btn.isHidden()
        if getattr(self.settings, "separate_islands", True):
            # Drei getrennte Hintergruende: die zentrale Pille bleibt vollstaendig,
            # auch wenn eine Rand-Insel fehlt. Ihr Padding kommt aus den vier Randwerten.
            left = self._cancel_btn.geometry().left() - pl
            right = self._finish_btn.geometry().right() + pr
            self._draw_bg(painter, QRectF(left, 0, right - left, h), fill, border)
            if math_on:
                # Modus-Insel dauerhaft sichtbar: neutral | violett (Mathe) |
                # amber (Prompting) | GETEILTER Rahmen bei BEIDEN (wie der Punkt).
                island = self._island_rect(self._math_dot)
                if self._prompt_latched:
                    m_fill, m_border = _BG_PROMPT, _PROMPT_ACCENT
                else:
                    m_fill, m_border = _BG, None
                self._draw_bg(painter, island, m_fill, m_border)
            if pause_on:
                # Pausen-Insel neutral halten: sie zeigt ihren Zustand ueber die
                # Glyphe (⏸/▶). Ein farbiger Hintergrund waere ein zweites Signal
                # fuer dieselbe Sache.
                self._draw_bg(painter, self._island_rect(self._pause_btn), _BG, None)
        else:
            # Durchgehende Pille: EIN Hintergrund von der linkesten bis zur rechtesten
            # sichtbaren Zelle; die vier Randwerte polstern diese eine Pille.
            left_w = self._math_dot if math_on else self._cancel_btn
            right_w = self._pause_btn if pause_on else self._finish_btn
            left = left_w.geometry().left() - pl
            right = right_w.geometry().right() + pr
            # Bei BEIDEN Modi bleibt die Pille neutral — der geteilte Punkt ist der
            # Indikator (sonst wuerde eine Farbe faelschlich „gewinnen").
            rect = QRectF(left, 0, right - left, h)
            if not self._command_armed and self._prompt_latched:
                fill, border = _BG_PROMPT, _PROMPT_ACCENT
            self._draw_bg(painter, rect, fill, border)

    def _draw_bg(self, painter, rect: QRectF, fill: QColor, border) -> None:
        # Clean: neutrale Kapseln OHNE Rahmen; nur Modus-Zustaende bekommen einen.
        if border is not None:
            painter.setPen(QPen(border, 1.4))
            rect = rect.adjusted(1, 1, -1, -1)
        else:
            painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        r = min(rect.width(), rect.height()) / 2.0  # Kapsel/Kreis je nach Seitenverhaeltnis
        painter.drawRoundedRect(rect, r, r)

    def _island_rect(self, w) -> QRectF:
        """Voll-hohe Kapsel, zentriert auf dem Rand-Widget. Breite = Basishoehe → ein
        Kreis bei 0 vertikalem Rand, sonst eine vertikale Kapsel (folgt der Hoehe mit)."""
        cx = w.geometry().center().x() + 0.5
        iw = getattr(self, "_island_w", self.height())
        return QRectF(cx - iw / 2.0, 0, iw, self.height())

    def eventFilter(self, obj, event) -> bool:
        """Hover-Erklaerungen als eigene Blase MITTIG UNTER der Pille anzeigen —
        gespiegelt zur Live-Transkription (gleicher Abstand, gleiche Zentrierung).
        Sie bleibt sichtbar, solange die Maus auf dem Element ist, und schliesst beim
        Verlassen (Leave)."""
        etype = event.type()
        if etype == QEvent.ToolTip:
            text = obj.toolTip() if hasattr(obj, "toolTip") else ""
            if text:
                self._tip_caption.show_above(
                    self.frameGeometry(), text, sticky=True, force_below=True,
                )
            return True  # Qt-Standard-Tooltip unterdruecken
        if etype == QEvent.Leave:
            self._tip_caption.hide()
        return super().eventFilter(obj, event)

    def set_command_armed(self, armed: bool) -> None:
        """Signalwort live erkannt → Pille + Waveform in Befehls-Optik schalten."""
        if armed == self._command_armed:
            return
        self._command_armed = armed
        self._wave.set_armed(armed)
        self.update()

    def set_prompt_latched(self, latched: bool) -> None:
        """KI-Prompting-Latch an/aus → amberfarbene Pille + Punkt, dauerhaft sichtbar."""
        if latched == self._prompt_latched:
            return
        self._prompt_latched = latched
        self._apply_latch_visuals()

    def _apply_latch_visuals(self) -> None:
        """Punkt-Farbe + Sichtbarkeit fuer die Modus-Latches nachziehen.

        Solange EIN Latch aktiv ist, bleibt die Pille sichtbar (persistenter
        Indikator), auch bei Sichtbarkeit „nur waehrend Aufnahme". Beim Ausrasten
        wird die normale Sichtbarkeitslogik wiederhergestellt."""
        if self._prompt_latched:
            mode = "prompt"
        else:
            mode = ""
        self._math_dot.set_mode(mode)
        latched = bool(mode)
        if latched and not self._edit_mode and self._effective_visibility() != "off":
            self.show()
        elif not latched and not self._edit_mode:
            if self._effective_visibility() == "during_activity" \
                    and self._state is AppState.IDLE:
                self.hide()
        self.update()

    # -- Einstellungen (auch live aus dem Settings-Fenster) ----------------------------

    def _screen_geometry(self) -> QRect:
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry()

    def _edge_pads(self) -> tuple[int, int, int, int]:
        """Nutzer-Raender (links, rechts, oben, unten) in px, vor Skalierung."""
        s = self.settings
        return (max(0, int(getattr(s, "edge_left", 10))),
                max(0, int(getattr(s, "edge_right", 10))),
                max(0, int(getattr(s, "edge_top", 0))),
                max(0, int(getattr(s, "edge_bottom", 0))))

    def pill_size(self) -> tuple[int, int]:
        factor = SIZE_FACTORS.get(getattr(self.settings, "size", "normal"), 1.0)
        # Die Nutzer-Raender vergroessern das Overlay nach aussen (Inhalt zentriert,
        # Waveform bleibt gleich gross).
        pl, pr, pt, pb = self._edge_pads()
        return (round((PILL_WIDTH + pl + pr) * factor),
                round((PILL_HEIGHT + pt + pb) * factor))

    def _apply_scale(self) -> None:
        # Basisgroessen aus der INNEREN Pillenhoehe ableiten (ohne Nutzer-Raender),
        # damit Buttons/Icons bei jedem Rand identisch gross bleiben.
        factor = SIZE_FACTORS.get(getattr(self.settings, "size", "normal"), 1.0)
        h = round(PILL_HEIGHT * factor)
        self._island_w = h              # Insel-Kapselbreite = Basishoehe (Kreis bei 0 Rand)
        vmargin = max(5, round(h * 0.18))
        spacing = max(4, round(h * 0.13))
        btn = h - 2 * vmargin           # Button fuellt die Hoehe zwischen den Raendern
        icon = round(btn * 0.58)
        self._bg_pad = max(3, round(spacing * 0.7))  # Basis-Rand des Pillen-Hintergrunds
        # Die vier Nutzer-Raender sind das PADDING des Haupt-Pillen-Hintergrunds (nicht
        # transparenter Aussenraum). Vertikal: die Buttons werden eingerueckt, der
        # Hintergrund fuellt die volle Fensterhoehe → mehr Hintergrund oben/unten. Die
        # Rand-Inseln (Mathe-Punkt, Trigger) folgen automatisch in der Hoehe.
        el, er, et, eb = self._edge_pads()
        el, er = round(el * factor), round(er * factor)
        et, eb = round(et * factor), round(eb * factor)
        self._pill_pad_l = self._bg_pad + el   # linkes/rechtes Padding im Pillen-Hintergrund
        self._pill_pad_r = self._bg_pad + er
        base_hmargin = vmargin + 2      # >= vmargin: Insel-Kapsel ragt nie ueber den Rand
        separate = getattr(self.settings, "separate_islands", True)
        base_gap = max(6, round(h * 0.30)) if separate else max(3, round(h * 0.08))
        if separate:
            # Getrennte Inseln: das links/rechts-Padding der Pille steckt in den Luecken —
            # die Inseln bleiben am Rand, die Pille dehnt sich hinein, der sichtbare
            # Abstand Insel↔Pille bleibt konstant.
            left_m = right_m = base_hmargin
            gap_l, gap_r = base_gap + el, base_gap + er
        else:
            # Durchgehende Pille: das Padding dehnt die Aussenkanten → aeussere Margins.
            left_m, right_m = base_hmargin + el, base_hmargin + er
            gap_l = gap_r = base_gap
        self._layout.setContentsMargins(left_m, vmargin + et, right_m, vmargin + eb)
        self._layout.setSpacing(spacing)
        for b in (self._cancel_btn, self._pause_btn, self._finish_btn):
            b.setFixedSize(btn, btn)
            b.setIconSize(QSize(icon, icon))
            b.setStyleSheet(_button_style(btn // 2))
        self._math_dot.setFixedSize(btn, btn)  # gleiche Zellgroesse → Symmetrie
        self._gap_l.setFixedWidth(gap_l)
        self._gap_r.setFixedWidth(gap_r)

    def apply_settings(self) -> None:
        s = self.settings
        self.setWindowOpacity(max(0.2, min(1.0, s.opacity)))
        self._apply_click_through()
        self._apply_scale()
        w, h = self.pill_size()
        geom = self._screen_geometry()
        # Preset "" migrieren: vorhandene x/y = frei gezogen (custom), sonst Default.
        if not s.position:
            s.position = "custom" if (s.x is not None and s.y is not None) else "right_center"
        if s.position != "custom":
            s.x, s.y = preset_position(s.position, geom, w, h)
        elif s.x is None or s.y is None:
            s.x, s.y = preset_position("right_center", geom, w, h)
        self.setFixedSize(w, h)
        self.setGeometry(s.x, s.y, w, h)
        self._sync_follow_timer()
        self.update()  # Stil-/Groessenwechsel (z. B. getrennte Inseln ↔ Pille) neu zeichnen
        if self._edit_mode:
            self.show()
        elif s.visibility == "always":
            self.show()
        elif s.visibility == "off" or self._state is AppState.IDLE:
            self.hide()

    def _apply_click_through(self) -> None:
        # Im Bearbeiten-Modus IMMER klickbar (sonst laesst sich die Pille nicht ziehen).
        through = bool(self.settings.click_through) and not self._edit_mode
        self.setAttribute(Qt.WA_TransparentForMouseEvents, through)

    # -- Positions-Presets, Reset, Bearbeiten-Modus ------------------------------------

    def apply_preset(self, preset: str) -> None:
        w, h = self.pill_size()
        self.settings.position = preset
        self.settings.x, self.settings.y = preset_position(
            preset, self._screen_geometry(), w, h
        )
        self.setGeometry(self.settings.x, self.settings.y, w, h)
        if self._edit_mode:
            self._show_edit_hint()
        self._on_geometry_changed()

    # -- Monitor des Mauszeigers folgen ---------------------------------------------

    def _sync_follow_timer(self) -> None:
        wanted = bool(getattr(self.settings, "follow_mouse_screen", False)) \
            and self.isVisible()
        if wanted and not self._follow_timer.isActive():
            self._follow_timer.start()
        elif not wanted and self._follow_timer.isActive():
            self._follow_timer.stop()

    def _follow_mouse_screen_tick(self) -> None:
        if self._drag_offset is not None or self._edit_mode:
            return  # niemals gegen aktives Ziehen/Bearbeiten kaempfen
        from PySide6.QtGui import QCursor

        target = QApplication.screenAt(QCursor.pos())
        if target is None or target == self.screen():
            return
        self._move_to_screen(target)

    def _move_to_screen(self, screen) -> None:
        """Pille auf einen anderen Monitor uebertragen: Presets werden dort neu
        berechnet, eine freie (custom) Position wird RELATIV uebertragen."""
        w, h = self.pill_size()
        geom = screen.availableGeometry()
        if self.settings.position != "custom":
            x, y = preset_position(self.settings.position, geom, w, h)
        else:
            cur = self._screen_geometry()
            rel_x = (self.x() - cur.left()) / max(1, cur.width() - w)
            rel_y = (self.y() - cur.top()) / max(1, cur.height() - h)
            x = geom.left() + round(max(0.0, min(1.0, rel_x)) * (geom.width() - w))
            y = geom.top() + round(max(0.0, min(1.0, rel_y)) * (geom.height() - h))
        self.settings.x, self.settings.y = x, y
        self.move(x, y)
        if self._caption.isVisible():
            self._caption.hide()  # Blase haengt sonst auf dem alten Monitor

    def reset_position(self) -> None:
        self.apply_preset("right_center")

    def is_edit_mode(self) -> bool:
        return self._edit_mode

    def toggle_edit_mode(self) -> bool:
        """Umschalten: Pille dauerhaft anzeigen + ziehbar machen. Gibt neuen Zustand."""
        if self._edit_mode:
            self._edit_mode = False
            self._caption.hide()
            self._apply_click_through()
            self.settings.x, self.settings.y = self.x(), self.y()
            self._on_geometry_changed()
            self.apply_settings()  # normale Sichtbarkeit wiederherstellen
        else:
            self._edit_mode = True
            self._apply_click_through()
            self.show()
            self.raise_()
            self._show_edit_hint()
        return self._edit_mode

    def _show_edit_hint(self) -> None:
        self._caption.show_above(
            self.frameGeometry(),
            "Zum Verschieben ziehen — dann „Fertig“ klicken",
            sticky=True, accent=True,
        )

    def show_formula_preview(self, formulas: list) -> None:
        """Geratene Formeln sichtbar machen — unabhaengig von der Transkript-Anzeige.

        formulas: [(latex, war_geraten)].

        Zwei Wege, je nach Einstellung. Ist die Transkript-Blase an, haengt
        `show_transcript` den Hinweis dort an (zwei Blasen kurz hintereinander
        wuerden sich gegenseitig ueberschreiben). Ist sie AUS, kommt hier eine
        eigene, kurze Blase — denn eine Bestaetigung darf man abschalten, eine
        Warnung nicht: Wer sie ausblendet, will weniger Bestaetigung, nicht
        weniger Sicherheit. Zusaetzlich blinkt der Haken amber; das ist das
        einzige Signal, das auch bei voellig ausgeschaltetem Text ankommt.
        """
        self._pending_formulas = list(formulas or [])
        guessed = [tex for tex, was_guessed in self._pending_formulas if was_guessed]
        if not guessed or self._edit_mode:
            return
        self._flash_check()            # Haken kurz amber = „schau hier nach"
        if self.settings.show_transcript:
            return                     # der Hinweis reist mit der Transkript-Blase
        self._pending_formulas = []
        self._caption_is_live = False
        self._caption_is_status = False
        self._caption.show_above(
            self.frameGeometry(), _guessed_line(guessed),
            duration_ms=_FORMULA_PREVIEW_MS,
            accent_color=_PROMPT_ACCENT,
        )

    def show_dropped_tail(self, dropped: str) -> None:
        """Melden, dass ein zerfallener Transkript-Schwanz verworfen wurde.

        Gleiche Logik wie bei der Formel-Vorschau, aber mit hoeherem Anspruch: Hier
        wurde etwas GELOESCHT. Wer die Transkript-Blase abschaltet, will weniger
        Bestaetigung — nicht weniger Sicherheit. Deshalb kommt die Meldung in dem
        Fall als eigene Blase, und der Haken blinkt in jedem Fall amber.
        """
        dropped = (dropped or "").strip()
        if not dropped or self._edit_mode:
            return
        self._pending_dropped = dropped
        self._flash_check()
        if self.settings.show_transcript:
            return                     # reist mit der Transkript-Blase mit
        self._pending_dropped = ""
        self._caption_is_live = False
        self._caption_is_status = False
        self._caption.show_above(
            self.frameGeometry(), _dropped_line(dropped),
            duration_ms=_FORMULA_PREVIEW_MS,
            accent_color=_PROMPT_ACCENT,
        )

    def show_transcript(self, text: str) -> None:
        """Erkannten Text kurz ueber der Pille einblenden (nach dem Diktat)."""
        if self._edit_mode or not self.settings.show_transcript:
            return
        # Endtranskript = KEINE Live-Vorschau mehr → das folgende set_state(IDLE)
        # darf diese Blase nicht als haengengebliebene Vorschau wieder verstecken.
        self._caption_is_live = False
        self._caption_is_status = False   # Endtranskript loest die Fortschritts-Blase ab
        clipped = text if len(text) <= 240 else text[:240].rsplit(" ", 1)[0] + " …"
        # Formel-Hinweis anhaengen: Wurde eine Formel GERATEN (die gesprochene
        # Fassung liess mehrere Lesarten zu), steht das direkt unter dem Text —
        # sichtbar, solange die Blase steht, ohne den Diktier-Fluss zu bremsen.
        guessed = [tex for tex, was_guessed in getattr(self, "_pending_formulas", [])
                   if was_guessed]
        self._pending_formulas = []
        if guessed:
            clipped += "\n" + _guessed_line(guessed)
        dropped = getattr(self, "_pending_dropped", "")
        self._pending_dropped = ""
        if dropped:
            clipped += "\n" + _dropped_line(dropped)
        # Nach einem Rohtext-Fallback bekommt die Blase einen amber Rahmen — dieselbe
        # Farbe wie der blinkende Haken, damit beides als ein Signal lesbar ist.
        warned = bool(guessed or dropped)
        self._caption.show_above(
            self.frameGeometry(), clipped,
            duration_ms=_FORMULA_PREVIEW_MS if warned else 4200,
            accent_color=(_PROMPT_ACCENT
                          if (self._fallback_active or warned) else None),
        )

    def show_progress(self, text: str) -> None:
        """Laengeren Zwischenschritt ueber der Pille anzeigen ("Modell wird geladen …").

        Nutzt dieselbe Blase wie Live-Vorschau und Endtranskript — dort schaut man
        beim Diktieren ohnehin hin. Der bisherige Weg (nur Tooltip) war zu versteckt:
        waehrend eines Kaltstarts (~13 s) sah man lediglich "verarbeitet"."""
        if self._edit_mode or not text or self._state is not AppState.PROCESSING:
            return
        self._caption_is_live = False
        self._caption_is_status = True
        self._caption.show_above(self.frameGeometry(), text, sticky=True)

    def _clear_status_caption(self) -> None:
        if self._caption_is_status:
            self._caption_is_status = False
            self._caption.hide()

    def flash_fallback(self) -> None:
        """Sichtbar machen, dass der Text als ROHTEXT kam (Modell nicht erreichbar
        oder Ausgabe verworfen): der Haken wird kurz amber statt cyan, und die
        Transkript-Blase bekommt denselben amber Rahmen.

        Bewusst kein Toast: Ton und Statuszeile melden den Fallback bereits, und die
        Banner-Politik lautet „so wenig wie moeglich". Was fehlte, war ein Signal
        genau dort, wo der Nutzer beim Diktieren hinschaut."""
        self._fallback_active = True
        self._flash_check()

    def _flash_check(self) -> None:
        """Haken kurz amber faerben = „schau hier bitte nach".

        Getrennt von `flash_fallback`, weil es zwei verschiedene Anlaesse gibt
        (Rohtext-Fallback und geratene Formel) — nur die Optik ist dieselbe. Wuerde
        die Formel-Warnung `_fallback_active` mitsetzen, waere die Transkript-Blase
        faelschlich als Fallback markiert."""
        self._finish_btn.setIcon(_glyph_icon("check", _PROMPT_ACCENT))
        self._fallback_timer.start(_FALLBACK_FLASH_MS)

    def _clear_fallback_flash(self) -> None:
        self._fallback_active = False
        self._finish_btn.setIcon(_glyph_icon("check", _ACCENT))

    LIVE_WORDS = 18  # nur die zuletzt erkannten Woerter tragen (Rest elidiert die Blase)

    def show_live_text(self, text: str) -> None:
        """Grobe Echtzeit-Vorschau WAEHREND der Aufnahme (PreviewStreamer): eine Zeile
        mit fester Breite, in der die zuletzt erkannten Woerter auflaufen — statt
        einer springenden, mehrzeiligen Blase."""
        if self._edit_mode or self._state is not AppState.LISTENING \
                or not getattr(self.settings, "live_preview", False):
            return
        words = (text or "").split()
        if not words:
            return
        self._caption_is_live = True
        self._caption.show_above(
            self.frameGeometry(), " ".join(words[-self.LIVE_WORDS:]),
            sticky=True, single_line=True,
        )

    def _hide_live_caption(self) -> None:
        self._caption_is_live = False
        self._caption.hide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_follow_timer()
        # Sofort-Check: die Pille soll direkt auf dem Maus-Monitor erscheinen,
        # nicht erst nach dem ersten Timer-Tick.
        if getattr(self.settings, "follow_mouse_screen", False):
            self._follow_mouse_screen_tick()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._follow_timer.stop()
        self._tip_caption.hide()  # Hover-Blase nie ohne die Pille stehen lassen

    # -- Fokus-Override (DND/Gaming) — Verhalten wie zuvor ------------------------------

    def set_focus_override(self, override: str | None) -> None:
        if override == self._focus_override:
            return
        self._focus_override = override
        if self._edit_mode:
            return  # Bearbeiten hat Vorrang: Pille bleibt sichtbar
        if override == "hidden":
            self.hide()
        elif self._effective_visibility() != "always" and self._state is AppState.IDLE:
            self.hide()
        elif self._effective_visibility() == "always":
            self.show()

    def _effective_visibility(self) -> str:
        if self._focus_override == "hidden":
            return "off"
        if self._focus_override in ("activity_only", "compact") and \
                self.settings.visibility == "always":
            return "during_activity"
        return self.settings.visibility

    # -- Statusanzeige -------------------------------------------------------------------

    def set_app_state(self, state: AppState) -> None:
        self._state = state
        self._wave.set_state(state)
        busy = state in (AppState.LISTENING, AppState.PROCESSING)
        self._cancel_btn.setEnabled(state is AppState.LISTENING)
        self._finish_btn.setEnabled(state is AppState.LISTENING)
        self._pause_btn.setEnabled(state is AppState.LISTENING)
        if state is not AppState.LISTENING:
            self.set_command_armed(False)  # Befehls-Optik endet mit der Aufnahme
            # Pause endet IMMER mit der Aufnahme. Bliebe die Optik stehen, zeigte
            # die naechste Aufnahme einen Pausenknopf, der nichts pausiert hat.
            self.set_paused(False)
        if state is not AppState.PROCESSING:
            # Fortschritts-Hinweis gehoert zur Verarbeitung — danach nie stehen lassen.
            self._clear_status_caption()
        if state is AppState.LISTENING:
            self._caption.hide()  # alte Transkript-Einblendung wegnehmen
            self.set_command_armed(False)  # neue Aufnahme startet neutral
        elif state is AppState.PROCESSING and self._caption_is_live:
            # Live-Vorschau beenden — das FINALE Transkript kommt (falls aktiviert)
            # gleich per transcript_ready; bei "nichts erkannt" bliebe sie sonst haengen.
            self._hide_live_caption()
        elif state is AppState.IDLE and self._caption_is_live:
            # Abbruch (LISTENING→IDLE ohne PROCESSING/transcript_ready): die sticky
            # Live-Vorschau wuerde sonst haengen bleiben (Nutzer-Bug: X gedrueckt →
            # Blase blieb bis zum Neustart). Ein echtes Endtranskript hat _is_live
            # bereits auf False gesetzt und wird hier NICHT versteckt.
            self._hide_live_caption()
        if self._edit_mode:
            return  # im Bearbeiten-Modus bleibt die Pille sichtbar
        visibility = self._effective_visibility()
        if visibility == "off":
            return
        if busy:
            self._hide_timer.stop()
            self.show()
        elif self._prompt_latched:
            self.show()  # Latch-Indikator bleibt sichtbar, auch wenn gerade nichts laeuft
        elif visibility == "during_activity":
            self.hide()
        elif visibility == "auto_hide":
            self._hide_timer.start(int(max(0.5, self.settings.auto_hide_seconds) * 1000))

    def set_mode_line(self, text: str) -> None:
        self.setToolTip(text)  # unauffaellig: Modus-Info nur als Tooltip

    def set_paused(self, paused: bool) -> None:
        """Pausenzustand anzeigen: Knopf-Glyphe, ruhende Waveform, matte Pille.

        Die Waveform geht bewusst in den IDLE-Zustand (Punktreihe) statt auf
        flache Balken: eine Reihe stiller Balken saehe aus wie „Mikrofon hoert zu,
        du bist nur leise" — genau die Verwechslung, die hier teuer waere.
        """
        if paused == self._paused:
            return
        self._paused = paused
        self._pause_btn.setIcon(_glyph_icon(
            "resume" if paused else "pause",
            _GLYPH_COLORS["resume" if paused else "pause"],
        ))
        self._pause_btn.setToolTip(
            "Weiter — Aufnahme fortsetzen" if paused else "Pause — Aufnahme anhalten"
        )
        self._wave.set_state(AppState.IDLE if paused else AppState.LISTENING)
        # Bewusst NICHT ueber show_progress(): das gilt nur waehrend der
        # Verarbeitung. Hier laeuft die Aufnahme (Zustand LISTENING) und steht
        # trotzdem still — der Hinweis muss genau dann erscheinen.
        if paused:
            self._caption_is_live = False
            self._caption_is_status = True
            self._caption.show_above(
                self.frameGeometry(), "Pause — es wird nichts aufgenommen", sticky=True,
            )
        else:
            self._clear_status_caption()
        self.update()

    def set_session_info(self, info) -> None:
        """Session-Punkt: info = (bloecke, minuten[, nur_lesbar]) | None.

        Beantwortet die Frage „warum greift mein Befehl (nicht)?" direkt an der
        Pille — und zwar VORHER. Drei Zustaende:

        * kein Punkt — kein Kontext, ein Bezug wie „der letzte Satz" geht ins Leere.
        * gefuellter Punkt — Kontext da, Ersetzen moeglich.
        * hohler Punkt — Kontext nur LESBAR. Nach einem Fensterwechsel ist die
          Cursor-Position unbekannt, deshalb verweigert Fleech das Ersetzen. Das
          erfuhr man bisher erst, wenn der Befehl schon gesprochen war; genau das
          hat ein externes Gutachten als den fehlenden Handgriff benannt.
        """
        nur_lesbar = bool(info) and len(info) > 2 and info[2]
        self._math_dot.set_session(bool(info), nur_lesbar)
        if not info:
            self._math_dot.setToolTip(self._dot_tooltip_base)
            return
        chunks, minutes = info[0], info[1]
        wann = "gerade eben" if minutes < 1 else f"vor {minutes} min"
        text = (f"{self._dot_tooltip_base}\nErinnert sich an "
                f"{chunks} Diktat{'e' if chunks != 1 else ''} in diesem Fenster "
                f"({wann}).")
        if nur_lesbar:
            text += ("\nNur lesbar: Nach dem Fensterwechsel kann Fleech nicht mehr "
                     "ersetzen — diktiere einmal neu, dann geht es wieder.")
        self._math_dot.setToolTip(text)

    def set_feedback(self, text: str) -> None:
        if text:
            self.setToolTip(f"{self.toolTip().splitlines()[0] if self.toolTip() else ''}\n{text}".strip())

    # -- Verschieben per Maus + Persistenz -------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            if self._edit_mode:
                self._show_edit_hint()  # Hinweis folgt der Pille

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.settings.x, self.settings.y = self.x(), self.y()
            self.settings.position = "custom"  # frei positioniert
            self._on_geometry_changed()
