"""Wiederverwendbare Bausteine der Oberflaeche — Widgets, Karten, Helfer.

Alles hier ist seitenunabhaengig: Was mehr als eine Seite braucht, steht in
dieser Datei; was nur eine Seite braucht, bleibt bei ihr. Bis 5.4.0 lag das
zusammen mit den vier Seiten in einer 2970-Zeilen-Datei.

Die Trennlinie ist bewusst so gezogen: `_logo_pixmap` und `_nav_icon` sind NICHT
hier, weil sie nur das Fenstergeruest benutzt — sie waeren hier ein Angebot, das
niemand annimmt.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .theme import (
    _STREAK_SHADES, ACCENT, ACCENT_DIM, BORDER_CARD, BORDER_HAIRLINE, CARD,
    MUTED, NAV_ACTIVE_BG, TEXT, TRACK,
)


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


def _no_hscroll(lst) -> None:
    """Liste umbrechen statt horizontal scrollen: lange Eintraege (z. B. der
    „Alle"-Fallback oder App-Namen mit Zusatz) gehen in eine zweite Zeile, statt
    eine horizontale Scrollleiste am unteren Rand zu erzeugen."""
    lst.setWordWrap(True)
    lst.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    lst.setTextElideMode(Qt.ElideNone)


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
