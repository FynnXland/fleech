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

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QWidget

from ..usersettings import OverlaySettings
from .overlaypille.bausteine import (  # noqa: F401  (WaveformWidget: Tests holen es hier)
    TranscriptCaption, WaveformWidget, _round_button, _StatusDot,
)
from .overlaypille.einblendungen import EinblendungenMixin
from .overlaypille.geometrie import GeometrieMixin, preset_position  # noqa: F401
from .overlaypille.konstanten import (  # noqa: F401  (Farben/Masse: Tests + Settings-UI)
    _ACCENT, _BAR_DIM, _BG, _BG_ARMED, _BG_PAUSED, _BG_PROMPT, _PROMPT_ACCENT,
    OVERLAY_PRESETS, PILL_HEIGHT, PILL_WIDTH, SIZE_FACTORS,
)
from .overlaypille.zustand import ZustandMixin
from .state import AppState  # noqa: F401  (Teilgebiete und Aufrufer holen es hier)

log = logging.getLogger(__name__)



class OverlayWindow(GeometrieMixin, EinblendungenMixin, ZustandMixin, QWidget):
    """Das Pillen-Fenster selbst: Aufbau, Hintergrund zeichnen, Qt-Ereignisse.

    Die drei Teilgebiete liegen in `ui/overlaypille/` — dort steht auch, warum sie
    als Mixins angebunden sind und nicht als eigene Objekte.
    """

    cancel_requested = Signal()   # ✕ — verwerfen ohne Verarbeitung
    finish_requested = Signal()   # ✓ — beenden und einfuegen
    profile_cycle_requested = Signal()  # Punkt geklickt — naechstes Profil
    pause_requested = Signal()    # ⏸ — Aufnahme anhalten/fortsetzen

    # Wie lange der Profilname unter der Pille stehen bleibt. Kuerzer als die
    # Transkript-Blase (4,2 s): Das Profil ist eine Bestaetigung dessen, was man
    # gerade selbst getan hat — man liest es im Vorbeigehen, nicht zu Ende.
    PROFIL_MS = 1800

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
        # Profil-Anzeige: dieselbe Blase wie die Live-Transkription, nur
        # unterhalb statt oberhalb. Vorher war das eine eigene Klasse mit eigener
        # Positionsrechnung — deren Rand-Korrektur schob die Kapsel bei tief
        # stehender Pille AUF die Pille (gemeldet). Eine Komponente, ein Abstand,
        # ein Aussehen; die Seite ist der einzige Unterschied.
        self._profile_caption = TranscriptCaption()
        self._caption_is_live = False  # zeigt die Blase gerade die Live-Vorschau?
        self._caption_is_status = False  # … oder einen Fortschritts-Hinweis?
        # Rohtranskript, solange die Bereinigung laeuft. Steht es, wird die
        # Statuszeile UNTER den Text gehaengt statt ihn zu ersetzen — sonst waere
        # der Gewinn wieder weg, kaum dass er da war.
        self._roh_vorschau = ""
        # Freihand: "aus" | "lauscht" | "aufnahme". Muss SICHTBAR sein — wer nicht
        # erkennen kann, ob mitgehoert wird, kann dem Modus nicht vertrauen.
        self._freihand = "aus"
        self._command_armed = False    # Signalwort in der Live-Vorschau erkannt
        self._prompt_latched = False   # KI-Prompting-Latch aktiv (exklusiv zu Mathe)
        self._paused = False           # Aufnahme angehalten (Pause-Knopf)
        # Modus-Zeile (Fokus/Eingriff/Modell). Nur noch Zustand, keine Einblendung
        # mehr — siehe set_mode_line.
        self._mode_line = ""

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
        # Ohne Tooltip (siehe set_paused): die Blase landete unter der Pille,
        # auf demselben Platz wie die Profil-Kapsel.
        self._pause_btn = _round_button("pause", "")
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
        self._math_dot.clicked.connect(self.profile_cycle_requested.emit)

        # Erklaerende Tooltips — beim laengeren Hover eingeblendet, UNTERHALB der Pille
        # (oben liegt die Live-Transkription). Der Event-Filter faengt das ToolTip-
        # Ereignis ab und positioniert den Hinweis mittig unter der Pille.
        self._cancel_btn.setToolTip("Abbrechen — nichts einfügen")
        self._finish_btn.setToolTip("Fertig — Text einfügen")
        self._dot_tooltip_base = (
            "Zeigt das Profil, das für das nächste Diktat gilt — es bestimmt, "
            "WAS aus dem Diktat wird: normaler Text, eine E-Mail oder ein "
            "KI-Prompt. Ein Klick wechselt reihum durch deine Profile, aber nur "
            "während einer laufenden Aufnahme. Vorher: Profil-Hotkey oder "
            "Profilseite."
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




    # -- Einstellungen (auch live aus dem Settings-Fenster) ----------------------------







    # -- Positions-Presets, Reset, Bearbeiten-Modus ------------------------------------


    # -- Monitor des Mauszeigers folgen ---------------------------------------------











    ROH_MAX = 240








    LIVE_WORDS = 18  # nur die zuletzt erkannten Woerter tragen (Rest elidiert die Blase)



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



    # -- Statusanzeige -------------------------------------------------------------------









    # -- Verschieben per Maus + Persistenz -------------------------------------------------
