"""Das Fenstergeruest: Sidebar, Seitenwechsel, Titelleiste, Geometrie.

Die vier Seiten selbst liegen in `ui/pages/`, die Bausteine in `ui/widgets.py`,
die Dialoge in `ui/dialogs.py`, die Farben in `ui/theme.py`. Hier bleibt nur, was
das Fenster als Ganzes betrifft.

Schliessen minimiert in den Tray (DesktopApp-Verhalten unveraendert). Geometrie
persistiert in settings.window.

Der Block „Weiterhin von hier erreichbar" unten ist kein Versehen: Tests und
andere Module ziehen diese Namen seit jeher aus `main_window`. Der Umzug soll
aufraeumen, nicht brechen — wer heute laeuft, laeuft weiter.
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSizeGrip, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import __version__
from ..history import HistoryStore
from ..usersettings import UserSettings
from .theme import ACCENT, CARD, MUTED, SIDEBAR, TEXT

# -- Weiterhin von hier erreichbar (Re-Export, siehe Modul-Docstring) --------------
from .dialogs import (  # noqa: F401
    DictionarySuggestionDialog, PromptDialog, TranscriptDetailDialog,
    WordDetailDialog,
)
from .pages.apps import _STALE_APP_DAYS, AppsPage  # noqa: F401
from .pages.home import HistoryEntryRow, HomePage  # noqa: F401
from .pages.insights import (  # noqa: F401
    _ADVICE_SCAN, _ADVICE_SHOWN, _DAYPART_LABELS, _RANGE_DAYS, INSIGHT_RANGES,
    InsightsPage, _latency_trend_line, _processing_summary,
)
from .pages.profiles import ProfilesPage  # noqa: F401
from .theme import (  # noqa: F401
    _STREAK_SHADES, ACCENT_DIM, BG, BORDER_CARD, BORDER_HAIRLINE, DANGER_TEXT,
    NAV_ACTIVE_BG, ON_ACCENT, ROW_HOVER, TRACK, button_qss, style_button,
)
from .widgets import (  # noqa: F401
    HelpBadge, StreakCalendar, UsageBar, WpmGauge, _ElidedLabel, _card, _dauer,
    _diktierzeit_text, _link_button, _metric, _no_hscroll, _passt, _ranked_row,
    _rebuild_ranked_list, _suchfeld, _x_icon, enable_card_hiding,
)

log = logging.getLogger(__name__)


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


class MainWindow(QMainWindow):
    PAGE_KEYS = ("home", "insights", "profiles", "apps", "settings")

    def __init__(self, settings: UserSettings, store: HistoryStore,
                 settings_panel: QWidget, on_close_to_tray, on_reprocess=None):
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
        self.home = HomePage(settings, store, on_change=self._on_history_edited,
                             on_reprocess=on_reprocess)
        self.insights = InsightsPage(store, on_add_rule=self._add_dictionary_rule,
                                     settings=settings,
                                     on_ignored=self._reload_dictionary_editor,
                                     kontext_fn=self._kontext_speicher)
        self.profiles = ProfilesPage(
            settings, store,
            on_changed=getattr(settings_panel, "_on_changed", None),
        )
        self.apps = AppsPage(
            settings, store,
            on_changed=getattr(settings_panel, "_on_changed", None),
            kontext_fn=self._kontext_speicher,
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

    def _kontext_speicher(self):
        """Verbindung zum Projekt-Gedaechtnis fuer die Insights-Seite (V-14)."""
        from ..kontext import oeffne

        return oeffne(getattr(self.settings.advanced, "kontext_lernen", True))

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
        self._kontext_vergessen(wrong)
        # Settings-Seite und laufende Pipeline nachziehen (dieselbe Nahtstelle, die
        # auch der Editor nutzt) — sonst greift die Regel erst nach einem Neustart.
        notify = getattr(self.settings_panel, "_on_changed", None)
        if callable(notify):
            notify("dictionary")
        reload_editor = getattr(self.settings_panel, "reload_dictionary", None)
        if callable(reload_editor):
            reload_editor()

    def _kontext_vergessen(self, falsch: str) -> None:
        """Die falsche Schreibweise auch aus dem Gedaechtnis nehmen (V-14/H-B3).

        Ohne das bliebe der Fehler im Priming: `kontext.db` gibt gelernte Begriffe
        als `initial_prompt` an Whisper zurueck — die Erkennung haette also weiter
        „Cloud-Code" gehoert, und die frische Regel haette es hinterher jedes Mal
        wieder korrigieren muessen. Fehlschlaege sind hier folgenlos: Die Regel
        steht bereits und wirkt."""
        speicher = self._kontext_speicher()
        if speicher is None or not falsch.strip():
            return
        anzahl = speicher.vergiss(begriff=falsch)
        if anzahl:
            log.info("Gedaechtnis: %r vergessen (%d Eintraege).", falsch, anzahl)
        panel_refresh = getattr(self.settings_panel, "_refresh_kontext_zeile", None)
        if callable(panel_refresh):
            panel_refresh()

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
