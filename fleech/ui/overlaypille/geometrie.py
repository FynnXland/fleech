"""Wo die Pille steht und wie gross sie ist: Presets, Ziehen, Einrasten, Monitorwechsel.

Mixin auf `OverlayWindow`: Der Zustand bleibt auf EINEM Widget. Ein eigenes
Objekt haette neue Referenzen in den Qt-Objektgraphen gelegt — genau die
Konstellation, aus der in diesem Projekt die wandernden Abstuerze kamen
(CLAUDE.md, Referenzzyklus-Crash).
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QApplication

from ..state import AppState
from .bausteine import _button_style
from .konstanten import _MARGIN, _SNAP_PX, PILL_HEIGHT, PILL_WIDTH, SIZE_FACTORS

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


class GeometrieMixin:
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

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _snap(self, x: int, y: int) -> tuple[int, int]:
        """Position auf die naechste ausgezeichnete Linie ziehen, wenn sie nah ist.

        Linien: horizontale und vertikale Bildschirmmitte sowie die vier
        Standard-Raender. Ohne das trifft man die Mitte per Hand nie exakt — und
        genau das faellt beim fertig positionierten Overlay sofort auf.
        """
        screen = QApplication.screenAt(QPoint(x, y)) or self.screen()
        if screen is None:
            return x, y
        rand = screen.availableGeometry()
        w, h = self.width(), self.height()
        for kandidat in (rand.left() + _MARGIN,
                         rand.right() - _MARGIN - w,
                         rand.left() + (rand.width() - w) // 2):
            if abs(x - kandidat) <= _SNAP_PX:
                x = kandidat
                break
        for kandidat in (rand.top() + _MARGIN,
                         rand.bottom() - _MARGIN - h,
                         rand.top() + (rand.height() - h) // 2,
                         # Die Default-Hoehe (42 % statt exakt mittig) ist die
                         # Position, aus der die meisten starten — sie soll sich
                         # genauso zurueckfinden lassen.
                         rand.top() + int(rand.height() * 0.42)):
            if abs(y - kandidat) <= _SNAP_PX:
                y = kandidat
                break
        return x, y

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            ziel = event.globalPosition().toPoint() - self._drag_offset
            self.move(*self._snap(ziel.x(), ziel.y()))
            if self._edit_mode:
                self._show_edit_hint()  # Hinweis folgt der Pille

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.settings.x, self.settings.y = self.x(), self.y()
            self.settings.position = "custom"  # frei positioniert
            self._on_geometry_changed()
