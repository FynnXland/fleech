"""Einführung beim Erststart (W3-14): fünf Schritte, jederzeit abbrechbar.

Zweck: Die drei Dinge klaeren, ohne die das erste Diktat scheitert (Mikrofon,
Bedienmodus/Hotkey, was die Modi bedeuten) — mehr nicht. Alles hier ist auch
spaeter in den Einstellungen aenderbar; der Wizard ist eine Abkuerzung, kein
zweiter Einstellungs-Dialog. Aus den Einstellungen (Allgemein) erneut aufrufbar.

Qt-Fallen beachtet: keine Lambdas mit `self`-Fang in Kind-Widgets (Referenzzyklus →
Access Violations), Mikrofon-Pegel-Stream defensiv gekapselt und beim Seitenwechsel/
Schliessen IMMER gestoppt.
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QRadioButton, QStackedWidget, QVBoxLayout, QWidget,
)

from .chevron import apply_chevrons
from .main_window import (
    ACCENT, BORDER_HAIRLINE, CARD, MUTED, TEXT, button_qss, style_button,
)

log = logging.getLogger(__name__)

_TITLE_STYLE = f"color: {TEXT}; font-size: 14pt; font-weight: 600;"
_BODY_STYLE = f"color: {TEXT}; font-size: 10pt;"
_MUTED_STYLE = f"color: {MUTED}; font-size: 9pt;"


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(_TITLE_STYLE)
    label.setWordWrap(True)
    return label


def _body(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(_BODY_STYLE)
    label.setWordWrap(True)
    return label


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(_MUTED_STYLE)
    label.setWordWrap(True)
    return label


class OnboardingDialog(QDialog):
    """Fuenf Seiten: Willkommen → Mikrofon → Bedienung → Modi & Safe-Word → Probediktat.

    settings: UserSettings (live — Aenderungen greifen sofort ueber on_changed).
    list_microphones: Callable() -> list[str].
    on_changed: Callable(section) — dieselbe Nahtstelle wie im Settings-Panel
    ("microphone", "recording"), damit Recorder/Hotkeys sofort nachziehen.
    audio: False = kein Pegel-Stream (Tests/Render).
    """

    def __init__(self, settings, list_microphones, on_changed=None, parent=None,
                 audio: bool = True, endpoints=None, stt_model: str = "",
                 llm_base_url: str = "http://127.0.0.1:11434", on_ready=None):
        super().__init__(parent)
        self.setWindowTitle("Willkommen bei Fleech")
        self.setMinimumSize(560, 460)
        self.setStyleSheet(
            f"QDialog {{ background: {CARD}; }}"
            f"QComboBox {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
            f"  padding: 6px 10px; }}"
            f"QRadioButton {{ color: {TEXT}; font-size: 10pt; spacing: 8px; }}"
        )
        self.settings = settings
        self._on_changed = on_changed
        self._audio_allowed = audio
        self._level_stream = None
        self._level = 0.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 18)
        outer.setSpacing(14)

        self._steps = QLabel("")
        self._steps.setStyleSheet(_MUTED_STYLE)
        outer.addWidget(self._steps)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)
        # Seiten-Index nach Namen, damit das Einschieben einer Seite nicht die
        # Pegel-Logik verschiebt (die haengt an "microphone").
        self._pages = {}
        self._add_page("welcome", self._page_welcome())
        setup = self._page_setup(endpoints, stt_model, llm_base_url, on_ready)
        if setup is not None:
            self._add_page("setup", setup)
        self._add_page("microphone", self._page_microphone(list_microphones))
        self._add_page("controls", self._page_controls())
        self._add_page("modes", self._page_modes())
        self._add_page("finish", self._page_finish())

        nav = QHBoxLayout()
        self._back_btn = style_button(QPushButton("Zurück"))
        self._next_btn = style_button(QPushButton("Weiter"), "primary")
        self._skip_btn = QPushButton("Überspringen")
        self._skip_btn.setStyleSheet(
            f"QPushButton {{ color: {MUTED}; background: transparent; border: none;"
            f"  font-size: 9pt; }} QPushButton:hover {{ color: {TEXT}; }}"
        )
        self._skip_btn.setCursor(Qt.PointingHandCursor)
        nav.addWidget(self._skip_btn)
        nav.addStretch(1)
        nav.addWidget(self._back_btn)
        nav.addWidget(self._next_btn)
        outer.addLayout(nav)

        self._back_btn.clicked.connect(self._go_back)
        self._next_btn.clicked.connect(self._go_next)
        self._skip_btn.clicked.connect(self._finish)
        self._stack.currentChanged.connect(self._on_page_changed)

        self._level_timer = QTimer(self)
        self._level_timer.setInterval(50)
        self._level_timer.timeout.connect(self._update_level_bar)

        self._on_page_changed(0)

    # -- Seiten -------------------------------------------------------------------

    def _page_welcome(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        lay.addWidget(_title("Willkommen bei Fleech"))
        lay.addWidget(_body(
            "Fleech schreibt, was du sprichst — in das Feld, in dem dein Cursor "
            "steht. Alles läuft auf diesem Rechner: Mikrofon, Erkennung und "
            "KI-Bereinigung verlassen ihn nicht."
        ))
        lay.addWidget(_body(
            "Diese Einführung klärt in vier kurzen Schritten das Mikrofon, die "
            "Bedienung und die Modi. Alles davon findest du später auch in den "
            "Einstellungen wieder."
        ))
        lay.addWidget(_muted("Dauer: etwa eine Minute."))
        lay.addStretch(1)
        return page

    def _page_microphone(self, list_microphones) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        lay.addWidget(_title("Mikrofon"))
        lay.addWidget(_body("Welches Mikrofon soll Fleech verwenden?"))
        combo = QComboBox()
        combo.setStyleSheet(apply_chevrons(combo.styleSheet() or ""))
        combo.addItem("Systemstandard", None)
        try:
            names = list_microphones() or []
        except Exception:
            log.exception("Mikrofonliste nicht abfragbar.")
            names = []
        current_index = 0
        for i, name in enumerate(names, start=1):
            combo.addItem(name, name)
            if name == self.settings.recording.microphone:
                current_index = i
        combo.setCurrentIndex(current_index)
        combo.currentIndexChanged.connect(self._on_microphone_selected)
        self._mic_combo = combo
        lay.addWidget(combo)

        lay.addSpacing(6)
        lay.addWidget(_muted("Sprich einen Satz — der Balken soll sich deutlich "
                             "bewegen, ohne dauerhaft am Anschlag zu sein."))
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(10)
        bar.setStyleSheet(
            f"QProgressBar {{ background: rgba(255,255,255,0.07); border: none;"
            f"  border-radius: 5px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}"
        )
        self._level_bar = bar
        lay.addWidget(bar)
        self._level_hint = _muted("")
        lay.addWidget(self._level_hint)
        lay.addStretch(1)
        return page

    def _page_controls(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        lay.addWidget(_title("Bedienung"))
        hotkey = (self.settings.recording.hotkey or "F9").upper()
        lay.addWidget(_body(
            f"Aufgenommen wird über die Taste {hotkey} — auf zwei Arten:"
        ))
        self._hold_radio = QRadioButton(
            f"Halten:  {hotkey} gedrückt halten = aufnehmen, loslassen = fertig"
        )
        self._toggle_radio = QRadioButton(
            f"Umschalten:  {hotkey} einmal drücken = Start, nochmal = fertig"
        )
        if self.settings.recording.mode == "toggle":
            self._toggle_radio.setChecked(True)
        else:
            self._hold_radio.setChecked(True)
        self._hold_radio.toggled.connect(self._on_mode_toggled)
        lay.addWidget(self._hold_radio)
        lay.addWidget(self._toggle_radio)
        lay.addSpacing(6)
        lay.addWidget(_muted(
            "Während der Aufnahme erscheint eine kleine Pille am Bildschirmrand: "
            "x bricht ab, der Haken fügt ein. Taste und weitere Hotkeys lassen sich "
            "unter Einstellungen → Aufnahme ändern."
        ))
        lay.addStretch(1)
        return page

    def _page_modes(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(10)
        lay.addWidget(_title("Die vier Modi"))
        rows = [
            ("Diktat", "einfach sprechen — Füllwörter und Versprecher räumt die "
                       "lokale KI weg, deine Worte bleiben deine Worte."),
            ("Befehle", None),  # Text unten dynamisch mit Safe-Word
            ("Formeln", "Strg+Alt+M während der Aufnahme (oder „Formel … Formel "
                        "Ende“): gesprochene Mathematik wird zu LaTeX."),
            ("KI-Prompting", "Strg+Alt+P: dein Diktat wird zu einem strukturierten "
                             "Prompt für eine KI ausformuliert."),
        ]
        trigger = self._trigger_word()
        for name, text in rows:
            if text is None:
                text = (f"sprich „{trigger}“ mitten im Diktat, dann die Anweisung — "
                        f"z. B. „{trigger}, mach den letzten Satz formeller.“")
            row = QLabel(f"<b style='color:{ACCENT};'>{name}</b>"
                         f"<span style='color:{TEXT};'> — {text}</span>")
            row.setWordWrap(True)
            row.setTextFormat(Qt.RichText)
            row.setStyleSheet("font-size: 10pt;")
            lay.addWidget(row)
        lay.addSpacing(6)
        lay.addWidget(_muted(
            "Für einzelne Apps lässt sich das Verhalten über Profile anpassen "
            "(Tab „Profile“) — z. B. weniger Eingriff im Code-Editor."
        ))
        lay.addStretch(1)
        return page

    def _page_finish(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        lay.addWidget(_title("Probediktat"))
        hotkey = (self.settings.recording.hotkey or "F9").upper()
        mode_hint = ("halte sie gedrückt, während du sprichst"
                     if self.settings.recording.mode != "toggle"
                     else "drücke sie einmal, sprich, und drücke sie erneut")
        lay.addWidget(_body(
            f"Klicke nach dem Abschluss in ein beliebiges Textfeld, drücke "
            f"{hotkey} — {mode_hint}. Zum Beispiel:"
        ))
        sample = QLabel("„Das ist mein erstes Diktat mit Fleech, äh, mal sehen "
                        "was die Bereinigung daraus macht.“")
        sample.setWordWrap(True)
        sample.setStyleSheet(
            f"color: {TEXT}; font-size: 10.5pt; font-style: italic;"
            f" background: rgba(255,255,255,0.05); border-radius: 8px; padding: 10px;"
        )
        lay.addWidget(sample)
        lay.addWidget(_muted(
            "Das „äh“ sollte im Ergebnis fehlen — der Rest bleibt wortgetreu. "
            "Diese Einführung findest du jederzeit wieder unter "
            "Einstellungen → Allgemein."
        ))
        lay.addStretch(1)
        return page

    # -- Interaktion ---------------------------------------------------------------

    def _trigger_word(self) -> str:
        word = (self.settings.output.trigger_word or "").strip()
        return word or "Kimono"

    def _on_microphone_selected(self, _index: int) -> None:
        self.settings.recording.microphone = self._mic_combo.currentData()
        self.settings.save()
        if self._on_changed is not None:
            self._on_changed("microphone")
        # Pegel-Stream auf das neue Geraet umziehen.
        self._stop_level_stream()
        self._start_level_stream()

    def _on_mode_toggled(self, _checked: bool) -> None:
        self.settings.recording.mode = ("hold" if self._hold_radio.isChecked()
                                        else "toggle")
        self.settings.save()
        if self._on_changed is not None:
            self._on_changed("recording")

    def _go_next(self) -> None:
        index = self._stack.currentIndex()
        if index >= self._stack.count() - 1:
            self._finish()
            return
        self._stack.setCurrentIndex(index + 1)

    def _go_back(self) -> None:
        self._stack.setCurrentIndex(max(0, self._stack.currentIndex() - 1))

    def _on_page_changed(self, index: int) -> None:
        total = self._stack.count()
        self._steps.setText(f"Schritt {index + 1} von {total}")
        self._back_btn.setEnabled(index > 0)
        self._next_btn.setText("Los geht's" if index == total - 1 else "Weiter")
        self._skip_btn.setVisible(index < total - 1)
        if index == self._pages.get("microphone"):
            self._start_level_stream()
        else:
            self._stop_level_stream()

    def _finish(self) -> None:
        # Egal ob durchlaufen oder uebersprungen: nie wieder automatisch zeigen.
        self.settings.general.onboarding_done = True
        self.settings.save()
        self.accept()

    def _stop_setup(self) -> None:
        """Laufende Einrichtung nach dem aktuellen Schritt anhalten.

        Der Download selbst laeuft weiter bzw. wird beim naechsten Start
        fortgesetzt — nur die Meldungen an ein geschlossenes Fenster hoeren auf.
        """
        page = getattr(self, "_setup_page", None)
        if page is not None:
            try:
                page.stop()
            except Exception:
                log.debug("Einrichtung liess sich nicht stoppen.", exc_info=True)

    def closeEvent(self, event) -> None:
        self._stop_level_stream()
        self._stop_setup()
        # X = Ueberspringen: wer die Einfuehrung wegklickt, will sie beim naechsten
        # Start nicht schon wieder sehen.
        self.settings.general.onboarding_done = True
        self.settings.save()
        super().closeEvent(event)

    def reject(self) -> None:
        self._stop_level_stream()
        self._stop_setup()
        self.settings.general.onboarding_done = True
        self.settings.save()
        super().reject()

    def accept(self) -> None:
        self._stop_level_stream()
        self._stop_setup()
        super().accept()

    # -- Mikrofon-Pegel ----------------------------------------------------------------

    def _start_level_stream(self) -> None:
        """Kleiner Eingabe-Stream nur fuer den Pegelbalken. Best-Effort: schlaegt er
        fehl (Geraet belegt/fehlt), zeigt die Seite das an, statt zu crashen."""
        if not self._audio_allowed or self._level_stream is not None:
            return
        try:
            import sounddevice as sd

            from ..audio import resolve_input_device

            dialog = self

            def _callback(indata, _frames, _time, _status):
                # Audio-Thread: nur den Wert ablegen, kein Qt von hier.
                dialog._level = float(np.sqrt(np.mean(np.square(indata))))

            self._level_stream = sd.InputStream(
                device=resolve_input_device(self.settings.recording.microphone),
                channels=1, samplerate=16000, callback=_callback,
            )
            self._level_stream.start()
            self._level_hint.setText("")
            self._level_timer.start()
        except Exception as exc:
            log.warning("Pegel-Anzeige nicht verfuegbar (%s).", exc)
            self._level_stream = None
            self._level_hint.setText(
                "Pegel-Anzeige nicht verfügbar — das Mikrofon lässt sich trotzdem "
                "auswählen und beim Probediktat testen."
            )

    def _stop_level_stream(self) -> None:
        self._level_timer.stop()
        stream = self._level_stream
        self._level_stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.debug("Pegel-Stream liess sich nicht sauber stoppen.", exc_info=True)
        if hasattr(self, "_level_bar"):
            self._level_bar.setValue(0)

    def _update_level_bar(self) -> None:
        # RMS von Sprache liegt grob bei 0.02–0.2 — auf 0–100 spreizen.
        self._level_bar.setValue(int(min(1.0, self._level * 6.0) * 100))

    # -- Seiten-Verwaltung ------------------------------------------------------------

    def _add_page(self, name: str, widget: QWidget) -> None:
        self._pages[name] = self._stack.count()
        self._stack.addWidget(widget)

    def _page_setup(self, endpoints, stt_model, base_url, on_ready):
        """Einrichtungs-Seite — nur, wenn wirklich etwas zu tun ist.

        Wer die Einfuehrung aus den Einstellungen erneut oeffnet und ein fertig
        eingerichtetes Fleech hat, soll keine Seite mit drei Haken durchklicken.
        """
        if not endpoints and not stt_model:
            return None            # Aufrufer ohne Modell-Kontext (Tests/Render)
        try:
            from ..provisioning import build_steps

            from .setuppage import SetupPage

            if all(s.state == "done"
                   for s in build_steps(endpoints, stt_model, base_url)):
                return None
            self._setup_page = SetupPage(
                endpoints, stt_model, base_url, on_ready=on_ready, parent=self,
            )
            return self._setup_page
        except Exception:
            log.exception("Einrichtungs-Seite konnte nicht aufgebaut werden.")
            return None
