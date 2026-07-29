"""Titelleiste in App-Farben — weg vom Standard-Fenster-Look.

Windows 11 (DWM): Statt eines rahmenlosen Fensters (das eigene Resize-/Snap-/
Drag-Logik braeuchte und Aero Snap verlieren wuerde) faerben wir die NATIVE
Titelleiste ueber die dokumentierten DWM-Attribute in die Markenfarben und
blenden Icon/Titeltext aus. Best-Effort: auf Windows 10 gibt es die
Farb-Attribute nicht, Fehler werden still ignoriert.

Linux/KDE (X11): Server-seitige Dekorationen lassen sich nicht per App faerben
oder teilweise ausblenden → hier geht es andersherum: Fenster rahmenlos +
eigene schmale Leiste (LinuxTitleBar) in Sidebar-Farbe, ohne Icon und ohne
Titeltext, nur mit den drei Fenster-Buttons. Verschieben laeuft ueber
startSystemMove (KWin, echtes natives Move inkl. Snap an Bildschirmkanten),
Groessenaendern ueber einen QSizeGrip unten rechts + Meta+Drag (KWin-Standard).
"""

from __future__ import annotations

import ctypes
import logging
import sys

log = logging.getLogger(__name__)

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20  # Win10 1903+: dunkle Titelleiste
_DWMWA_BORDER_COLOR = 34             # Win11: Fensterrahmen-Farbe
_DWMWA_CAPTION_COLOR = 35            # Win11: Titelleisten-Hintergrund
_DWMWA_TEXT_COLOR = 36               # Win11: Titelleisten-Text

_CAPTION = "#1A1D22"  # SIDEBAR — nahtlos zum App-Header
_BORDER = "#2E3742"   # TRACK — dezenter, abgestimmter Rahmen
_TEXT = "#E8E8EC"     # TEXT


def _colorref(hex_color: str) -> int:
    """"#RRGGBB" → COLORREF (0x00BBGGRR)."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return (b << 16) | (g << 8) | r


def apply_dark_titlebar(widget, hide_caption: bool = False) -> None:
    """Titelleiste + Rahmen des (Top-Level-)Widgets in die Markenfarben faerben.

    hide_caption=True blendet zusaetzlich App-Icon UND Titeltext in der Leiste aus
    (nur die drei Fenster-Buttons bleiben) — Taskleiste und Alt-Tab zeigen den Titel
    weiterhin, weil der Fenstertitel selbst erhalten bleibt.

    Nach show() aufrufen (das HWND muss existieren). Jeder Teilschritt ist einzeln
    Best-Effort — ein nicht unterstuetztes Attribut bricht die anderen nicht."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
    except Exception:
        return
    if not hwnd:
        return
    dwm = ctypes.windll.dwmapi
    for attr, value in (
        (_DWMWA_USE_IMMERSIVE_DARK_MODE, 1),
        (_DWMWA_CAPTION_COLOR, _colorref(_CAPTION)),
        (_DWMWA_TEXT_COLOR, _colorref(_TEXT)),
        (_DWMWA_BORDER_COLOR, _colorref(_BORDER)),
    ):
        try:
            data = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(data), ctypes.sizeof(data))
        except Exception:
            log.debug("DWM-Attribut %d nicht setzbar.", attr, exc_info=True)
    if hide_caption:
        _hide_caption_text_and_icon(hwnd)


class _WTA_OPTIONS(ctypes.Structure):
    _fields_ = [("dwFlags", ctypes.c_uint32), ("dwMask", ctypes.c_uint32)]


_WTA_NONCLIENT = 1
_WTNCA_NODRAWCAPTION = 0x1  # Titeltext nicht zeichnen
_WTNCA_NODRAWICON = 0x2     # App-Icon nicht zeichnen


def _hide_caption_text_and_icon(hwnd: int) -> None:
    """Icon + Titeltext aus der Titelleiste nehmen (dokumentiert: uxtheme,
    SetWindowThemeAttribute/WTA_NONCLIENT) — Fenster-Buttons bleiben unveraendert."""
    try:
        flags = _WTNCA_NODRAWCAPTION | _WTNCA_NODRAWICON
        opts = _WTA_OPTIONS(flags, flags)
        ctypes.windll.uxtheme.SetWindowThemeAttribute(
            hwnd, _WTA_NONCLIENT, ctypes.byref(opts), ctypes.sizeof(opts)
        )
    except Exception:
        log.debug("Titelleisten-Caption nicht ausblendbar.", exc_info=True)


# -- Linux: eigene rahmenlose Titelleiste -------------------------------------------------


