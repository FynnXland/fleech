"""Die eigenstaendigen Teile der Pille: Waveform, Status-Punkt, Textblase.

Echte Widgets, keine Mixins — sie haben eigenen Zustand und eigenes Zeichnen und
haengen nicht am Overlay-Fenster. `TranscriptCaption` wird dreimal verwendet
(Transkript, Hover-Erklaerung, Profilname).
"""

from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QWidget

from ..state import AppState
from .konstanten import (
    _BG,
    _PROMPT_ACCENT,
    _AGC_FLOOR,
    _AGC_DECAY,
    _AGC_MAX_FACTOR,
    _BAR,
    _BAR_DIM,
    _ACCENT,
    _KEIN_TON,
)

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
       aktiv (One-Shot ueber den Hotkey). Klick wechselt reihum zum naechsten
       Profil — NICHT das Prompting selbst; dauerhaftes Prompting laeuft ueber
       das Profil „KI-Prompt" (E-19).
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
        # Freihand lauscht: ein ruhig atmender Ring um den Punkt. Kein Blinken —
        # „hoert zu" ist ein Dauerzustand, und etwas dauerhaft Blinkendes am
        # Bildschirmrand macht muerbe.
        self._lauscht = False
        # Kein Ton vom Mikrofon (Befund H-B2): roter, gefuellter Punkt. Gewinnt
        # gegen jede andere Aussage des Punktes — welches Profil gilt, ist
        # zweitrangig, solange gar nichts ankommt.
        self._kein_ton = False
        # Farbe des aktiven Profils. Leer = wie frueher, dezent grau: Wer keine
        # Profile nutzt, soll keinen bunten Punkt bekommen, der etwas ankuendigt,
        # das es bei ihm gar nicht gibt.
        self._profil_farbe = ""
        # Klickbar NUR waehrend einer laufenden Aufnahme (siehe set_klickbar).
        # Bewusst hier und nicht per setEnabled(): Der Punkt bleibt ausserhalb
        # der Aufnahme voll sichtbar — er ist dort die Anzeige „welches Profil
        # gilt", und die soll nicht ausgegraut werden, nur weil man sie gerade
        # nicht anklicken kann.
        self._klickbar = False
        self.setFixedSize(28, 28)
        self.setCursor(Qt.ArrowCursor)

    def set_klickbar(self, an: bool) -> None:
        """Darf der Punkt gerade das Profil wechseln?

        Ausserhalb der Aufnahme nicht: Ein Klick haette dort keine sichtbare
        Folge ausser der kurzen Namens-Kapsel, waehrend die Pille am Bildschirm-
        rand liegt und beilaeufig getroffen wird. Wer vorher waehlen will,
        nimmt den Profil-Hotkey oder die Profilseite."""
        an = bool(an)
        if an == self._klickbar:
            return
        self._klickbar = an
        self.setCursor(Qt.PointingHandCursor if an else Qt.ArrowCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._klickbar:
            self.clicked.emit()
            event.accept()
            return
        # Nicht klickbar: Ereignis bewusst NICHT annehmen — dann traegt es die
        # Pille weiter und man kann sie auch am Punkt anfassen und verschieben.
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

    def set_profile_color(self, farbe: str) -> None:
        """Farbe des aktiven Profils — faerbt den RING, nicht die Fuellung.

        Die Trennung ist der Kern: Der Ring sagt „welches Profil gilt", die
        Fuellung sagt „ein Modus ist eingerastet". Beides auf die Fuellung zu
        legen haette die zweite Aussage geloescht — man haette nicht mehr
        unterschieden, ob KI-Prompting aktiv ist oder nur ein buntes Profil."""
        farbe = str(farbe or "")
        if farbe != self._profil_farbe:
            self._profil_farbe = farbe
            self.update()

    def set_lauscht(self, an: bool) -> None:
        if an != self._lauscht:
            self._lauscht = an
            self.update()

    def set_kein_ton(self, an: bool) -> None:
        """Warnzustand: vom Mikrofon kommt nichts an (Befund H-B2)."""
        if an != self._kein_ton:
            self._kein_ton = an
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
        eingerastet = self._COLORS.get(self._mode)
        # Die Profilfarbe faerbt, was ohnehin gezeichnet wird — sie ersetzt die
        # Modus-Aussage nicht. Eingerastet fuellt weiterhin, nur eben passend zum
        # Profil statt immer amber.
        profil = QColor(self._profil_farbe) if self._profil_farbe else None
        if profil is not None and not profil.isValid():
            profil = None
        if self._kein_ton:
            # Warnung schlaegt Profil und Modus: Es kommt kein Ton an, alles
            # andere ist in diesem Moment egal. Gefuellt mit Schein wie der
            # eingerastete Zustand — nur eben rot, und ohne Profilfarbe, die die
            # Aussage verwaessern wuerde.
            glow = QColor(_KEIN_TON)
            glow.setAlpha(80)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(c, r * 1.9, r * 1.9)
            p.setBrush(_KEIN_TON)
            p.drawEllipse(c, r, r)
            self._paint_session_badge(p, c, r)
            return
        if eingerastet is not None:
            ton = profil or QColor(eingerastet)
            glow = QColor(ton)
            glow.setAlpha(70)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(c, r * 1.9, r * 1.9)     # weicher Schein
            p.setBrush(ton)
            p.drawEllipse(c, r, r)                  # gefuellter Kern
        elif profil is not None:
            # Ruhezustand MIT Profil: kraeftiger Ring in Profilfarbe, innen leer.
            # Nicht gefuellt, weil „gefuellt" fuer eingerastet reserviert bleibt —
            # sonst waeren die beiden Zustaende nicht mehr zu unterscheiden.
            ring = QColor(profil)
            ring.setAlpha(255 if self._hover else 210)
            p.setPen(QPen(ring, 2.0))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r, r)
        else:
            p.setPen(QPen(_BAR if self._hover else _BAR_DIM, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r, r)                  # dezenter Ring wie bisher
        if self._lauscht and eingerastet is None:
            # Zweiter, weiterer Ring in Akzentfarbe: sichtbar genug, um „es hoert
            # mit" zu melden, ruhig genug, um dauerhaft dazustehen.
            #
            # Bleibt bewusst CYAN und nimmt NICHT die Profilfarbe an: „es hoert
            # mit" ist eine Aussage ueber das Mikrofon, nicht ueber das Profil.
            # Faerbte man ihn mit, waeren bei einem tuerkisen Profil beide Ringe
            # gleich und die Freihand-Anzeige praktisch unsichtbar.
            ring = QColor(_ACCENT)
            ring.setAlpha(150)
            p.setPen(QPen(ring, 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r * 1.75, r * 1.75)
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
