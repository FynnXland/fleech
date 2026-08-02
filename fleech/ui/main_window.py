"""Hauptfenster im Flow-Stil, Dark Mode: Sidebar (Home · Insights · Einstellungen).

- Home:      "Willkommen zurueck" + Verlauf der Transkripte + Kurz-Stats.
- Insights:  Kennzahlen-Dashboard (Woerter/Minute, Korrekturen, Gesamtwoerter,
             App-Nutzung, Serien-Kalender) — alles lokal aus der Historie.
- Einstellungen: das bestehende SettingsPanel, eingebettet.

Schliessen minimiert in den Tray (DesktopApp-Verhalten unveraendert). Geometrie
persistiert in settings.window.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import logging
import sys
import time as _time

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QPushButton, QScrollArea,
    QSizeGrip, QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .. import __version__
from ..history import HistoryStore, Stats
from ..milestones import word_milestone
from ..usersettings import PROFILE_FORMATS, UserSettings

log = logging.getLogger(__name__)

# Brand-Farben (Dark) — Design-System-Token (claude.ai/design „Fleech Design System").
BG = "#16181C"
SIDEBAR = "#1A1D22"
CARD = "#22262E"
ACCENT = "#35C0D8"
ACCENT_DIM = "#219FB8"
TEXT = "#E8E8EC"
MUTED = "#8A8A92"
TRACK = "#2E3742"
NAV_ACTIVE_BG = "#243A40"
ROW_HOVER = "#2A2F3A"                       # Zeilen-/Control-Hover (eine Stufe heller)
BORDER_HAIRLINE = "rgba(255,255,255,0.06)"  # Hairline fuer Controls/Trenner
BORDER_CARD = "rgba(255,255,255,0.04)"      # noch dezenter: Karten-Rahmen
ON_ACCENT = "#0E2126"                       # dunkle Glyphe/Schrift AUF Akzentflaeche
DANGER_TEXT = "#E08585"                     # Danger-Buttons (Verlauf löschen)

_STREAK_SHADES = ["#2A313B", "#12525F", "#219FB8", "#35C0D8"]


def button_qss(variant: str = "default") -> str:
    """Button-Stile des Design-Systems: default (Karte + Hairline), primary
    (Akzent, dunkle Schrift), danger (rote Schrift, roter Hover), ghost (nackt)."""
    base = ("QPushButton { font-size: 9.5pt; font-weight: 500; border-radius: 8px;"
            "  padding: 6px 14px; }"
            "QPushButton:disabled { color: rgba(232,232,236,0.35); }")
    variants = {
        "default": (
            f"QPushButton {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; }}"
            f"QPushButton:hover {{ background: {ROW_HOVER}; }}"
            f"QPushButton:pressed {{ background: {SIDEBAR}; }}"
        ),
        "primary": (
            f"QPushButton {{ background: {ACCENT_DIM}; color: {ON_ACCENT};"
            f"  border: none; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {ACCENT}; }}"
            f"QPushButton:pressed {{ background: {ACCENT_DIM}; }}"
        ),
        "danger": (
            f"QPushButton {{ background: {CARD}; color: {DANGER_TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; }}"
            f"QPushButton:hover {{ background: rgba(220,90,90,0.16);"
            f"  border-color: rgba(220,90,90,0.4); }}"
        ),
        "ghost": (
            f"QPushButton {{ background: transparent; color: {MUTED}; border: none; }}"
            f"QPushButton:hover {{ background: {CARD}; color: {TEXT}; }}"
        ),
    }
    return base + variants.get(variant, variants["default"])


def style_button(btn: QPushButton, variant: str = "default") -> QPushButton:
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(button_qss(variant))
    return btn

def _processing_summary(stats) -> str:
    """Text der "Verarbeitung"-Karte: Ø Latenzen, Routing-Verteilung, Fallback-Quote."""
    if not stats.avg_stt_ms and not (stats.tier_shares or {}):
        return "Noch keine Daten — Latenzen werden ab dem nächsten Diktat erfasst."
    lines = []
    if stats.avg_stt_ms or stats.avg_llm_ms:
        total_s = (stats.avg_stt_ms + stats.avg_llm_ms) / 1000
        lines.append(
            f"Ø Verarbeitung: {total_s:.1f} s — davon {stats.avg_stt_ms / 1000:.1f} s "
            f"Erkennung · {stats.avg_llm_ms / 1000:.1f} s KI-Bereinigung"
        )
    shares = stats.tier_shares or {}
    if shares:
        tier_names = (("trivial", "ohne KI"), ("simple", "schnelles Modell"),
                      ("complex", "großes Modell"))
        parts = [f"{round(shares[key] * 100)} % {label}"
                 for key, label in tier_names if key in shares]
        lines.append("Routing: " + " · ".join(parts))
    lines.append(f"Fallback-Quote: {round(stats.fallback_rate * 100)} % "
                 f"(Diktate, die auf das Roh-Transkript zurückfielen)")
    return "\n".join(lines)


# Ab wie vielen Tagen ohne Sichtung ein zugewiesener Prozess als verdaechtig gilt.
# Bewusst grosszuegig: eine App, die man nur monatlich braucht, soll nicht sofort
# als Fehler markiert werden — es geht um Tippfehler und umbenannte Programme.
_STALE_APP_DAYS = 30

# Vorschlaege: wie viele gleichzeitig gezeigt werden und wie viele dafuer geprueft
# werden (Puffer fuer uebernommene/ignorierte, damit Nachruecker sichtbar werden).
_ADVICE_SHOWN = 3
_ADVICE_SCAN = 12




def _latency_trend_line(store) -> str:
    """Kurzer Verlauf der KI-Latenz — macht Modell-Kaltstarts sichtbar (ein einzelner
    Ausreisser nach oben ist fast immer ein Kaltstart, kein langsameres Modell)."""
    try:
        days = store.latency_by_day(days=14)
    except Exception:
        return ""
    if len(days) < 2:
        return ""
    values = [ms for _day, ms in days]
    best, worst = min(values), max(values)
    if worst <= 0:
        return ""
    line = f"\nKI-Latenz der letzten {len(values)} Tage: {values[-1] / 1000:.1f} s zuletzt"
    if worst >= best * 2 and worst - best > 2000:
        line += (f" · Spanne {best / 1000:.1f}–{worst / 1000:.1f} s "
                 f"(Ausreisser = Modell-Kaltstart)")
    return line


# Anzeigetexte fuer history.Stats.productive_daypart ("Deine Muster"-Karte).
_DAYPART_LABELS = {
    "morgens": "morgens (5–11 Uhr)",
    "mittags": "mittags (11–14 Uhr)",
    "nachmittags": "nachmittags (14–18 Uhr)",
    "abends": "abends (18–23 Uhr)",
    "nachts": "nachts (23–5 Uhr)",
}


def _logo_pixmap(size: int = 26, dpr: float = 1.0) -> QPixmap:
    """Brand-Waveform (5 Balken) in Akzentfarbe — wie Tray/Overlay, eine Sprache.

    Rendert in Geraetepixeln (dpr) und setzt devicePixelRatio → auch auf HiDPI scharf."""
    px = max(1, round(size * dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(ACCENT))
    heights = (0.42, 0.68, 1.0, 0.68, 0.42)
    bar_w = px * 0.13
    gap = (px - 5 * bar_w) / 4
    for i, h in enumerate(heights):
        bh = px * h
        x = i * (bar_w + gap)
        p.drawRoundedRect(QRectF(x, (px - bh) / 2, bar_w, bh), bar_w / 2, bar_w / 2)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def _nav_icon(kind: str, color: str) -> QIcon:
    pm = QPixmap(20, 20)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if kind == "home":
        p.drawPolyline([QPointF(3, 10), QPointF(10, 3.5), QPointF(17, 10)])
        p.drawRect(QRectF(5.5, 10, 9, 6.5))
    elif kind == "chart":
        p.drawLine(5, 16, 5, 10)
        p.drawLine(10, 16, 10, 5)
        p.drawLine(15, 16, 15, 8)
    elif kind == "profile":
        # Person: Kopf + Schulterbogen
        p.drawEllipse(QRectF(7, 3.5, 6, 6))
        p.drawArc(QRectF(4.5, 11, 11, 10), 0, 180 * 16)
    elif kind == "apps":
        # Vier Kacheln — die uebliche Bildsprache fuer „Anwendungen"; klar
        # unterscheidbar von den Reglern der Einstellungen daneben.
        for x, y in ((3.5, 3.5), (11, 3.5), (3.5, 11), (11, 11)):
            p.drawRoundedRect(QRectF(x, y, 5.5, 5.5), 1.5, 1.5)
    else:  # sliders
        for y, knob_x in ((5, 13), (10, 7), (15, 11)):
            p.drawLine(4, y, 16, y)
            p.setBrush(QColor(color))
            p.drawEllipse(knob_x - 2, y - 2, 4, 4)
    p.end()
    return QIcon(pm)


def _x_icon(color: str) -> QIcon:
    """Kleines ×-Icon per QPainter (fontunabhaengig) fuer den Loeschen-Button."""
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 1.6, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(5, 5), QPointF(11, 11))
    p.drawLine(QPointF(11, 5), QPointF(5, 11))
    p.end()
    return QIcon(pm)


class HelpBadge(QLabel):
    """Kleines „?" neben einer Bezeichnung. Die Erklaerung erscheint beim Hover als
    Tooltip UNTERHALB des Badges (stabil: verschwindet nicht, solange die Maus auf dem
    Badge bleibt). Bewusst KEIN setToolTip: der Qt-Standardpfad zeigt den Tooltip an
    der Maus und ueberdeckt das Element — hier positionieren enter/leaveEvent selbst.
    """

    def __init__(self, tip: str = ""):
        super().__init__("?")
        self._tip = ""
        self.set_tip(tip)
        self.setFixedSize(15, 15)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)  # kein „?"-Mauszeiger — der stoert
        # Design-System: TRACK-Kachel (5px Radius), Hover kippt auf NAV_ACTIVE_BG + Akzent.
        self.setStyleSheet(
            f"QLabel {{ background: {TRACK}; color: {MUTED}; border: none;"
            f"  border-radius: 5px; font-size: 7.5pt; font-weight: 600; }}"
            f"QLabel:hover {{ background: {NAV_ACTIVE_BG}; color: {ACCENT}; }}"
        )

    def set_tip(self, tip: str) -> None:
        # <qt> aktiviert Rich-Text → der Tooltip bricht um statt einzeilig auszuufern.
        self._tip = f"<qt>{tip}</qt>" if tip else ""

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if self._tip:
            from PySide6.QtCore import QPoint
            from PySide6.QtWidgets import QToolTip

            # Unterhalb des Badges (= unterhalb des Mauszeigers) zeigen; das rect haelt
            # ihn stabil offen, solange der Cursor auf dem Badge bleibt.
            below = self.mapToGlobal(QPoint(-6, self.height() + 8))
            QToolTip.showText(below, self._tip, self, self.rect(), 30000)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        from PySide6.QtWidgets import QToolTip

        QToolTip.hideText()


def _no_hscroll(lst) -> None:
    """Liste umbrechen statt horizontal scrollen: lange Eintraege (z. B. der
    „Alle"-Fallback oder App-Namen mit Zusatz) gehen in eine zweite Zeile, statt
    eine horizontale Scrollleiste am unteren Rand zu erzeugen."""
    lst.setWordWrap(True)
    lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    lst.setTextElideMode(Qt.ElideNone)


def _dauer(sekunden: float) -> str:
    """Sekunden → „46 s" | „3 min" | „1 h 12 min" | „15,1 Stunden".

    Vier Stufen statt einer Formel: „0,05 h" sagt niemandem etwas, „906 min" auch
    nicht mehr. Unter einer Minute braucht es Sekunden — sonst wird ein Diktat von
    46 s zu „1 min", und der Schnitt je Diktat waere fuer alle gleich. Ab zehn
    Stunden ist umgekehrt die Minute belanglos; dort ist die Dezimalstunde die
    Zahl, die man weitererzaehlt.
    """
    sekunden = max(0.0, float(sekunden or 0.0))
    if sekunden < 60:
        return f"{sekunden:.0f} s"
    minuten = sekunden / 60.0
    if minuten < 60:
        return f"{minuten:.0f} min"
    stunden, rest = int(minuten // 60), int(minuten) % 60
    if stunden < 10:
        return f"{stunden} h {rest} min" if rest else f"{stunden} h"
    return f"{minuten / 60.0:.1f} Stunden".replace(".", ",")


def _diktierzeit_text(stats) -> str:
    """Zeile unter dem Tacho: gesprochene Zeit gesamt und je Diktat."""
    gesamt = getattr(stats, "total_audio_seconds", 0.0) or 0.0
    anzahl = getattr(stats, "total_dictations", 0) or 0
    if gesamt <= 0:
        return "Noch keine Sprechzeit aufgezeichnet."
    text = f"{_dauer(gesamt)} gesprochen"
    if anzahl:
        text += f" · Ø {_dauer(gesamt / anzahl)} je Diktat"
    return text


def _suchfeld(platzhalter: str):
    """Schmales Suchfeld ueber einer Liste — Apps- und Profilseite teilen es sich,
    damit Suchen an beiden Stellen gleich aussieht und sich gleich anfuehlt.

    Escape leert das Feld: Wer nach der Suche wieder alles sehen will, soll nicht
    ruecklaufend loeschen muessen.
    """
    from PySide6.QtWidgets import QLineEdit

    feld = QLineEdit()
    feld.setPlaceholderText(platzhalter)
    feld.setClearButtonEnabled(True)
    feld.setStyleSheet(
        f"QLineEdit {{ background: {CARD}; color: {TEXT};"
        f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
        f"  padding: 5px 9px; font-size: 9pt; }}"
        f"QLineEdit:focus {{ border-color: {ACCENT}; }}")
    return feld


def _passt(text: str, suche: str) -> bool:
    """Einfache Teilstring-Suche, Gross-/Kleinschreibung egal.

    Bewusst kein Fuzzy-Matching: Die Listen sind kurz, und ein „ungefaehrer"
    Treffer, den man nicht erklaeren kann, kostet mehr Vertrauen als er Tipparbeit
    spart. Mehrere Woerter muessen ALLE vorkommen (Reihenfolge egal) — so findet
    „code fleech" die Titel-Regel, ohne dass man sie exakt abtippt.
    """
    suche = (suche or "").strip().lower()
    if not suche:
        return True
    ziel = (text or "").lower()
    return all(teil in ziel for teil in suche.split())


def enable_card_hiding(frame: QFrame, title: str, attr: str, settings, on_changed) -> None:
    """Rechtsklick auf eine Karte → „Ausblenden".

    Ersetzt elf Checkboxen auf einer eigenen Einstellungs-Seite. Wer eine Karte
    nicht sehen will, schaut sie in dem Moment an — dort gehoert die Handlung hin,
    nicht in eine Liste, in der man erst den passenden Namen suchen muss.
    Zurueckholen geht gesammelt in den Einstellungen (Allgemein)."""
    from PySide6.QtWidgets import QMenu

    frame.setContextMenuPolicy(Qt.CustomContextMenu)
    # Daten am Widget statt im Lambda: ein Lambda, das `self`/settings faengt und
    # am Kind-Widget haengt, erzeugt Referenzzyklen (real: Access Violations).
    frame.setProperty("hide_attr", attr)
    frame.setProperty("hide_title", title)

    def _menu(pos, _frame=frame, _settings=settings, _changed=on_changed):
        menu = QMenu(_frame)
        action = menu.addAction(f"„{_frame.property('hide_title')}“ ausblenden")
        if menu.exec(_frame.mapToGlobal(pos)) is action and action is not None:
            setattr(_settings.interface, _frame.property("hide_attr"), False)
            _settings.save()
            _frame.hide()
            if callable(_changed):
                _changed("interface")

    frame.customContextMenuRequested.connect(_menu)


# Zeitraeume der Insights: (Schluessel, Beschriftung, Tage | None fuer „alles").
# Bewusst kurz gehalten — vier Knoepfe passen in die Kopfzeile, sieben nicht.
INSIGHT_RANGES = (("day", "Heute"), ("week", "7 Tage"),
                  ("month", "30 Tage"), ("all", "Alle"))
_RANGE_DAYS = {"day": 1, "week": 7, "month": 30, "all": None}


def _card(title: str = "", header_action: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    # WICHTIG: per objectName scopen — ein unscoped "QFrame {...}" kaskadiert auf
    # ALLE Kind-Widgets (QLabel erbt von QFrame) und malt Pillen hinter Labels.
    # Design-System: flache Karte, 10px Radius, dezente Hairline.
    frame.setStyleSheet(
        f"QFrame#card {{ background: {CARD}; border-radius: 10px;"
        f"  border: 1px solid {BORDER_CARD}; }}"
    )
    box = QVBoxLayout(frame)
    box.setContentsMargins(14, 12, 14, 12)
    box.setSpacing(8)
    if title or header_action:
        header = QHBoxLayout()
        if title:
            label = QLabel(title)
            # Karten-Titel: gedaempft, klein, semibold (Inhalt traegt die Betonung).
            label.setStyleSheet(
                f"color: {MUTED}; font-weight: 600; font-size: 9pt;"
                f" letter-spacing: 0.3px; border: none;"
            )
            header.addWidget(label)
        header.addStretch(1)
        if header_action:
            header.addWidget(header_action)
        box.addLayout(header)
    return frame, box


def _link_button(text: str) -> QPushButton:
    """Dezenter, textartiger Button fuer Karten-Header (z. B. "Alle anzeigen")."""
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFlat(True)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setStyleSheet(
        f"QPushButton {{ color: {ACCENT_DIM}; background: transparent; border: none;"
        f"  font-size: 8.5pt; padding: 0; }}"
        f"QPushButton:hover {{ color: {ACCENT}; }}"
    )
    return btn


def _ranked_row(name_text: str, share: float, value_text: str) -> QWidget:
    """Eine Zeile einer Balken-Rangliste (App-Nutzung, Häufigste Wörter): Name,
    Balken (UsageBar, share 0..1) und ein rechtsbuendiger Wert."""
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 2, 0, 2)
    h.setSpacing(10)
    name = QLabel(name_text)
    name.setStyleSheet(f"color: {TEXT}; font-size: 9.5pt; border: none;")
    name.setFixedWidth(96)
    bar = UsageBar()
    bar.set_share(share)
    value = QLabel(value_text)
    value.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; font-weight: 500; border: none;")
    value.setFixedWidth(40)
    # AlignRight ALLEIN verwirft die vertikale Zentrierung des Labels — der Wert
    # saesse sonst hoeher als Balken und Name.
    value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    h.addWidget(name)
    h.addWidget(bar, 1)
    h.addWidget(value)
    return row


def _rebuild_ranked_list(box: QVBoxLayout, rows: list[QWidget], entries,
                         empty_text: str) -> list[QWidget]:
    """Ersetzt die Zeilen einer Rangliste durch `entries` ([(name, share, value), ...])."""
    for row in rows:
        # erst aus Layout nehmen und verstecken, sonst wird die alte Zeile bis zum
        # naechsten Event-Loop-Durchlauf weitergemalt (Ghost-Widgets/Duplikate).
        box.removeWidget(row)
        row.hide()
        row.deleteLater()
    new_rows = []
    if not entries:
        empty = QLabel(empty_text)
        empty.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        box.addWidget(empty)
        new_rows.append(empty)
        return new_rows
    for name_text, share, value_text in entries:
        row = _ranked_row(name_text, share, value_text)
        box.addWidget(row)
        new_rows.append(row)
    return new_rows


def _metric(title: str, value: str = "0") -> tuple[QFrame, QVBoxLayout, QLabel]:
    """KPI-Karte im Design-System-Stil: gedaempfter Titel im Karten-Header,
    grosse Kennzahl (28px/21pt) darunter; Detailzeilen haengt der Aufrufer an."""
    frame, box = _card(title)
    value_label = QLabel(value)
    value_label.setStyleSheet(
        f"color: {TEXT}; font-size: 21pt; font-weight: 600; border: none;"
    )
    box.addWidget(value_label)
    return frame, box, value_label


class UsageBar(QWidget):
    """Balken fuer App-Nutzung: selbst gemalt statt QFrame+qlineargradient-Stops.

    Der fruehere CSS-Gradient-Trick (Hard-Stop bei "share") loeste die Stop-Position
    beim allerersten Polish VOR der finalen Layout-Breite auf und cachte sie —
    danach blieb JEDE Fuellung (unabhaengig vom tatsaechlichen Anteil) auf die
    Breite zu diesem fruehen Zeitpunkt eingefroren (sichtbar als winziger Streifen
    bei allen Balken). paintEvent nutzt dagegen IMMER die aktuelle Breite."""

    def __init__(self):
        super().__init__()
        self.share = 0.0
        self.setFixedHeight(6)  # Design-System: schlanker 6px-Balken, Radius 3

    def set_share(self, share: float) -> None:
        self.share = max(0.0, min(1.0, share))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        w, h = self.width(), self.height()
        radius = h / 2.0
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, w, h), QColor(TRACK))
        if self.share > 0:
            fill_w = min(w, max(h, w * self.share))  # Mindestbreite: sichtbarer Punkt
            p.fillRect(QRectF(0, 0, fill_w, h), QColor(ACCENT_DIM))


class WpmGauge(QWidget):
    """Halbkreis-Anzeige fuer das Sprechtempo (Skala bis 150 WPM) — Design-System:
    Akzent-Bogen (Stroke 9) auf TRACK, grosse Kennzahl mittig im Bogen, Label darunter."""

    STROKE = 9

    def __init__(self):
        super().__init__()
        self.wpm = 0.0
        self.setFixedSize(110, 78)

    def set_wpm(self, wpm: float) -> None:
        self.wpm = wpm
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.STROKE
        d = self.width() - s  # Bogen-Durchmesser (RoundCap braucht s/2 Rand)
        rect = QRectF(s / 2, s / 2, d, d)
        p.setPen(QPen(QColor(TRACK), s, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 180 * 16, -180 * 16)
        share = max(0.0, min(1.0, self.wpm / 150.0))
        if share > 0:
            p.setPen(QPen(QColor(ACCENT), s, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, 180 * 16, int(-180 * 16 * share))
        # Kennzahl unten mittig im Bogen, Label darunter (wie die KPI-Karten).
        value_font = self.font()
        value_font.setPointSizeF(16.0)
        value_font.setWeight(QFont.DemiBold)
        p.setFont(value_font)
        p.setPen(QColor(TEXT))
        base = self.width() / 2 + s / 2  # Unterkante des Halbkreises
        p.drawText(QRectF(0, base - 30, self.width(), 24),
                   Qt.AlignHCenter | Qt.AlignBottom, str(round(self.wpm)))
        label_font = self.font()
        label_font.setPointSizeF(7.5)
        label_font.setWeight(QFont.Medium)
        p.setFont(label_font)
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(0, base - 4, self.width(), 16),
                   Qt.AlignHCenter | Qt.AlignTop, "Wörter / Minute")


class StreakCalendar(QWidget):
    """GitHub-artiger Aktivitaets-Kalender der letzten ~14 Wochen."""

    CELL, GAP = 10, 3  # Design-System: 10px-Kacheln, 3px Gap, Radius 3

    def __init__(self):
        super().__init__()
        self.daily: dict[str, int] = {}
        self.setMinimumHeight(7 * (self.CELL + self.GAP))

    def set_data(self, daily: dict[str, int]) -> None:
        self.daily = daily
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        today = _dt.date.today()
        start = today - _dt.timedelta(days=97)
        start -= _dt.timedelta(days=start.weekday())  # auf Montag ausrichten
        weeks = ((today - start).days // 7) + 1
        x_offset = max(0, self.width() - weeks * (self.CELL + self.GAP))
        day = start
        while day <= today:
            col = (day - start).days // 7
            row = day.weekday()
            count = self.daily.get(day.isoformat(), 0)
            shade = _STREAK_SHADES[min(3, count if count < 2 else (2 if count < 4 else 3))]
            p.setBrush(QColor(shade))
            p.drawRoundedRect(
                QRectF(x_offset + col * (self.CELL + self.GAP),
                       row * (self.CELL + self.GAP), self.CELL, self.CELL), 3, 3,
            )
            day += _dt.timedelta(days=1)


class TranscriptDetailDialog(QDialog):
    """Zeigt einen Verlaufseintrag vollstaendig (nicht abgeschnitten) und laesst den
    Text in die Zwischenablage kopieren — z. B. um ein Diktat nachzuholen, das im
    Zielfeld nicht angekommen ist (Fokus verloren, versehentlich weggeklickt)."""

    def __init__(self, entry: dict, parent=None, raw: str = ""):
        # Bewusst NICHT modal: der Dialog soll sich schliessen, sobald man daneben
        # klickt (siehe event()) — statt den Klick zu blocken (Windows-Fehlerton).
        super().__init__(parent)
        self.setWindowTitle("Transkript")
        self.resize(480, 440)
        self.setStyleSheet(f"QDialog {{ background: {BG}; }}")
        self._text = entry["cleaned"]
        self._was_activated = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(4)

        ts = _dt.datetime.fromtimestamp(entry["ts"])
        header = QLabel(f"TRANSKRIPT · {ts.strftime('%d.%m.%Y · %H:%M')}")
        header.setStyleSheet(
            f"color: {MUTED}; font-size: 9pt; font-weight: 600; letter-spacing: 0.5px;"
        )
        outer.addWidget(header)
        outer.addSpacing(6)

        def _section(caption: str) -> None:
            lab = QLabel(caption)
            lab.setStyleSheet(
                f"color: {MUTED}; font-size: 7.5pt; font-weight: 500;"
                f" letter-spacing: 1px;"
            )
            outer.addWidget(lab)

        _section("BEREINIGT")
        self._edit = QTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setPlainText(self._text)
        self._edit.setStyleSheet(
            f"QTextEdit {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE};"
            f"  border-radius: 8px; padding: 8px; font-size: 10pt; }}"
        )
        outer.addWidget(self._edit, 2)

        raw = (raw or "").strip()
        if raw and raw != self._text:
            outer.addSpacing(6)
            _section("ROH")
            raw_edit = QTextEdit()
            raw_edit.setReadOnly(True)
            raw_edit.setPlainText(raw)
            raw_edit.setStyleSheet(
                f"QTextEdit {{ background: {CARD}; color: {MUTED};"
                f"  border: 1px solid {BORDER_HAIRLINE};"
                f"  border-radius: 8px; padding: 8px; font-size: 9.5pt; }}"
            )
            outer.addWidget(raw_edit, 1)
        outer.addSpacing(8)

        buttons = QHBoxLayout()
        meta_parts = []
        app = (entry.get("app") or "").removesuffix(".exe")
        if app:
            meta_parts.append(app)
        meta_parts.append(f"{entry.get('words', len(self._text.split()))} Wörter")
        meta_parts.append("lokal verarbeitet")
        meta = QLabel(" · ".join(meta_parts))
        meta.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        buttons.addWidget(meta)
        buttons.addStretch(1)
        self._copy_btn = style_button(QPushButton("Kopieren"))
        self._copy_btn.clicked.connect(self._copy)
        close_btn = style_button(QPushButton("Schließen"), "ghost")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        buttons.addWidget(self._copy_btn)
        outer.addLayout(buttons)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._text)
        self._copy_btn.setText("Kopiert ✓")

    def event(self, e) -> bool:
        # Klick ausserhalb / Fensterwechsel → schliessen (nicht nur in den
        # Hintergrund fallen). Der Kopieren-Button klickt INNERHALB, deaktiviert
        # das Fenster also nicht. Der _was_activated-Guard verhindert, dass ein
        # verirrtes Deactivate direkt beim Oeffnen das Fenster sofort schliesst.
        if e.type() == QEvent.WindowActivate:
            self._was_activated = True
        elif e.type() == QEvent.WindowDeactivate and self._was_activated:
            self.close()
        return super().event(e)


class _ElidedLabel(QLabel):
    """Einzeiliges Label, das seinen Text an der aktuellen Breite mit „…" elidiert
    (QLabel schneidet sonst hart ab). Fuer die flachen Verlaufszeilen im Design."""

    def __init__(self, text: str = ""):
        super().__init__()
        self._full = text
        self.setMinimumWidth(40)

    def setFullText(self, text: str) -> None:
        self._full = text
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        from PySide6.QtGui import QFontMetrics

        fm = QFontMetrics(self.font())
        super().setText(fm.elidedText(self._full, Qt.ElideRight, max(20, self.width())))


class HistoryEntryRow(QFrame):
    """Flache Verlaufszeile (Design-System): Uhrzeit · einzeiliger Text · Loeschen.
    Transparent, hebt sich beim Hover an (ROW_HOVER); der Loeschen-Button erscheint
    erst beim Hover. Klick auf die Zeile oeffnet den vollen Text; der Loeschen-Button
    verschluckt seinen Klick (Qt liefert das Event dem Button, nicht dem Parent)."""

    clicked = Signal()

    def __init__(self, entry: dict, on_delete):
        super().__init__()
        self.setObjectName("entry")
        self.setStyleSheet(
            f"QFrame#entry {{ background: transparent; border-radius: 8px; }}"
            f"QFrame#entry:hover {{ background: {ROW_HOVER}; }}"
        )
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Klicken für den vollen Text")
        self.entry_id = entry["id"]

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(10)
        time_label = QLabel(_dt.datetime.fromtimestamp(entry["ts"]).strftime("%H:%M"))
        time_label.setStyleSheet(f"color: {MUTED}; font-size: 9pt; background: transparent;")
        time_label.setFixedWidth(44)
        text_label = _ElidedLabel()
        text_label.setStyleSheet(f"color: {TEXT}; font-size: 9.5pt; background: transparent;")
        text_label.setFullText(entry["cleaned"])

        self._del_btn = del_btn = QPushButton()
        del_btn.setIcon(_x_icon(MUTED))
        del_btn.setIconSize(QSize(14, 14))
        del_btn.setFixedSize(24, 24)
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.setToolTip("Eintrag löschen")
        del_btn.setFocusPolicy(Qt.NoFocus)
        del_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: {TRACK}; }}"
        )
        del_btn.clicked.connect(lambda: on_delete(self.entry_id))
        # Erst beim Hover sichtbar — Platz bleibt reserviert (keine Layout-Spruenge).
        sp = del_btn.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        del_btn.setSizePolicy(sp)
        del_btn.hide()
        row.addWidget(time_label)
        row.addWidget(text_label, 1)
        row.addWidget(del_btn)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._del_btn.show()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._del_btn.hide()

    def mouseReleaseEvent(self, event) -> None:
        # Wie ein Button: nur ausloesen, wenn der Klick auch AUF der Karte endet
        # (Press-und-wieder-rausgezogen soll den Dialog nicht oeffnen).
        if event.button() == Qt.LeftButton and \
                self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class HomePage(QWidget):
    def __init__(self, settings: UserSettings, store: HistoryStore, on_change=None):
        super().__init__()
        self.settings = settings
        self.store = store
        self._on_change = on_change  # nach Einzel-Loeschung: Insights mitziehen

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        self._welcome = QLabel("")
        self._welcome.setStyleSheet(f"color: {TEXT}; font-size: 12pt; font-weight: 600;")
        outer.addWidget(self._welcome)
        outer.addSpacing(8)

        body = QHBoxLayout()
        body.setSpacing(12)
        outer.addLayout(body, 1)

        # Verlauf (links)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self._timeline_holder = QWidget()
        self._timeline = QVBoxLayout(self._timeline_holder)
        self._timeline.setContentsMargins(0, 8, 8, 8)
        self._timeline.addStretch(1)
        self._scroll.setWidget(self._timeline_holder)
        body.addWidget(self._scroll, 1)

        # Kurz-Stats (rechts) — Design-System: grosse Kennzahl + kleines Label,
        # der erste Wert (Woerter gesamt) traegt den Akzent.
        self._stats_frame, stats_box = _card("Kurz-Stats")
        self._stats_frame.setFixedWidth(190)
        stats_box.setSpacing(12)

        def _stat(color: str, caption: str) -> QLabel:
            value = QLabel("")
            value.setStyleSheet(
                f"color: {color}; font-size: 21pt; font-weight: 600; border: none;"
            )
            label = QLabel(caption)
            label.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; border: none;")
            holder = QVBoxLayout()
            holder.setSpacing(3)
            holder.addWidget(value)
            holder.addWidget(label)
            stats_box.addLayout(holder)
            return value

        self._stat_words = _stat(ACCENT, "Wörter gesamt")
        self._stat_wpm = _stat(TEXT, "WPM")
        self._stat_streak = _stat(TEXT, "Tage-Serie")
        stats_box.addStretch(1)
        side = QVBoxLayout()
        side.addWidget(self._stats_frame)
        side.addStretch(1)
        body.addLayout(side)

    def apply_interface(self, ui) -> None:
        """Bausteine gemaess InterfaceSettings ein-/ausblenden."""
        self._welcome.setVisible(ui.home_show_welcome)
        self._stats_frame.setVisible(ui.home_show_stats)

    def enable_hiding(self, settings, on_changed) -> None:
        enable_card_hiding(self._stats_frame, "Statistik", "home_show_stats",
                           settings, on_changed)

    def _display_name(self) -> str:
        name = self.settings.general.display_name.strip()
        if not name:
            try:
                name = getpass.getuser().capitalize()
            except Exception:
                name = ""
        return name

    def refresh(self) -> None:
        name = self._display_name()
        self._welcome.setText(f"Willkommen zurück{', ' + name if name else ''}")

        stats = self.store.stats()
        self._stat_words.setText(f"{stats.total_words:n}")
        self._stat_wpm.setText(f"{round(stats.wpm)}")
        self._stat_streak.setText(f"{stats.streak}")

        # Timeline neu aufbauen (gruppiert nach Tag)
        while self._timeline.count() > 1:
            item = self._timeline.takeAt(0)
            w = item.widget()
            if w:
                # sofort verstecken: takeAt entfernt nur aus dem Layout, gemalt
                # wird das Widget sonst bis zum naechsten Event-Loop-Durchlauf
                w.hide()
                w.deleteLater()
        entries = self.store.recent(limit=40)
        if not entries:
            empty = QLabel("Noch keine Diktate — halte den Hotkey und sprich los.")
            empty.setStyleSheet(f"color: {MUTED}; font-size: 10pt;")
            self._timeline.insertWidget(0, empty)
            return
        today = _dt.date.today()
        group = None
        insert_at = 0
        for entry in entries:
            day = _dt.datetime.fromtimestamp(entry["ts"]).date()
            if day != group:
                group = day
                title = ("HEUTE" if day == today else
                         "GESTERN" if day == today - _dt.timedelta(days=1)
                         else day.strftime("%d.%m.%Y"))
                header = QLabel(title)
                header.setStyleSheet(
                    f"color: {MUTED}; font-size: 7.5pt; font-weight: 600;"
                    f" letter-spacing: 1px; margin-top: 10px; padding-left: 8px;"
                )
                self._timeline.insertWidget(insert_at, header)
                insert_at += 1
            self._timeline.insertWidget(insert_at, self._entry_row(entry))
            insert_at += 1

    def _entry_row(self, entry: dict) -> QFrame:
        row = HistoryEntryRow(entry, self._delete_entry)
        row.clicked.connect(lambda: self._open_entry(entry))
        return row

    def _open_entry(self, entry: dict) -> None:
        # Nicht-modal (.show statt .exec) — schliesst bei Klick daneben. Referenz
        # halten, sonst raeumt der GC den Dialog sofort wieder ab.
        self._detail_dialog = TranscriptDetailDialog(
            entry, self, raw=self.store.raw_text(entry["id"])
        )
        self._detail_dialog.show()
        self._detail_dialog.raise_()
        self._detail_dialog.activateWindow()

    def _delete_entry(self, entry_id: int) -> None:
        self.store.delete(entry_id)
        self.refresh()
        if self._on_change:
            self._on_change()  # Insights aktualisieren


class WordDetailDialog(QDialog):
    """Vollstaendigere Rangliste der haeufigsten Woerter (Klick auf "Alle anzeigen"
    in der Insights-Karte) — auch die Woerter, die auf den ersten 5 keinen Platz
    mehr fanden."""

    def __init__(self, store: HistoryStore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Häufigste Wörter")
        self.resize(420, 520)
        self.setStyleSheet(f"QDialog {{ background: {BG}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        title = QLabel("ALLE WÖRTER")
        title.setStyleSheet(
            f"color: {MUTED}; font-size: 9pt; font-weight: 600; letter-spacing: 0.5px;"
        )
        outer.addWidget(title)
        hint = QLabel("Gesamter Verlauf, ohne Füllwörter wie „der“, „die“, „das“.")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        outer.addWidget(hint)
        outer.addSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 8, 0)
        box.setSpacing(4)

        words = store.top_words(limit=50)
        if not words:
            empty = QLabel("Noch keine Daten.")
            empty.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
            box.addWidget(empty)
        else:
            for word, count, share in words:
                box.addWidget(_ranked_row(word, share, f"{count}×"))
        box.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(scroll, 1)

        close_btn = style_button(QPushButton("Schließen"))
        close_btn.clicked.connect(self.accept)
        outer.addWidget(close_btn, 0, Qt.AlignRight)


class InsightsPage(QWidget):
    def __init__(self, store: HistoryStore, on_add_rule=None, settings=None,
                 on_ignored=None):
        """on_add_rule: Callable(falsch, richtig) — uebernimmt einen erkannten
        Korrektur-Fehler als Woerterbuch-Regel (Ein-Klick aus der Vorschlags-Karte).
        settings: UserSettings — fuer bereits vorhandene Regeln und die Ignorier-
        Liste (None = alle Vorschlaege zeigen, z. B. in Tests).
        on_ignored: Callable() — nach einem „Ignorieren"-Klick, damit der Editor
        der Ignorier-Liste in den Einstellungen nachzieht."""
        self._on_add_rule = on_add_rule
        self._settings = settings
        self._on_ignored = on_ignored
        self._init_page(store)

    def _init_page(self, store: HistoryStore):
        super().__init__()
        self.store = store

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)  # Karten-Grid-Gap des Design-Systems
        # Kopfzeile: Titel links, Zeitraum rechts. Der Zeitraum ist der Grund, warum
        # die Seite ueberhaupt lebendig wirkt — ohne ihn rechnet jede Zahl ueber die
        # gesamte Historie, und nach ein paar hundert Diktaten bewegt sich nichts mehr.
        head = QHBoxLayout()
        title = QLabel("Insights")
        title.setStyleSheet(f"color: {TEXT}; font-size: 12pt; font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        self._range_buttons: dict[str, QPushButton] = {}
        for key, label in INSIGHT_RANGES:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("range_key", key)   # KEIN Lambda mit self — Referenzzyklus
            btn.clicked.connect(self._on_range_clicked)
            self._range_buttons[key] = btn
            head.addWidget(btn)
        outer.addLayout(head)
        self._range = self._stored_range()
        self._apply_range_styles()

        # Reihe 1 — drei KPI-Karten (Titel im Header, grosse Kennzahl darunter).
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        outer.addLayout(row1)

        self._wpm_frame, wpm_box = _card("WPM")
        gauge_row = QHBoxLayout()
        self._gauge = WpmGauge()
        gauge_row.addStretch(1)
        gauge_row.addWidget(self._gauge)
        gauge_row.addStretch(1)  # Gauge mittig in der Karte (Design)
        wpm_box.addLayout(gauge_row)
        # Echte Sprechzeit aus `audio_seconds` der Historie — NICHT aus Woertern
        # geteilt durch WPM gerechnet. Das waere ein Zirkelschluss (WPM stammt aus
        # denselben zwei Zahlen) und haette Pausen, Verwerfungen und abgebrochene
        # Aufnahmen unterschlagen.
        self._time_label = QLabel("")
        self._time_label.setWordWrap(True)
        self._time_label.setAlignment(Qt.AlignCenter)
        self._time_label.setStyleSheet(
            f"color: {MUTED}; font-size: 8.5pt; border: none;")
        wpm_box.addWidget(self._time_label)
        wpm_box.addStretch(1)

        self._fix_frame, fix_box, self._fix_value = _metric("Korrekturen von Fleech")
        self._fix_detail = QLabel("")
        self._fix_detail.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; border: none;")
        fix_box.addWidget(self._fix_detail)
        fix_box.addStretch(1)

        self._words_frame, words_box, self._words_value = _metric("Wörter diktiert")
        # Hier stand bisher der Lokal-Anteil („Desktop · 100 % lokal"). Seit v3.6.0
        # gibt es ueberhaupt keinen Cloud-Pfad mehr — die Zeile konnte gar nichts
        # anderes mehr sagen und war damit tote Flaeche. Jetzt steht dort ein
        # Groessenvergleich mit einem bekannten Buch: „74.245" sagt niemandem etwas,
        # „etwa das 1,2-Fache von Momo" schon.
        self._local_label = QLabel("")
        self._local_label.setWordWrap(True)
        self._local_label.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; border: none;")
        words_box.addWidget(self._local_label)
        words_box.addStretch(1)

        row1.addWidget(self._wpm_frame, 1)
        row1.addWidget(self._fix_frame, 1)
        row1.addWidget(self._words_frame, 1)

        # Reihe 2 — App-Nutzung und Serie, gleich breit (Design).
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        outer.addLayout(row2)
        self._usage_frame, self._usage_box = _card("App-Nutzung")
        # Befehle — welche Art Anweisung nutzt du wirklich? Gleiche Rangliste wie
        # die App-Nutzung; Karte bleibt weg, solange es keine Befehle gab.
        self._commands_frame, self._commands_box = _card("Befehle")
        self._commands_rows: list[QWidget] = []
        self._streak_frame, streak_box = _card("Serie")
        self._calendar = StreakCalendar()
        streak_box.addWidget(self._calendar)
        self._streak_label = QLabel("")
        self._streak_label.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; border: none;")
        streak_box.addWidget(self._streak_label)
        row2.addWidget(self._usage_frame, 1)
        row2.addWidget(self._commands_frame, 1)
        row2.addWidget(self._streak_frame, 1)

        # Reihe 3 — Haeufigste Woerter · Deine Muster · Verarbeitung, je ein Drittel.
        row3 = QHBoxLayout()
        row3.setSpacing(12)
        outer.addLayout(row3)

        # Haeufigste Woerter — Rangliste wie App-Nutzung, Fuellwoerter ausgeblendet
        # (STOPWORDS_DE); die erste Zeile ist damit implizit das "Lieblingswort".
        # "Alle anzeigen" oeffnet die vollstaendige Liste (nicht nur die Top 5).
        show_all_words = _link_button("Alle anzeigen")
        show_all_words.clicked.connect(self._open_word_detail)
        self._words_freq_frame, self._words_freq_box = _card(
            "Häufigste Wörter", header_action=show_all_words
        )
        row3.addWidget(self._words_freq_frame, 1)

        # Deine Muster — kurze Einordnung aus Tageszeit/Wochentag der Diktate.
        self._pattern_frame, pattern_box = _card("Deine Muster")
        self._pattern_label = QLabel("")
        self._pattern_label.setWordWrap(True)
        self._pattern_label.setStyleSheet(f"color: {TEXT}; font-size: 9pt; border: none;")
        pattern_box.addWidget(self._pattern_label)
        pattern_box.addStretch(1)
        row3.addWidget(self._pattern_frame, 1)

        # Verarbeitung — lokale Latenz-Telemetrie + Routing-/Fallback-Bild.
        # Vorschlags-Karte: aus Zahlen wird eine Handlung. Wird nur eingeblendet,
        # wenn es tatsaechlich etwas vorzuschlagen gibt (sonst leerer Platz).
        self._advice_frame, self._advice_box = _card("Vorschläge")
        self._advice_rows: list[QWidget] = []
        outer.addWidget(self._advice_frame)

        self._processing_frame, processing_box = _card("Verarbeitung")
        self._processing_label = QLabel("")
        self._processing_label.setWordWrap(True)
        self._processing_label.setStyleSheet(f"color: {TEXT}; font-size: 9pt; border: none;")
        processing_box.addWidget(self._processing_label)
        processing_box.addStretch(1)
        row3.addWidget(self._processing_frame, 1)

        outer.addStretch(1)
        self._usage_rows: list[QWidget] = []
        self._words_freq_rows: list[QWidget] = []
        self._advice_allowed = True
        self._commands_allowed = True

    # -- Vorschlaege ------------------------------------------------------------------

    def _advice_text(self, text: str) -> QWidget:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {TEXT}; font-size: 9pt; border: none;")
        self._advice_box.addWidget(label)
        return label

    def _correction_row(self, wrong: str, right: str, count: int) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(10)
        label = QLabel(f"„{wrong}“ wurde {count}× zu „{right}“ korrigiert")
        label.setStyleSheet(f"color: {TEXT}; font-size: 9pt; border: none;")
        button = style_button(QPushButton("Als Regel übernehmen"))
        # Daten am Button statt in einem Lambda: ein Lambda, das `self` faengt und in
        # einem Kind-Widget haengt, erzeugt einen Referenzzyklus (real: sporadische
        # Access Violations). Eine gebundene Methode + sender()-Property ist sicher.
        button.setProperty("rule_wrong", wrong)
        button.setProperty("rule_right", right)
        button.clicked.connect(self._on_take_rule)
        ignore = style_button(QPushButton("Ignorieren"))
        ignore.setToolTip(
            "Schlägt dieses Paar nicht mehr vor. Die Liste der ignorierten Paare "
            "steht unter Einstellungen → Wörterbuch — dort löschen holt den "
            "Vorschlag zurück."
        )
        ignore.setProperty("rule_wrong", wrong)
        ignore.setProperty("rule_right", right)
        ignore.clicked.connect(self._on_ignore_rule)
        h.addWidget(label, 1)
        h.addWidget(button)
        h.addWidget(ignore)
        self._advice_box.addWidget(row)
        return row

    @staticmethod
    def _advice_key(wrong: str, right: str) -> str:
        return f"{wrong} => {right}".lower()

    def _on_take_rule(self) -> None:
        button = self.sender()
        if button is None or self._on_add_rule is None:
            return
        wrong = button.property("rule_wrong")
        right = button.property("rule_right")
        if not wrong or not right:
            return
        self._on_add_rule(str(wrong), str(right))
        # Kein zusaetzlicher Merkposten noetig: `_refresh_advice` blendet Paare aus,
        # fuer die bereits eine Woerterbuch-Regel existiert. Loescht man die Regel
        # spaeter wieder, taucht der Vorschlag zu Recht erneut auf.
        self._refresh_advice()

    def _on_ignore_rule(self) -> None:
        """„Ignorieren": Paar dauerhaft in die sichtbare Ignorier-Liste.

        Dieselbe Liste, die auch abgelehnte Woerterbuch-Rueckfragen traegt — sie
        steht als Editor unter Einstellungen → Woerterbuch. Dauerhaft ist hier
        vertretbar, WEIL sie sichtbar ist: Ein Fehlklick laesst sich dort per
        Zeile-loeschen zuruecknehmen."""
        button = self.sender()
        settings = self._settings
        if button is None or settings is None:
            return
        wrong = button.property("rule_wrong")
        right = button.property("rule_right")
        if not wrong or not right:
            return
        key = self._advice_key(str(wrong), str(right))
        ignores = settings.output.dictionary_ignores
        if not any(str(i).strip().lower() == key for i in ignores):
            ignores.append(key)
            settings.save()
        if self._on_ignored is not None:
            self._on_ignored()
        self._refresh_advice()

    def _advice_suppressed(self, wrong: str, right: str) -> bool:
        """Vorschlag ausblenden — weil die Regel schon existiert oder das Paar auf
        der Ignorier-Liste steht."""
        settings = self._settings
        if settings is None:
            return False
        line = f"{wrong} => {right}".strip().lower()
        for existing in settings.output.dictionary or []:
            if str(existing).strip().lower() == line:
                return True
        key = self._advice_key(wrong, right)
        return any(str(i).strip().lower() == key
                   for i in settings.output.dictionary_ignores or [])

    def _update_advice_visibility(self) -> None:
        self._advice_frame.setVisible(self._advice_allowed and bool(self._advice_rows))

    def _refresh_advice(self) -> None:
        """Beobachtungen, aus denen eine Handlung folgt. Nichts zu sagen → Karte weg."""
        for row in self._advice_rows:
            self._advice_box.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._advice_rows = []

        try:
            # Mehr holen als angezeigt wird: Sonst bliebe die Karte leer, sobald die
            # drei staerksten Paare uebernommen oder weggeklickt sind — obwohl es
            # dahinter weitere echte Funde gibt.
            corrections = self.store.top_corrections(limit=_ADVICE_SCAN)
        except Exception:
            corrections = []
        shown = 0
        for wrong, right, count in corrections:
            if shown >= _ADVICE_SHOWN:
                break
            if self._advice_suppressed(wrong, right):
                continue
            shown += 1
            if self._on_add_rule is None:
                self._advice_rows.append(self._advice_text(
                    f"„{wrong}“ wurde {count}× zu „{right}“ korrigiert."))
            else:
                self._advice_rows.append(self._correction_row(wrong, right, count))

        try:
            recent, previous, seen = self.store.fallback_trend()
        except Exception:
            recent, previous, seen = 0.0, 0.0, 0
        # Nur melden, wenn es genug Diktate gab UND der Anstieg deutlich ist —
        # sonst ist jede Schwankung ein Fehlalarm.
        if seen >= 5 and recent >= 0.25 and recent > previous * 1.5:
            self._advice_rows.append(self._advice_text(
                f"Die Fallback-Quote liegt zuletzt bei {round(recent * 100)} % (davor "
                f"{round(previous * 100)} %) — läuft Ollama noch, und stimmt das "
                f"Modell in der Konfiguration?"
            ))
        self._update_advice_visibility()

    def apply_interface(self, ui) -> None:
        """Bausteine gemaess InterfaceSettings ein-/ausblenden."""
        self._wpm_frame.setVisible(ui.insights_show_wpm)
        self._fix_frame.setVisible(ui.insights_show_corrections)
        self._words_frame.setVisible(ui.insights_show_words)
        self._usage_frame.setVisible(ui.insights_show_app_usage)
        self._streak_frame.setVisible(ui.insights_show_streak)
        self._words_freq_frame.setVisible(ui.insights_show_top_words)
        self._pattern_frame.setVisible(ui.insights_show_patterns)
        self._processing_frame.setVisible(ui.insights_show_processing)
        self._advice_allowed = getattr(ui, "insights_show_advice", True)
        self._update_advice_visibility()
        # Die Befehls-Karte kennt zwei Gruende, weg zu sein: abgeschaltet ODER es
        # gab noch keine Befehle. Der Sichtbarkeits-Stand aus refresh() darf hier
        # nicht ueberschrieben werden — deshalb nur die Erlaubnis merken und die
        # tatsaechliche Sichtbarkeit dem naechsten refresh() ueberlassen.
        self._commands_allowed = getattr(ui, "insights_show_commands", True)
        if not self._commands_allowed:
            self._commands_frame.setVisible(False)

    def enable_hiding(self, settings, on_changed) -> None:
        """Jede Karte per Rechtsklick ausblendbar machen (statt Checkbox-Liste)."""
        for frame, title, attr in (
            (self._wpm_frame, "Wörter/Minute", "insights_show_wpm"),
            (self._fix_frame, "Korrekturen", "insights_show_corrections"),
            (self._words_frame, "Wörter diktiert", "insights_show_words"),
            (self._usage_frame, "App-Nutzung", "insights_show_app_usage"),
            (self._commands_frame, "Befehle", "insights_show_commands"),
            (self._streak_frame, "Serie", "insights_show_streak"),
            (self._words_freq_frame, "Häufigste Wörter", "insights_show_top_words"),
            (self._pattern_frame, "Deine Muster", "insights_show_patterns"),
            (self._processing_frame, "Verarbeitung", "insights_show_processing"),
            (self._advice_frame, "Vorschläge", "insights_show_advice"),
        ):
            enable_card_hiding(frame, title, attr, settings, on_changed)

    def _open_word_detail(self) -> None:
        WordDetailDialog(self.store, self).exec()

    def _stored_range(self) -> str:
        gemerkt = getattr(getattr(self._settings, "interface", None),
                          "insights_range", "all")
        return gemerkt if gemerkt in _RANGE_DAYS else "all"

    def _on_range_clicked(self) -> None:
        """Zeitraum umgeschaltet. Der Schluessel haengt am Button (setProperty),
        NICHT in einem Lambda — ein Lambda mit `self` in einem Kind-Widget baut
        einen Referenzzyklus, an dem Qt schon einmal sporadisch abgestuerzt ist."""
        sender = self.sender()
        key = sender.property("range_key") if sender is not None else None
        if key not in _RANGE_DAYS:
            return
        self._range = key
        if self._settings is not None:
            try:
                self._settings.interface.insights_range = key
                self._settings.save()
            except Exception:
                log.debug("Zeitraum konnte nicht gespeichert werden.", exc_info=True)
        self._apply_range_styles()
        self.refresh()

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

    def _range_since(self) -> float | None:
        tage = _RANGE_DAYS.get(self._range)
        return None if not tage else _time.time() - tage * 86400

    def refresh(self) -> None:
        stats = self.store.stats(since=self._range_since())
        self._gauge.set_wpm(stats.wpm)  # Kennzahl steht IM Gauge (Design)
        self._time_label.setText(_diktierzeit_text(stats))
        self._fix_value.setText(f"{stats.corrected_words:n}")
        per_dictation = (stats.corrected_words / stats.total_dictations
                         if stats.total_dictations else 0.0)
        self._fix_detail.setText(
            f"Wörter korrigiert oder entfernt\n"
            f"aus {stats.total_dictations:n} Diktaten · Ø {per_dictation:.1f} je Diktat"
        )
        self._words_value.setText(f"{stats.total_words:n}")
        self._streak_label.setText(
            f"Aktuell {stats.streak} Tage · längste Serie {stats.longest_streak} Tage"
        )
        self._calendar.set_data(stats.daily_counts or {})

        usage_entries = [
            (app.removesuffix(".exe"), share, f"{round(share * 100)} %")
            for app, _words, share in (stats.app_usage or [])[:5]
        ]
        self._usage_rows = _rebuild_ranked_list(
            self._usage_box, self._usage_rows, usage_entries, "Noch keine Daten."
        )

        try:
            kinds = self.store.command_kinds()
        except Exception:
            kinds = []
        kind_total = sum(count for _name, count in kinds)
        command_entries = [
            (name, (count / kind_total) if kind_total else 0.0, f"{count}×")
            for name, count in kinds
        ]
        self._commands_rows = _rebuild_ranked_list(
            self._commands_box, self._commands_rows, command_entries,
            "Noch keine Befehle genutzt."
        )
        self._commands_frame.setVisible(self._commands_allowed and bool(kinds))

        # Groessenvergleich statt nackter Zahl. Bewusst NICHT bei jedem Neuzeichnen
        # neu gewuerfelt, sondern einmal je Aufbau der Seite — sonst wechselte der
        # Titel bei jedem Repaint und die Karte flackerte.
        self._local_label.setText(word_milestone(int(stats.total_words or 0)))

        word_entries = [
            (word, share, f"{count}×")
            for word, count, share in (stats.top_words or [])[:5]
        ]
        self._words_freq_rows = _rebuild_ranked_list(
            self._words_freq_box, self._words_freq_rows, word_entries, "Noch keine Daten."
        )

        if stats.productive_daypart and stats.productive_weekday:
            self._pattern_label.setText(
                f"Du diktierst am meisten {_DAYPART_LABELS.get(stats.productive_daypart, stats.productive_daypart)}. "
                f"Dein aktivster Wochentag ist {stats.productive_weekday}."
            )
        else:
            self._pattern_label.setText(
                "Noch nicht genug Diktate für eine Auswertung — nach ein paar Tagen "
                "zeigen wir dir hier, wann du am produktivsten bist."
            )

        self._processing_label.setText(
            _processing_summary(stats) + _latency_trend_line(self.store)
        )
        self._refresh_advice()


class DictionarySuggestionDialog(QDialog):
    """Rueckfrage bei wahrscheinlicher Fehlschreibung: „Meintest du ‚X‘?" — mit
    markiertem Satz. Bestaetigen legt automatisch eine Woerterbuch-Regel an
    (selbstlernend); Ablehnen merkt sich das Paar und fragt nie wieder.
    Nicht-modal, schliesst bei Klick daneben."""

    def __init__(self, recognized: str, meant: str, sentence: str,
                 on_learn, on_ignore, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wörterbuch")
        self.resize(440, 240)
        self.setStyleSheet(f"QDialog {{ background: {BG}; }}")
        self._on_learn = on_learn
        self._on_ignore = on_ignore
        self._recognized, self._meant = recognized, meant
        self._was_activated = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        title = QLabel(f"Meintest du „{meant}“?")
        title.setStyleSheet(f"color: {TEXT}; font-size: 12.5pt; font-weight: 600;")
        outer.addWidget(title)
        sub = QLabel(f"Erkannt wurde „{recognized}“ — das liegt nah an deinem "
                     f"Wörterbuch-Begriff „{meant}“.")
        sub.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        sub.setWordWrap(True)
        outer.addWidget(sub)
        outer.addSpacing(6)

        sentence_label = QLabel()
        sentence_label.setTextFormat(Qt.RichText)
        highlighted = sentence.replace(
            recognized, f'<span style="color:{ACCENT}; font-weight:600;">{recognized}</span>'
        )
        sentence_label.setText(f"„{highlighted}“")
        sentence_label.setWordWrap(True)
        sentence_label.setStyleSheet(
            f"color: {TEXT}; font-size: 10pt; background: {CARD};"
            f" border-radius: 8px; padding: 10px;"
        )
        outer.addWidget(sentence_label, 1)

        buttons = QHBoxLayout()
        learn_btn = style_button(QPushButton(f"Ja — künftig „{meant}“ schreiben"), "primary")
        learn_btn.clicked.connect(self._learn)
        ignore_btn = style_button(QPushButton("Nein, war richtig"), "ghost")
        ignore_btn.clicked.connect(self._ignore)
        buttons.addWidget(learn_btn)
        buttons.addStretch(1)
        buttons.addWidget(ignore_btn)
        outer.addLayout(buttons)

    def _learn(self) -> None:
        self._on_learn(self._recognized, self._meant)
        self.close()

    def _ignore(self) -> None:
        self._on_ignore(self._recognized, self._meant)
        self.close()

    def event(self, e) -> bool:
        if e.type() == QEvent.WindowActivate:
            self._was_activated = True
        elif e.type() == QEvent.WindowDeactivate and self._was_activated:
            self.close()  # Klick daneben = spaeter entscheiden (fragt beim
            # naechsten Vorkommen erneut — nichts wird gelernt/ignoriert)
        return super().event(e)


class AppsPage(QWidget):
    """Zuordnung App → Profil, von der APP aus gedacht.

    Auf der Profilseite stand dieselbe Beziehung andersherum („welche Apps gehoeren
    zu diesem Profil?") — und damit an der falschen Stelle: Ein Profil beantwortet
    seit den Ausgabeformaten die Frage „was wird aus dem Diktat", nicht „wo".
    Gefragt wird im Alltag aber „was soll Fleech in DIESEM Programm tun?" — genau
    das ist diese Seite.

    Die Daten bleiben unveraendert: zugewiesen wird weiterhin in `profil["apps"]`,
    nur die Blickrichtung dreht sich. Keine Migration.
    """

    KEIN_PROFIL = "— kein Profil (Standard)"

    def __init__(self, settings: UserSettings, store: HistoryStore, on_changed=None):
        super().__init__()
        self.settings = settings
        self.store = store
        self._on_changed = on_changed or (lambda section: None)
        self._loading = False

        from PySide6.QtWidgets import QComboBox, QLineEdit

        from .chevron import apply_chevrons

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(12)
        titel = QLabel("Apps")
        titel.setStyleSheet(f"color: {TEXT}; font-size: 17pt; font-weight: 600;")
        layout.addWidget(titel)
        unter = QLabel("Anwendung links wählen. In der Mitte, welches Profil "
                       "Fleech dort automatisch nimmt — rechts, zwischen welchen "
                       "der Profil-Hotkey dort wechselt. Ohne Zuordnung gilt das "
                       "Standardprofil oder das, was du von Hand gewählt hast.")
        unter.setWordWrap(True)
        unter.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        layout.addWidget(unter)

        body = QHBoxLayout()
        body.setSpacing(14)
        layout.addLayout(body, 1)

        list_style = (
            f"QListWidget {{ background: transparent; border: none; outline: none;"
            f"  color: {TEXT}; font-size: 9.5pt; }}"
            f"QListWidget::item {{ padding: 7px 10px; border-radius: 8px; }}"
            f"QListWidget::item:hover {{ background: {ROW_HOVER}; }}"
            f"QListWidget::item:selected {{ background: {NAV_ACTIVE_BG}; color: {ACCENT}; }}"
        )
        links, links_box = _card("Anwendungen")
        self._app_suche = _suchfeld("Anwendung suchen …")
        self._app_suche.textChanged.connect(lambda _t: self._filter_apps())
        links_box.addWidget(self._app_suche)
        self._apps = QListWidget()
        self._apps.setStyleSheet(list_style)
        _no_hscroll(self._apps)
        self._apps.currentRowChanged.connect(lambda _r: self._refresh_detail())
        links_box.addWidget(self._apps, 1)
        body.addWidget(links, 5)

        rechts, rechts_box = _card("Zuordnung")
        self._app_titel = QLabel("")
        self._app_titel.setStyleSheet(
            f"color: {TEXT}; font-size: 11pt; font-weight: 600;")
        rechts_box.addWidget(self._app_titel)

        hinweis = QLabel("Profil für diese Anwendung")
        hinweis.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        rechts_box.addWidget(hinweis)
        self._profil_combo = QComboBox()
        self._profil_combo.setStyleSheet(apply_chevrons(
            f"QComboBox {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
            f"  padding: 6px 10px; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox::down-arrow {{ width: 11px; height: 11px;"
            f"  margin-right: 6px; image: url(__CHEV_DOWN__); }}"
            f"QComboBox QAbstractItemView {{ background: {SIDEBAR}; color: {TEXT};"
            f"  border: 1px solid {TRACK}; outline: none; padding: 4px;"
            f"  selection-background-color: {NAV_ACTIVE_BG};"
            f"  selection-color: {ACCENT}; }}"))
        self._profil_combo.currentIndexChanged.connect(self._on_profil_gewaehlt)
        rechts_box.addWidget(self._profil_combo)

        # Eigene, DRITTE Spalte: acht Profile in die Zuordnungs-Karte gequetscht
        # zeigten drei Zeilen mit Scrollbalken — man sah nicht einmal, welche
        # angehakt sind. Und es ist ohnehin eine andere Frage: „welches Profil gilt
        # hier" (Mitte) gegen „zwischen welchen kann ich hier wechseln" (rechts).
        dritte, dritte_box = _card("Schnellwechsel")
        self._app_titel2 = QLabel("")
        self._app_titel2.setStyleSheet(
            f"color: {TEXT}; font-size: 11pt; font-weight: 600;")
        dritte_box.addWidget(self._app_titel2)
        schnell_hinweis = QLabel(
            "Was der Profil-Hotkey in dieser Anwendung durchtippt — und beim "
            "Halten zur Auswahl stellt. Alles angehakt = keine Einschränkung.")
        schnell_hinweis.setWordWrap(True)
        schnell_hinweis.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        dritte_box.addWidget(schnell_hinweis)
        self._schnell = QListWidget()
        # Ankreuz-Kaestchen im Design-System (15px, Radius 4, Akzent-Fuellung mit
        # generiertem Haken) — der Windows-Standardindikator sass hier als einziges
        # helles Element in einer dunklen Karte.
        self._schnell.setStyleSheet(apply_chevrons(
            list_style
            + f"QListWidget::indicator {{ width: 15px; height: 15px;"
              f"  border-radius: 4px; border: 1.5px solid {TRACK};"
              f"  background: transparent; margin-right: 4px; }}"
              f"QListWidget::indicator:hover {{ border-color: {MUTED}; }}"
              f"QListWidget::indicator:checked {{ background: {ACCENT};"
              f"  border-color: {ACCENT}; image: url(__CHEV_CHECK__); }}"))
        _no_hscroll(self._schnell)
        self._schnell.itemChanged.connect(self._schnell_geaendert)
        dritte_box.addWidget(self._schnell, 1)

        rechts_box.addSpacing(8)
        regel_hinweis = QLabel(
            "Ausnahmen nach Fenstertitel — derselbe Prozess trägt oft sehr "
            "verschiedene Kontexte (ein Editor mit Code, einer mit Notizen). "
            "Eine Ausnahme gewinnt gegen das Profil oben. Doppelklick entfernt sie.")
        regel_hinweis.setWordWrap(True)
        regel_hinweis.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt;")
        rechts_box.addWidget(regel_hinweis)
        self._regeln = QListWidget()
        self._regeln.setStyleSheet(list_style)
        _no_hscroll(self._regeln)
        self._regeln.setMinimumHeight(60)
        self._regeln.itemDoubleClicked.connect(self._regel_entfernen)
        rechts_box.addWidget(self._regeln, 1)

        neu_row = QHBoxLayout()
        neu_row.setSpacing(6)
        self._regel_titel = QLineEdit()
        self._regel_titel.setPlaceholderText("Titel …")
        self._regel_titel.setStyleSheet(
            f"QLineEdit {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
            f"  padding: 6px 10px; font-size: 9.5pt; }}"
            f"QLineEdit:focus {{ border-color: {ACCENT}; }}")
        self._regel_titel.returnPressed.connect(self._regel_hinzufuegen)
        neu_row.addWidget(self._regel_titel, 3)
        self._regel_profil = QComboBox()
        self._regel_profil.setStyleSheet(self._profil_combo.styleSheet())
        neu_row.addWidget(self._regel_profil, 2)
        plus = style_button(QPushButton("Hinzufügen"), "ghost")
        plus.clicked.connect(self._regel_hinzufuegen)
        neu_row.addWidget(plus)
        rechts_box.addLayout(neu_row)
        body.addWidget(rechts, 5)
        body.addWidget(dritte, 4)

    # -- Daten ---------------------------------------------------------------------

    def _items(self) -> list:
        return [i for i in (self.settings.profiles.items or []) if isinstance(i, dict)]

    def _aktuelle_app(self) -> str:
        item = self._apps.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else ""

    def refresh(self) -> None:
        from ..usersettings import parse_app_rule
        from .windowsfocus import list_visible_window_processes

        vorher = self._aktuelle_app()
        self._loading = True
        self._apps.clear()
        gesehen: set = set()
        self._erhoben: list = []      # [(app, zusatz)] — Quelle fuer die Anzeige
        try:
            laufend = list_visible_window_processes()
        except Exception:
            log.debug("Fensterliste nicht abrufbar.", exc_info=True)
            laufend = []
        for app in laufend:
            gesehen.add(app.lower())
            self._eintrag(app, "läuft")
        try:
            haeufig = self.store.stats().app_usage or []
        except Exception:
            haeufig = []
        for app, words, _share in haeufig:
            if app.lower() not in gesehen:
                gesehen.add(app.lower())
                self._eintrag(app, f"{words} Wörter diktiert")
        # Zugewiesene Apps, die gerade weder laufen noch im Verlauf stehen: sonst
        # verschwindet eine bestehende Regel aus der Sicht und wirkt geloescht.
        # Der „nie gesehen"-Hinweis ist wichtig — ein vertippter Prozessname
        # faellt sonst NIE auf, weil das Profil einfach stumm nie greift.
        stale = self._stale_apps()
        for profil in self._items():
            for eintrag in profil.get("apps", []):
                prozess = parse_app_rule(eintrag)[0]
                if prozess and prozess.lower() not in gesehen:
                    gesehen.add(prozess.lower())
                    tage = stale.get(prozess.lower())
                    if tage is None:
                        zusatz = "zugewiesen"
                    elif tage:
                        zusatz = f"seit {tage} Tagen nicht gesehen"
                    else:
                        zusatz = "noch nie gesehen"
                    self._eintrag(prozess, zusatz)
        self._loading = False
        self._zeige_apps(vorher)

    def _stale_apps(self) -> dict:
        """{prozess_klein: tage_seit_letztem_diktat} fuer Prozesse, die weder gerade
        laufen noch in den letzten 30 Tagen als Diktat-Ziel auftauchten.

        None-Wert gibt es nicht — 0 bedeutet „noch nie gesehen"."""
        try:
            from .windowsfocus import list_visible_window_processes

            running = {a.lower() for a in list_visible_window_processes()}
        except Exception:
            running = set()
        try:
            seen = self.store.last_seen_apps()
        except Exception:
            seen = {}
        import time as _time

        now = _time.time()
        stale = {}
        for profile in self.settings.profiles.items or []:
            if not isinstance(profile, dict) or profile.get("default"):
                continue
            for entry in profile.get("apps", []):
                from ..usersettings import parse_app_rule

                process = parse_app_rule(entry)[0].lower()
                if not process or process in running or process in stale:
                    continue
                ts = seen.get(process)
                if ts is None:
                    stale[process] = 0
                    continue
                days = int((now - ts) // 86400)
                if days >= _STALE_APP_DAYS:
                    stale[process] = days
        return stale

    def _eintrag(self, app: str, zusatz: str) -> None:
        from ..usersettings import parse_app_rule

        # Nur die ALLGEMEINE Regel (ohne Titel-Bedingung) anzeigen — sonst stuende
        # links ein Profil, das nur in einem einzigen Fenster gilt, und der Pfeil
        # loege ueber den Normalfall. Titel-Ausnahmen bekommen ein eigenes Zeichen.
        profil, ausnahmen = "", 0
        for p in self._items():
            for eintrag in p.get("apps", []):
                prozess, titel = parse_app_rule(eintrag)
                if prozess.lower() != app.lower():
                    continue
                if titel:
                    ausnahmen += 1
                elif not profil:
                    profil = str(p.get("name", ""))
        text = f"{app}   ·  {zusatz}"
        if profil:
            text += f"   →  {profil}"
        if ausnahmen:
            text += f"   (+{ausnahmen} nach Titel)"
        self._erhoben.append((app, zusatz, text))

    def _refresh_detail(self) -> None:
        from ..usersettings import parse_app_rule

        app = self._aktuelle_app()
        self._loading = True
        self._regeln.clear()
        self._profil_combo.clear()
        self._regel_profil.clear()
        self._profil_combo.addItem(self.KEIN_PROFIL, "")
        for p in self._items():
            if not p.get("default"):
                name = str(p.get("name", ""))
                self._profil_combo.addItem(name, name)
                self._regel_profil.addItem(name, name)
        self._app_titel.setText(app or "Keine Anwendung gewählt")
        self._app_titel2.setText(app or "—")
        self._profil_combo.setEnabled(bool(app))
        for w in (self._regel_titel, self._regel_profil):
            w.setEnabled(bool(app) and self._regel_profil.count() > 0)
        self._fuelle_schnellwechsel(app)
        if not app:
            self._loading = False
            return

        gewaehlt = ""
        for p in self._items():
            for eintrag in p.get("apps", []):
                prozess, titel = parse_app_rule(eintrag)
                if prozess.lower() != app.lower():
                    continue
                if titel:
                    zeile = QListWidgetItem(
                        f"Titel enthält „{titel}“   →  {p.get('name', '')}")
                    zeile.setData(Qt.UserRole, (str(p.get("name", "")), eintrag))
                    self._regeln.addItem(zeile)
                else:
                    gewaehlt = str(p.get("name", ""))
        index = self._profil_combo.findData(gewaehlt)
        self._profil_combo.setCurrentIndex(max(0, index))
        self._loading = False

    # -- Aenderungen ----------------------------------------------------------------

    def _on_profil_gewaehlt(self, _index: int) -> None:
        if self._loading:
            return
        app = self._aktuelle_app()
        if not app:
            return
        from ..usersettings import parse_app_rule

        ziel = str(self._profil_combo.currentData() or "")
        # Erst ueberall entfernen (nur die Regel OHNE Titel), dann neu setzen: Eine
        # App gehoert nie zu zwei Profilen, sonst entscheidet die Listenreihenfolge
        # und niemand kann nachvollziehen, warum welches gewinnt.
        for p in self._items():
            p["apps"] = [e for e in p.get("apps", [])
                         if not (parse_app_rule(e)[0].lower() == app.lower()
                                 and not parse_app_rule(e)[1])]
        if ziel:
            for p in self._items():
                if str(p.get("name", "")) == ziel:
                    p.setdefault("apps", []).append(app)
                    break
        self.settings.save()
        self._on_changed("profiles")
        log.info("App %s → Profil %s", app, ziel or "(keins)")
        self.refresh()

    # -- Schnellwechsel je App ------------------------------------------------------

    def _app_quick(self) -> dict:
        vorhanden = getattr(self.settings.profiles, "app_quick", None)
        if not isinstance(vorhanden, dict):
            vorhanden = {}
            self.settings.profiles.app_quick = vorhanden
        return vorhanden

    def _fuelle_schnellwechsel(self, app: str) -> None:
        """Ankreuzliste der global freigegebenen Profile, Haken je App.

        Angeboten werden nur Profile, die global im Schnellwechsel stehen — was
        dort ausgeblendet ist, kann eine App nicht zurueckholen. Sonst gaebe es
        zwei Schalter fuer dieselbe Frage, und der eine wuerde den anderen
        stillschweigend uebersteuern.
        """
        from ..usersettings import quickswitch_profiles

        self._schnell.clear()
        namen = quickswitch_profiles(self._items())
        erlaubt = {str(n).lower()
                   for n in (self._app_quick().get((app or "").lower()) or [])}
        for name in namen:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            # Ohne Eintrag ist ALLES erlaubt — dann alle Haken setzen, sonst saehe
            # eine unkonfigurierte App aus, als waere der Schnellwechsel dort leer.
            item.setCheckState(Qt.Checked if not erlaubt or name.lower() in erlaubt
                               else Qt.Unchecked)
            item.setData(Qt.UserRole, name)
            self._schnell.addItem(item)
        self._schnell.setEnabled(bool(app) and bool(namen))

    def _schnell_geaendert(self, _item) -> None:
        if self._loading:
            return
        app = self._aktuelle_app()
        if not app:
            return
        angehakt = [str(self._schnell.item(i).data(Qt.UserRole))
                    for i in range(self._schnell.count())
                    if self._schnell.item(i).checkState() == Qt.Checked]
        speicher = self._app_quick()
        schluessel = app.lower()
        # Alle angehakt = kein Sonderfall → Eintrag entfernen statt die Vollmenge
        # zu speichern. Sonst friert die App auf dem heutigen Profilstand ein: ein
        # spaeter angelegtes Profil taucht dort nie auf, ohne dass man ahnt, warum.
        if len(angehakt) == self._schnell.count():
            speicher.pop(schluessel, None)
        else:
            # Leere Auswahl NICHT speichern — sie hiesse „hier gar kein Profil"
            # und liesse sich per Hotkey nicht mehr verlassen.
            speicher[schluessel] = angehakt or None
            if not angehakt:
                speicher.pop(schluessel, None)
        self.settings.save()
        self._on_changed("profiles")
        log.info("Schnellwechsel fuer %s: %s", app,
                 ", ".join(angehakt) if angehakt else "(alle)")

    def _zeige_apps(self, auswahl: str = "") -> None:
        """Gemerkte Eintraege anzeigen, gefiltert nach dem Suchfeld.

        Getrennt von `refresh()`, weil dort die teuren Quellen stecken (Fensterliste
        per EnumWindows, Verlaufs-Statistik). Beides bei jedem Tastendruck im
        Suchfeld abzufragen waere spuerbar traege.
        """
        suche = self._app_suche.text()
        self._loading = True
        self._apps.clear()
        for app, zusatz, text in getattr(self, "_erhoben", []):
            # Gesucht wird ueber die GANZE Zeile, nicht nur den Prozessnamen — so
            # findet „stichpunkte" auch die Apps, die auf dieses Profil zeigen.
            if not _passt(text, suche):
                continue
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, app)
            self._apps.addItem(item)
        self._loading = False
        if self._apps.count():
            treffer = [i for i in range(self._apps.count())
                       if str(self._apps.item(i).data(Qt.UserRole)) == auswahl]
            self._apps.setCurrentRow(treffer[0] if treffer else 0)
        self._refresh_detail()

    def _filter_apps(self) -> None:
        self._zeige_apps(self._aktuelle_app())

    def _regel_hinzufuegen(self) -> None:
        app = self._aktuelle_app()
        titel = self._regel_titel.text().strip()
        ziel = str(self._regel_profil.currentData() or "")
        if not app or not titel or not ziel:
            return
        from ..usersettings import format_app_rule, parse_app_rule

        # Dieselbe Titel-Bedingung nie zweimal: sonst haengt dieselbe App an zwei
        # Profilen und die Reihenfolge in der Liste entscheidet.
        for p in self._items():
            p["apps"] = [e for e in p.get("apps", [])
                         if not (parse_app_rule(e)[0].lower() == app.lower()
                                 and parse_app_rule(e)[1].lower() == titel.lower())]
        for p in self._items():
            if str(p.get("name", "")) == ziel:
                p.setdefault("apps", []).append(format_app_rule(app, titel))
                break
        self.settings.save()
        self._on_changed("profiles")
        log.info("App %s (Titel %r) → Profil %s", app, titel, ziel)
        self._regel_titel.clear()
        self.refresh()

    def _regel_entfernen(self, item) -> None:
        daten = item.data(Qt.UserRole)
        if not daten:
            return
        profilname, eintrag = daten
        for p in self._items():
            if str(p.get("name", "")) == profilname:
                p["apps"] = [e for e in p.get("apps", []) if e != eintrag]
                break
        self.settings.save()
        self._on_changed("profiles")
        self.refresh()


class ProfilesPage(QWidget):
    """App-Profile: pro Ziel-App automatisch Eingriffsgrad + Stil-Tags fahren.

    Drei Spalten: laufende/haeufige Apps (links) → Doppelklick weist sie dem
    gewaehlten Profil (Mitte) zu; rechts das Detail mit Eingriffsgrad, Stil-Tags
    und zugewiesenen Apps (Doppelklick entfernt). Das Standardprofil ("Alle")
    ist der Fallback fuer alle nicht zugewiesenen Apps. Der grosse Toggle rechts
    neben der Ueberschrift schaltet Profile global — aus = alles ausgegraut.
    """

    _INTERVENTION_LABELS = [("", "Wie Einstellungen (Ausgabe)"),
                            ("minimal", "Minimal (kein LLM-Eingriff)"),
                            ("standard", "Standard"),
                            ("strong", "Strong (starke Glättung)")]

    def __init__(self, settings: UserSettings, store: HistoryStore, on_changed=None):
        super().__init__()
        self.settings = settings
        self.store = store
        self._on_changed = on_changed or (lambda section: None)
        self._loading = False
        from ..usersettings import ensure_default_profile

        ensure_default_profile(self.settings.profiles.items)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        head = QHBoxLayout()
        title = QLabel("Profile")
        title.setStyleSheet(f"color: {TEXT}; font-size: 12pt; font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        from PySide6.QtWidgets import QCheckBox

        # Grosser globaler Toggle, rechtsbuendig in der Titelzeile.
        self._global_cb = QCheckBox()
        self._global_cb.setChecked(settings.profiles.enabled)
        self._global_cb.setToolTip("App-Profile global aktivieren/deaktivieren")
        self._global_cb.setCursor(Qt.PointingHandCursor)
        from .chevron import apply_chevrons

        self._global_cb.setStyleSheet(apply_chevrons(
            f"QCheckBox::indicator {{ width: 22px; height: 22px; border-radius: 6px;"
            f"  border: 1.5px solid {TRACK}; background: transparent; }}"
            f"QCheckBox::indicator:hover {{ border-color: {MUTED}; }}"
            f"QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT};"
            f"  image: url(__CHEV_CHECK__); }}"
        ))
        self._global_cb.toggled.connect(self._on_global_toggled)
        head.addWidget(self._global_cb)
        outer.addLayout(head)
        hint = QLabel("Ein Profil bestimmt, was aus dem Diktat wird. Welche App "
                      "welches Profil bekommt, steht auf der Seite „Apps“ — hier "
                      "gilt „Alle“ als Standard.")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        hint.setWordWrap(True)
        outer.addWidget(hint)
        outer.addSpacing(6)

        # Alles unterhalb des Kopfes lebt in einem Container, der bei global-aus
        # komplett deaktiviert (ausgegraut, nicht klickbar) wird.
        self._body = QWidget()
        body = QHBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        outer.addWidget(self._body, 1)

        # Design-System: Zeilen 7/10-Padding, Radius 8; Hover eine Flaechenstufe heller.
        list_style = (
            f"QListWidget {{ background: transparent; border: none; outline: none;"
            f"  color: {TEXT}; font-size: 9.5pt; }}"
            f"QListWidget::item {{ padding: 7px 10px; border-radius: 8px; }}"
            f"QListWidget::item:hover {{ background: {ROW_HOVER}; }}"
            f"QListWidget::item:selected {{ background: {NAV_ACTIVE_BG}; color: {ACCENT}; }}"
        )
        # Checkbox im Design-System: 15px, Radius 4, TRACK-Rahmen → Akzent-Fuellung
        # mit dunklem Haken (generiertes Icon, QSS kann keinen Haken zeichnen).
        cb_style = (
            f"QCheckBox {{ color: {TEXT}; font-size: 9.5pt; spacing: 8px; }}"
            f"QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px;"
            f"  border: 1.5px solid {TRACK}; background: transparent; }}"
            f"QCheckBox::indicator:hover {{ border-color: {MUTED}; }}"
            f"QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT};"
            f"  image: url(__CHEV_CHECK__); }}"
            f"QCheckBox:disabled {{ color: {MUTED}; }}"
        )
        # Combobox im dunklen Karten-Kontext: geschlossenes Feld UND aufgeklappte Liste
        # in Brand-Farben, damit das Dropdown nicht im Windows-Hell-Stil aufpoppt.
        combo_style = (
            f"QComboBox {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE};"
            f"  border-radius: 8px; padding: 5px 10px; font-size: 9.5pt; }}"
            f"QComboBox:hover {{ background: {ROW_HOVER}; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QComboBox::down-arrow {{ width: 11px; height: 11px; margin-right: 6px;"
            f"  image: url(__CHEV_DOWN__); }}"
            f"QComboBox QAbstractItemView {{ background: {SIDEBAR}; color: {TEXT};"
            f"  border: 1px solid {TRACK}; outline: none; padding: 4px;"
            f"  selection-background-color: {NAV_ACTIVE_BG}; selection-color: {ACCENT}; }}"
            f"QComboBox QAbstractItemView::item {{ min-height: 24px; padding: 4px 8px;"
            f"  border-radius: 5px; }}"
        )

        # Kleine Abschnitts-Ueberschrift + „?"-Badge — ersetzt die frueheren
        # dauerhaft sichtbaren Erklaertexte (konsistent mit den Einstellungen).
        def _section(text: str, tip: str) -> QWidget:
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 4, 0, 0)
            lay.setSpacing(6)
            lab = QLabel(text)
            lab.setStyleSheet(f"color: {MUTED}; font-size: 8.5pt; font-weight: 600;")
            lay.addWidget(lab)
            lay.addWidget(HelpBadge(tip))
            lay.addStretch(1)
            return w

        # Links: Profil-Liste (Klick = Auswahl) + Funktions-Schalter darunter.
        # Die frueher hier stehende App-Spalte ist mit v4.7.0 auf die eigene
        # Seite „Apps" gewandert: Ein Profil beantwortet „was wird aus dem
        # Diktat", die Frage „wo gilt das" gehoert zur App, nicht zum Profil.
        profiles_frame, profiles_box = _card("Profile")
        self._profil_suche = _suchfeld("Profil suchen …")
        self._profil_suche.textChanged.connect(lambda _t: self._refresh_profiles(keep_row=True))
        profiles_box.addWidget(self._profil_suche)
        self._profiles_list = QListWidget()
        self._profiles_list.setStyleSheet(list_style)
        _no_hscroll(self._profiles_list)
        self._profiles_list.currentRowChanged.connect(lambda _r: self._refresh_detail())
        profiles_box.addWidget(self._profiles_list, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        add_btn = style_button(QPushButton("Hinzufügen"))
        add_btn.clicked.connect(self._add_profile)
        del_btn = style_button(QPushButton("Löschen"), "ghost")
        del_btn.clicked.connect(self._delete_profile)
        row.addWidget(add_btn, 1)
        row.addWidget(del_btn)
        profiles_box.addLayout(row)
        body.addWidget(profiles_frame, 1)

        # Rechts: Detail des gewaehlten Profils.
        detail_frame, detail_box = _card("Details")
        from PySide6.QtWidgets import QComboBox, QLineEdit

        # Titel = editierbares Feld: Klick hinein → Profil umbenennen (Enter/Fokusverlust
        # uebernimmt). Sieht wie eine Ueberschrift aus, verhaelt sich wie ein Eingabefeld.
        self._detail_title = QLineEdit("")
        self._detail_title.setFrame(False)
        self._detail_title.setStyleSheet(
            f"QLineEdit {{ color: {TEXT}; font-size: 11pt; font-weight: 600;"
            f"  background: transparent; border: none; padding: 0; }}"
            f"QLineEdit:focus {{ border-bottom: 1px solid {ACCENT}; }}"
        )
        self._detail_title.setToolTip("Zum Umbenennen anklicken, Enter übernimmt")
        self._detail_title.editingFinished.connect(self._on_rename_profile)
        title_row = QWidget()
        trow = QHBoxLayout(title_row)
        trow.setContentsMargins(0, 0, 0, 0)
        trow.setSpacing(6)
        trow.addWidget(self._detail_title, 1)
        trow.addWidget(HelpBadge("Name anklicken und tippen — Enter benennt das Profil um."))
        detail_box.addWidget(title_row)

        from .chevron import apply_chevrons

        # Ausgabeformat: die Einstellung, die aus einem Profil mehr macht als eine
        # Glaettungsstufe. Der frueher entfernte „Modus-Slot" ist damit zurueck —
        # diesmal mit einem Zweck, den man beim Diktieren sofort merkt.
        detail_box.addWidget(_section(
            "Ausgabeformat", "Was aus dem Diktat wird. „Diktat“ = bereinigter Text "
            "wie gesprochen. „E-Mail“ und „KI-Prompt“ formulieren um: Anrede und "
            "Absätze bzw. knappe Stichpunkte für eine KI.",
        ))
        self._profile_format_combo = QComboBox()
        self._profile_format_combo.setStyleSheet(apply_chevrons(combo_style))
        for value, label in PROFILE_FORMATS:
            self._profile_format_combo.addItem(label, value)
        self._profile_format_combo.currentIndexChanged.connect(
            self._on_profile_format_changed
        )
        detail_box.addWidget(self._profile_format_combo)

        self._quick_cb = QCheckBox("Im Schnellwechsel zeigen")
        self._quick_cb.setCursor(Qt.PointingHandCursor)
        self._quick_cb.setStyleSheet(apply_chevrons(cb_style))
        self._quick_cb.setToolTip(
            "Punkt in der Pille, Profil-Hotkey und Auswahlliste gehen nur durch "
            "diese Profile. Wer viele pflegt, aber im Alltag zwischen zweien "
            "wechselt, blendet den Rest hier aus."
        )
        self._quick_cb.toggled.connect(self._on_quick_toggled)
        detail_box.addWidget(self._quick_cb)

        # Ab hier: alles, was der Normalfall NICHT braucht. Der Umschalter unten
        # blendet diesen Block aus — ein Profil besteht dann aus Name, Ausgabeformat
        # und Schnellwechsel. Die App-Zuweisung steckt bewusst hier drin: Profile
        # sind seit den Ausgabeformaten in erster Linie eine Wahl beim Sprechen,
        # nicht eine Automatik nach Prozessnamen.
        self._advanced_box = QWidget()
        adv = QVBoxLayout(self._advanced_box)
        adv.setContentsMargins(0, 0, 0, 0)
        adv.setSpacing(detail_box.spacing())
        detail_box.addWidget(self._advanced_box, 1)
        detail_box = adv

        detail_box.addWidget(_section(
            "Eingriff", "Wie stark die KI das Diktat glättet. „Wie Einstellungen“ = "
            "globaler Wert aus Einstellungen → Ausgabe.",
        ))
        self._intervention_combo = QComboBox()
        self._intervention_combo.setStyleSheet(apply_chevrons(combo_style))
        for value, label in self._INTERVENTION_LABELS:
            self._intervention_combo.addItem(label, value)
        self._intervention_combo.currentIndexChanged.connect(self._on_intervention_changed)
        detail_box.addWidget(self._intervention_combo)

        # Gesprochenes Safe-Word je Profil: im Meeting/Grossraum unpassend und
        # zufaellig ausloesbar. Der »-Knopf in der Pille bleibt immer verfuegbar.
        detail_box.addWidget(_section(
            "Safe-Word (gesprochen)", "Ob in diesen Apps ein gesprochenes Safe-Word "
            "Befehle auslöst. Der »-Knopf in der Pille funktioniert immer.",
        ))
        self._profile_command_combo = QComboBox()
        self._profile_command_combo.setStyleSheet(apply_chevrons(combo_style))
        for value, label in (("", "Wie Einstellungen (Ausgabe)"),
                             ("on", "An — gesprochenes Safe-Word erlaubt"),
                             ("off", "Aus — nur über den »-Knopf")):
            self._profile_command_combo.addItem(label, value)
        self._profile_command_combo.currentIndexChanged.connect(
            self._on_profile_command_changed
        )
        detail_box.addWidget(self._profile_command_combo)

        # Der Stil-Tag-Editor ist mit v3.7.2 entfallen. Die Profilseite beantwortet
        # jetzt genau eine Frage — „in welcher App wie stark eingreifen" — statt
        # nebenbei noch Stilvorgaben und Modus-Slots anzubieten, die in der Praxis
        # leer blieben. Das Feld `tags` bleibt in den Settings erhalten (alte
        # settings.json laden unveraendert) und wirkt weiter, falls jemand es dort
        # von Hand pflegt; die Pipeline nimmt es unveraendert entgegen.

        detail_box.addWidget(_section(
            "Nachricht absenden", "Nach dem Einfügen zusätzlich Enter drücken — "
            "praktisch in KI-Chats, gefährlich in E-Mails.",
        ))
        self._autosend_cb = QCheckBox("Diktat direkt abschicken")
        self._autosend_cb.setStyleSheet(apply_chevrons(cb_style))
        self._autosend_cb.setCursor(Qt.PointingHandCursor)
        self._autosend_cb.setToolTip(
            "Gilt nur für die diesem Profil zugewiesenen Apps und nur bei einem "
            "normalen Diktat — nach einem Befehl oder einem Rohtext-Rückfall wird "
            "nie automatisch gesendet."
        )
        self._autosend_cb.toggled.connect(self._on_autosend_toggled)
        detail_box.addWidget(self._autosend_cb)

        # Ohne diesen Dehnungs-Platzhalter verteilt Qt den freien Platz GLEICHMAESSIG
        # zwischen allen Zeilen, sobald der erweiterte Block (mit der App-Liste, die
        # den Raum bisher aufgefangen hat) versteckt ist: Beschriftungen standen dann
        # weit von ihren Bedienelementen entfernt und die Karte sah leer aus.
        # WICHTIG in die AEUSSERE Karte — `detail_box` zeigt hier laengst auf den
        # erweiterten Container, dort waere der Platzhalter mit versteckt.
        detail_frame.layout().addStretch(1)

        self._advanced_cb = QCheckBox("Erweiterte Einstellungen")
        self._advanced_cb.setCursor(Qt.PointingHandCursor)
        self._advanced_cb.setStyleSheet(apply_chevrons(cb_style))
        self._advanced_cb.setToolTip(
            "Zeigt Eingriffsgrad, Safe-Word und automatisches Absenden. Ohne "
            "das besteht ein Profil aus Name, Ausgabeformat und Schnellwechsel "
            "— für die meisten genug. Welche App welches Profil bekommt, steht "
            "auf der Seite „Apps“."
        )
        self._advanced_cb.setChecked(bool(self.settings.interface.profiles_advanced))
        self._advanced_cb.toggled.connect(self._on_advanced_toggled)
        detail_frame.layout().addWidget(self._advanced_cb)
        self._advanced_box.setVisible(self._advanced_cb.isChecked())
        body.addWidget(detail_frame, 1)

        # Der Funktions-Balken (Mathe-Funktion) ist mit v3.7.4 entfallen: Er
        # schaltete dasselbe Feld wie die Formel-Erkennung in den Einstellungen —
        # zwei Schalter fuer einen Wert, an zwei weit auseinanderliegenden Orten.
        # Auf der Profilseite hatte er ohnehin nichts zu suchen: Er galt global,
        # unabhaengig von jedem Profil.

        self._apply_body_enabled(settings.profiles.enabled)

    # -- Datenzugriff -----------------------------------------------------------------

    def _items(self) -> list:
        return self.settings.profiles.items

    def _current_index(self) -> int:
        """Index in `items` — aus dem Item, NICHT aus der Zeilennummer.

        Mit dem Suchfeld sind das zwei verschiedene Dinge: Zeile 0 einer gefilterten
        Liste kann Profil 5 sein. Wer hier die Zeilennummer nimmt, benennt oder
        loescht stillschweigend das falsche Profil.
        """
        item = self._profiles_list.currentItem()
        if item is None:
            return -1
        wert = item.data(Qt.UserRole)
        return int(wert) if isinstance(wert, int) else -1

    def _current_profile(self) -> dict | None:
        index = self._current_index()
        items = self._items()
        return items[index] if 0 <= index < len(items) else None

    def _save(self) -> None:
        self.settings.save()

    # -- Aufbau/Refresh ------------------------------------------------------------------

    def refresh(self) -> None:
        from ..usersettings import ensure_default_profile

        ensure_default_profile(self._items())
        self._refresh_profiles(keep_row=True)

    # BEWUSST OHNE die Brand-Akzentfarbe (#35C0D8): die steht im ganzen Programm
    # fuer „ausgewaehlt". Als Kategoriefarbe gelesen wirkte der E-Mail-Punkt wie
    # eine Markierung — genau so wurde es gemeldet.
    _MODE_DOT_COLORS = {"math": "#AA78F0", "prompt": "#E8A13C",
                        "email": "#6E86C8", "summary": "#7FD1A6"}
    # Kurzform des Ausgabeformats hinter dem Namen. Beantwortet die Frage „was macht
    # dieses Profil?" in der LISTE — vorher musste man jedes Profil anklicken.
    _MODE_KURZ = {"email": "E-Mail", "prompt": "KI-Prompt", "math": "Formeln",
                  "summary": "Stichpunkte"}

    @staticmethod
    def _mode_dot_icon(color: str) -> QIcon:
        """Kleiner gefuellter Punkt in der Modus-Farbe — dieselbe Sprache wie der
        Status-Punkt im Overlay (violett = Mathe, amber = KI-Prompting)."""
        pm = QPixmap(16, 16)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(8, 8), 4, 4)
        p.end()
        return QIcon(pm)

    def _refresh_profiles(self, keep_row: bool = False) -> None:
        from ..usersettings import profile_in_quickswitch, profile_mode

        previous = self._current_index() if keep_row else 0
        suche = self._profil_suche.text()
        self._loading = True
        self._profiles_list.clear()
        for index, profile in enumerate(self._items()):
            name = profile.get("name", "Profil")
            if profile.get("default"):
                name += "  („Alle“)"
            kurz = self._MODE_KURZ.get(profile_mode(profile), "")
            # „E-Mail · E-Mail" ist keine Zusatzinfo, sondern Laerm: Die
            # Standardprofile heissen wie ihr Format. Nur anhaengen, wenn der
            # Name das Format NICHT schon sagt.
            if kurz and kurz.lower() not in name.lower():
                name += f"   ·  {kurz}"
            if not profile_in_quickswitch(profile):
                # Ausgeblendete Profile bleiben sichtbar, aber erkennbar: sonst
                # sucht man spaeter, warum der Schnellwechsel eines auslaesst.
                name += "   (nicht im Schnellwechsel)"
            if not _passt(name, suche):
                continue
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, index)
            # Modus-Slot direkt in der Liste sichtbar machen (Design-System):
            # farbiger Punkt in der Modus-Farbe vor dem Namen.
            mode = profile_mode(profile)
            if mode in self._MODE_DOT_COLORS:
                item.setIcon(self._mode_dot_icon(self._MODE_DOT_COLORS[mode]))
            self._profiles_list.addItem(item)
        self._loading = False
        if self._profiles_list.count():
            zeilen = [i for i in range(self._profiles_list.count())
                      if self._profiles_list.item(i).data(Qt.UserRole) == previous]
            self._profiles_list.setCurrentRow(zeilen[0] if zeilen else 0)
        self._refresh_detail()

    def _refresh_detail(self) -> None:
        profile = self._current_profile()
        self._loading = True
        if profile is None:
            self._detail_title.setText("")
            self._detail_title.setEnabled(False)
            self._profile_command_combo.setCurrentIndex(0)
            self._loading = False
            return
        self._detail_title.setEnabled(True)
        self._detail_title.setText(profile.get("name", "Profil"))
        from ..usersettings import profile_mode

        from ..usersettings import profile_command_mode

        self._profile_command_combo.setCurrentIndex(
            ["", "on", "off"].index(profile_command_mode(profile))
        )
        self._autosend_cb.setChecked(bool(profile.get("auto_send", False)))
        values = [v for v, _l in self._INTERVENTION_LABELS]
        current = profile.get("intervention", "")
        self._intervention_combo.setCurrentIndex(
            values.index(current) if current in values else 0
        )
        from ..usersettings import profile_mode

        formate = [v for v, _l in PROFILE_FORMATS]
        fmt = profile_mode(profile)
        self._profile_format_combo.setCurrentIndex(
            formate.index(fmt) if fmt in formate else 0
        )
        from ..usersettings import profile_in_quickswitch

        self._quick_cb.setChecked(profile_in_quickswitch(profile))
        self._loading = False

    # -- Interaktionen ---------------------------------------------------------------------

    def _apply_body_enabled(self, on: bool) -> None:
        """Bei global-aus den GESAMTEN Bereich unter dem Kopf klar sichtbar ausgrauen:
        nicht nur deaktivieren (Qt graut nur dezent), sondern zusaetzlich per
        Opacity-Effekt deutlich abdunkeln. Effekt nur im Aus-Zustand setzen — im
        Normalbetrieb kein Effekt (verhindert Render-Eigenheiten beim Scrollen)."""
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        self._body.setEnabled(on)
        if on:
            self._body.setGraphicsEffect(None)
        else:
            effect = QGraphicsOpacityEffect(self._body)
            effect.setOpacity(0.30)
            self._body.setGraphicsEffect(effect)

    def _on_global_toggled(self, on: bool) -> None:
        self.settings.profiles.enabled = on
        self._apply_body_enabled(on)
        self._save()


    def _on_autosend_toggled(self, on: bool) -> None:
        if self._loading:
            return
        profile = self._current_profile()
        if profile is not None:
            profile["auto_send"] = bool(on)
            self._save()

    def _on_profile_command_changed(self, _index: int) -> None:
        if self._loading:
            return
        profile = self._current_profile()
        if profile is not None:
            profile["command"] = self._profile_command_combo.currentData()
            self._save()


    def _on_rename_profile(self) -> None:
        if self._loading:
            return
        profile = self._current_profile()
        name = self._detail_title.text().strip()
        if profile is None or not name or name == profile.get("name"):
            return
        profile["name"] = name
        self._save()
        self._refresh_profiles(keep_row=True)

    def _on_advanced_toggled(self, checked: bool) -> None:
        self._advanced_box.setVisible(bool(checked))
        if self._loading:
            return
        self.settings.interface.profiles_advanced = bool(checked)
        self.settings.save()

    def _on_quick_toggled(self, checked: bool) -> None:
        if self._loading:
            return
        profile = self._current_profile()
        if profile is not None:
            profile["quick"] = bool(checked)
            self._save()
            self._refresh_profiles(keep_row=True)

    def _on_profile_format_changed(self, _index: int) -> None:
        if self._loading:
            return
        profile = self._current_profile()
        if profile is not None:
            profile["mode"] = self._profile_format_combo.currentData()
            self._save()

    def _on_intervention_changed(self, _index: int) -> None:
        if self._loading:
            return
        profile = self._current_profile()
        if profile is not None:
            profile["intervention"] = self._intervention_combo.currentData()
            self._save()

    def _add_profile(self) -> None:
        items = self._items()
        items.append({"name": f"Profil {len(items)}", "intervention": "standard",
                      "tags": [], "apps": []})
        self._save()
        # Suche leeren: Sonst legt man bei aktivem Filter ein Profil an, das die
        # Suche nicht trifft — es waere sofort unsichtbar und wirkte wie ein
        # fehlgeschlagener Klick.
        if self._profil_suche.text():
            self._loading = True
            self._profil_suche.clear()
            self._loading = False
        self._refresh_profiles()
        self._profiles_list.setCurrentRow(self._profiles_list.count() - 1)

    def _delete_profile(self) -> None:
        row = self._current_index()
        items = self._items()
        if 0 <= row < len(items) and not items[row].get("default"):
            del items[row]   # das Standardprofil ist nicht loeschbar
            self._save()
            self._refresh_profiles()


class MainWindow(QMainWindow):
    PAGE_KEYS = ("home", "insights", "profiles", "apps", "settings")

    def __init__(self, settings: UserSettings, store: HistoryStore,
                 settings_panel: QWidget, on_close_to_tray):
        super().__init__()
        self.settings = settings
        self._on_close_to_tray = on_close_to_tray

        self.setWindowTitle(f"Fleech {__version__}")
        # Untergrenze, unter der Inhalte rechts abgeschnitten wuerden: Die
        # Insights-Reihen (drei Karten) und die Profilseite (drei Spalten) brauchen
        # diese Breite. Ohne Minimum liess sich das Fenster in einen Zustand ziehen,
        # in dem Text einfach verschwand — statt umzubrechen oder zu scrollen.
        self.setMinimumSize(940, 620)
        w = settings.window
        if w.x is not None and w.y is not None:
            self.setGeometry(w.x, w.y, max(w.width, 940), max(w.height, 620))
        else:
            self.resize(w.width, w.height)

        # Root = Sidebar-Farbe. Der Content-Bereich (dunkler) legt sich als eigenes
        # Panel mit abgerundeter oberer Ecke darueber → weicher Uebergang von der
        # Sidebar ins Dunkle statt einer harten Kante.
        root = QWidget()
        root.setObjectName("root")
        root.setStyleSheet(f"QWidget#root {{ background: {SIDEBAR}; }}")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if sys.platform.startswith("linux"):
            # Linux/KDE: native Dekoration laesst sich weder faerben noch teilweise
            # ausblenden → rahmenlos + eigene schmale Leiste in Sidebar-Farbe (ohne
            # Icon/Titel, nur Fenster-Buttons). Windows behaelt die native Leiste
            # (DWM-gefaerbt, siehe showEvent).
            from .titlebar import LinuxTitleBar

            self.setWindowFlag(Qt.FramelessWindowHint, True)
            wrapper = QWidget()
            wrapper.setObjectName("rootwrap")
            wrapper.setStyleSheet(f"QWidget#rootwrap {{ background: {SIDEBAR}; }}")
            vbox = QVBoxLayout(wrapper)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(0)
            self._linux_titlebar = LinuxTitleBar(self, bg=SIDEBAR, fg=MUTED, hover_bg=CARD)
            vbox.addWidget(self._linux_titlebar.build())
            vbox.addWidget(root, 1)
            self.setCentralWidget(wrapper)
            # Rahmenlos = kein WM-Resize-Rand → dezenter Griff unten rechts
            # (Position haelt resizeEvent nach); Meta+Drag (KWin) geht zusaetzlich.
            self._size_grip = QSizeGrip(wrapper)
            self._size_grip.setFixedSize(14, 14)
            self._size_grip.setStyleSheet("background: transparent;")
        else:
            self.setCentralWidget(root)

        # -- Sidebar --------------------------------------------------------------
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(176)
        sidebar.setStyleSheet(f"QFrame#sidebar {{ background: {SIDEBAR}; }}")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 10, 10, 12)

        brand = QHBoxLayout()
        brand.setSpacing(9)
        brand.setContentsMargins(6, 2, 6, 0)
        logo = QLabel()
        logo.setPixmap(_logo_pixmap(30, self.devicePixelRatioF()))
        brand_name = QLabel("Fleech")
        brand_name.setStyleSheet(f"color: {TEXT}; font-size: 15pt; font-weight: 600;")
        brand.addWidget(logo)
        brand.addWidget(brand_name)
        brand.addStretch(1)
        side.addLayout(brand)
        side.addSpacing(20)

        self._nav_group = QButtonGroup(self)
        self._nav_buttons: dict[str, QPushButton] = {}

        def nav_button(key: str, label: str, icon_kind: str) -> QPushButton:
            btn = QPushButton(f"  {label}")
            btn.setCheckable(True)
            btn.setIcon(_nav_icon(icon_kind, MUTED))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(34)
            # Design-System: gedaempft → Hover hellt auch die SCHRIFT auf → aktiv Akzent.
            btn.setStyleSheet(
                f"QPushButton {{ color: {MUTED}; background: transparent; border: none;"
                f"  border-radius: 8px; padding: 0 10px; text-align: left;"
                f"  font-size: 10pt; font-weight: 500; }}"
                f"QPushButton:hover {{ background: {CARD}; color: {TEXT}; }}"
                f"QPushButton:checked {{ background: {NAV_ACTIVE_BG}; color: {ACCENT}; }}"
            )
            btn.clicked.connect(lambda: self.show_page(key))
            self._nav_group.addButton(btn)
            self._nav_buttons[key] = btn
            return btn

        side.addWidget(nav_button("home", "Home", "home"))
        side.addSpacing(2)
        side.addWidget(nav_button("insights", "Insights", "chart"))
        side.addSpacing(2)
        side.addWidget(nav_button("profiles", "Profile", "profile"))
        side.addSpacing(2)
        side.addWidget(nav_button("apps", "Apps", "apps"))
        side.addStretch(1)
        # Einstellungen unten, mit Hairline-Trenner abgesetzt (Design-System).
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {BORDER_HAIRLINE}; border: none;")
        side.addWidget(divider)
        side.addSpacing(8)
        side.addWidget(nav_button("settings", "Einstellungen", "sliders"))
        layout.addWidget(sidebar)

        # -- Seiten ----------------------------------------------------------------
        self._stack = QStackedWidget()
        self.home = HomePage(settings, store, on_change=self._on_history_edited)
        self.insights = InsightsPage(store, on_add_rule=self._add_dictionary_rule,
                                     settings=settings,
                                     on_ignored=self._reload_dictionary_editor)
        self.profiles = ProfilesPage(
            settings, store,
            on_changed=getattr(settings_panel, "_on_changed", None),
        )
        self.apps = AppsPage(
            settings, store,
            on_changed=getattr(settings_panel, "_on_changed", None),
        )
        self.settings_panel = settings_panel
        # Karten per Rechtsklick ausblendbar — ersetzt elf Checkboxen.
        _notify = getattr(settings_panel, "_on_changed", None)
        self.home.enable_hiding(settings, _notify)
        self.insights.enable_hiding(settings, _notify)
        self._stack.addWidget(self.home)
        self._stack.addWidget(self.insights)
        self._stack.addWidget(self.profiles)
        self._stack.addWidget(self.apps)
        self._stack.addWidget(settings_panel)
        # Content-Panel: eigener dunkler Hintergrund mit abgerundeter oberer Ecke
        # (oben links, wo es an die Sidebar/den oberen Rand grenzt).
        content = QWidget()
        content.setObjectName("content")
        content.setStyleSheet(
            f"QWidget#content {{ background: {BG}; border-top-left-radius: 16px; }}"
        )
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.addWidget(self._stack)
        layout.addWidget(content, 1)

        self.apply_interface()
        self.show_page("home")

    # -- Navigation ---------------------------------------------------------------

    def _add_dictionary_rule(self, wrong: str, right: str) -> None:
        """Vorschlag aus den Insights als Woerterbuch-Regel uebernehmen.

        Ein Klick statt „Einstellungen oeffnen, Woerterbuch finden, Zeile tippen" —
        genau die Handlung, auf die die Beobachtung hinauslaeuft."""
        line = f"{wrong} => {right}"
        rules = self.settings.output.dictionary
        if any(str(existing).strip().lower() == line.lower() for existing in rules):
            return
        rules.append(line)
        self.settings.save()
        log.info("Woerterbuch-Regel aus Insights uebernommen: %s", line)
        # Settings-Seite und laufende Pipeline nachziehen (dieselbe Nahtstelle, die
        # auch der Editor nutzt) — sonst greift die Regel erst nach einem Neustart.
        notify = getattr(self.settings_panel, "_on_changed", None)
        if callable(notify):
            notify("dictionary")
        reload_editor = getattr(self.settings_panel, "reload_dictionary", None)
        if callable(reload_editor):
            reload_editor()

    def _reload_dictionary_editor(self) -> None:
        """Woerterbuch-Seite (inkl. Ignorier-Liste) nachziehen, wenn sich die Daten
        ausserhalb des Editors geaendert haben (z. B. „Ignorieren" in den Insights)."""
        reload_editor = getattr(self.settings_panel, "reload_dictionary", None)
        if callable(reload_editor):
            reload_editor()

    def show_page(self, key: str) -> None:
        index = self.PAGE_KEYS.index(key) if key in self.PAGE_KEYS else 0
        self._stack.setCurrentIndex(index)
        self._nav_buttons[self.PAGE_KEYS[index]].setChecked(True)
        if key == "home":
            self.home.refresh()
        elif key == "insights":
            self.insights.refresh()
        elif key == "profiles":
            self.profiles.refresh()
        elif key == "apps":
            self.apps.refresh()

    def open_page(self, key: str) -> None:
        """Fenster anzeigen + Seite waehlen (Tray-Aktionen)."""
        self.show_page(key)
        self.show()
        self.raise_()
        self.activateWindow()

    def apply_interface(self) -> None:
        """UI-Bausteine gemaess settings.interface schalten (live aus den Settings)."""
        self.home.apply_interface(self.settings.interface)
        self.insights.apply_interface(self.settings.interface)

    def _on_history_edited(self) -> None:
        """Nach dem Loeschen eines einzelnen Verlaufseintrags: Insights nachziehen."""
        self.insights.refresh()

    def refresh_data(self) -> None:
        """Nach jedem aufgezeichneten Diktat: sichtbare Seite aktualisieren."""
        if not self.isVisible():
            return
        current = self._stack.currentIndex()
        if current == 0:
            self.home.refresh()
        elif current == 1:
            self.insights.refresh()
        elif current == 2:
            self.profiles.refresh()

    # -- Fenster -------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Titelleiste/Rahmen in App-Farben (Win 11, Best-Effort) — nahtloser Uebergang
        # statt Standard-Windows-Chrome. hide_caption: kein Icon/„Fleech x.y.z" in der
        # Leiste (der Fenstertitel bleibt fuer Taskleiste/Alt-Tab erhalten).
        from .titlebar import apply_dark_titlebar

        apply_dark_titlebar(self, hide_caption=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        grip = getattr(self, "_size_grip", None)
        if grip is not None:
            grip.move(self.width() - grip.width(), self.height() - grip.height())
            grip.raise_()

    def closeEvent(self, event) -> None:
        # Offene Textfelder verbindlich uebernehmen, BEVOR gespeichert wird — sonst
        # geht ein noch nicht bestaetigter Eintrag (Cursor im Feld) verloren.
        self.settings_panel.commit()
        w = self.settings.window
        w.x, w.y, w.width, w.height = self.x(), self.y(), self.width(), self.height()
        self.settings.save()
        event.ignore()
        self.hide()
        self._on_close_to_tray()
