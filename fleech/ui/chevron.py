"""Chevron-Pfeile (^ / v) fuer Comboboxen und Spinboxen.

Statt der CSS-Border-Dreiecke (rendern je nach System/DPI als „Rechteck") zeichnen
wir schmale Chevron-Striche per QPainter, speichern sie als kleine PNGs und binden
sie ueber QSS `image: url(...)` ein — ueberall gleich, unabhaengig vom Windows-Theme.

apply_chevrons(qss) ersetzt die Platzhalter __CHEV_DOWN__, __CHEV_UP__ (normal) und
__CHEV_DOWN_HL__, __CHEV_UP_HL__ (Hover, Akzentfarbe) durch die Dateipfade. Lazy: die
Pixmaps werden beim ersten Aufruf erzeugt (QApplication muss existieren).
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

log = logging.getLogger(__name__)

_MUTED = "#9AA0AA"
_ACCENT = "#35C0D8"
_CACHE: dict[str, str] | None = None


def _chevron_pixmap(direction: str, color: str, w: int = 24, h: int = 16) -> QPixmap:
    """Ein einfacher, stroked Chevron („v" bzw. „^") — kein gefuelltes Dreieck.

    Grosszuegig gerendert und per QSS heruntergesizt → auch auf HiDPI scharf."""
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    pad = w * 0.24
    top, bot = h * 0.34, h * 0.66
    if direction == "down":
        p.drawPolyline([QPointF(pad, top), QPointF(w / 2, bot), QPointF(w - pad, top)])
    else:  # up
        p.drawPolyline([QPointF(pad, bot), QPointF(w / 2, top), QPointF(w - pad, bot)])
    p.end()
    return pm


def _check_pixmap(color: str, size: int = 20) -> QPixmap:
    """Haekchen fuer Checkbox-Indikatoren (dunkler Strich auf Akzent-Fuellung) —
    QSS kann den Haken nicht selbst zeichnen, nur eine Flaeche fuellen."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 2.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline([QPointF(size * 0.24, size * 0.54),
                    QPointF(size * 0.43, size * 0.72),
                    QPointF(size * 0.78, size * 0.30)])
    p.end()
    return pm


def _paths() -> dict[str, str]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    out: dict[str, str] = {}
    try:
        target = Path(tempfile.gettempdir()) / "fleech-chevrons"
        target.mkdir(parents=True, exist_ok=True)
        specs = {
            "CHEV_DOWN": ("down", _MUTED), "CHEV_UP": ("up", _MUTED),
            "CHEV_DOWN_HL": ("down", _ACCENT), "CHEV_UP_HL": ("up", _ACCENT),
        }
        for key, (direction, color) in specs.items():
            f = target / f"{key.lower()}.png"
            _chevron_pixmap(direction, color).save(str(f), "PNG")
            out[key] = f.as_posix()
        f = target / "chev_check.png"
        _check_pixmap("#0E2126").save(str(f), "PNG")  # dunkler Haken auf Akzent
        out["CHEV_CHECK"] = f.as_posix()
    except Exception:
        log.debug("Chevron-Icons konnten nicht erzeugt werden.", exc_info=True)
    _CACHE = out
    return out


def apply_chevrons(qss: str) -> str:
    """__CHEV_*__-Platzhalter im Stylesheet durch die Icon-Pfade ersetzen."""
    for key, path in _paths().items():
        qss = qss.replace(f"__{key}__", path)
    return qss