def _window_glyph(kind: str, color: str, size: int, dpr: float):
    """Minimal-Glyphen (Linie/Rechteck/Kreuz/Doppel-Rechteck) als HiDPI-Pixmap."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

    px = QPixmap(int(size * dpr), int(size * dpr))
    px.setDevicePixelRatio(dpr)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.2)
    p.setPen(pen)
    m = size * 0.28  # Rand
    if kind == "min":
        y = size * 0.55
        p.drawLine(QRectF(m, y, size - 2 * m, 0).topLeft(), QRectF(m, y, size - 2 * m, 0).topRight())
    elif kind == "max":
        p.drawRect(QRectF(m, m, size - 2 * m, size - 2 * m))
    elif kind == "restore":
        off = size * 0.10
        p.drawRect(QRectF(m + off, m - off + size * 0.06, size - 2 * m - off, size - 2 * m - off))
        p.drawRect(QRectF(m, m + off, size - 2 * m - off, size - 2 * m - off))
    elif kind == "close":
        r = QRectF(m, m, size - 2 * m, size - 2 * m)
        p.drawLine(r.topLeft(), r.bottomRight())
        p.drawLine(r.topRight(), r.bottomLeft())
    p.end()
    return px


class LinuxTitleBar:
    """Erzeugt die rahmenlose Titelleiste + Fensterknoepfe fuer ein QMainWindow.

    Bewusst eine Fabrik statt Widget-Subklasse: haelt PySide6-Importe lazy, damit
    das Modul (wie bisher) ohne Qt importierbar bleibt (z. B. CLI-Modus/Tests).
    build() liefert das fertige QWidget fuer das Layout des Aufrufers.
    """

    HEIGHT = 34
    BTN_W, BTN_H = 40, 26
    ICON = 15

    def __init__(self, window, bg: str, fg: str, hover_bg: str,
                 close_hover: str = "#B4373C"):
        self.window = window
        self.bg, self.fg, self.hover_bg, self.close_hover = bg, fg, hover_bg, close_hover
        self._max_button = None

    def build(self):
        from PySide6.QtCore import QEvent, QObject, Qt
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

        window, outer = self.window, self

        class _Bar(QWidget):
            def mousePressEvent(self, event) -> None:
                if event.button() == Qt.LeftButton and window.windowHandle():
                    window.windowHandle().startSystemMove()  # natives KWin-Move inkl. Snap
                event.accept()

            def mouseDoubleClickEvent(self, event) -> None:
                if event.button() == Qt.LeftButton:
                    outer._toggle_maximized()
                event.accept()

        bar = _Bar()
        bar.setObjectName("linuxTitlebar")
        bar.setFixedHeight(self.HEIGHT)
        bar.setStyleSheet(f"QWidget#linuxTitlebar {{ background: {self.bg}; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(2)
        lay.addStretch(1)  # bewusst KEIN Icon, KEIN Titeltext — nur die Buttons rechts

        dpr = window.devicePixelRatioF()

        def button(kind: str, hover: str, handler) -> QToolButton:
            btn = QToolButton()
            btn.setIcon(QIcon(_window_glyph(kind, self.fg, self.ICON, dpr)))
            btn.setFixedSize(self.BTN_W, self.BTN_H)
            btn.setCursor(Qt.ArrowCursor)
            btn.setStyleSheet(
                f"QToolButton {{ background: transparent; border: none; border-radius: 6px; }}"
                f"QToolButton:hover {{ background: {hover}; }}"
            )
            btn.clicked.connect(handler)
            return btn

        lay.addWidget(button("min", self.hover_bg, window.showMinimized))
        self._max_button = button("max", self.hover_bg, self._toggle_maximized)
        lay.addWidget(self._max_button)
        lay.addWidget(button("close", self.close_hover, window.close))

        # Maximieren kann auch von aussen kommen (Doppelklick, KWin-Shortcut) →
        # Icon ueber den Fensterzustand nachziehen, nicht ueber den Klickpfad.
        class _StateWatcher(QObject):
            def eventFilter(self, _obj, event) -> bool:
                if event.type() == QEvent.WindowStateChange:
                    outer._sync_max_icon()
                return False

        self._watcher = _StateWatcher(bar)
        window.installEventFilter(self._watcher)
        self._dpr = dpr
        return bar

    def _toggle_maximized(self) -> None:
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def _sync_max_icon(self) -> None:
        from PySide6.QtGui import QIcon

        if self._max_button is not None:
            kind = "restore" if self.window.isMaximized() else "max"
            self._max_button.setIcon(QIcon(_window_glyph(kind, self.fg, self.ICON, self._dpr)))
