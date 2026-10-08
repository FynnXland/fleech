"""Einfuehrung beim Erststart: Sprache, KI, Einrichtung, Mikrofon, Taste, Probediktat.

Zweck: alles klaeren, ohne das das erste Diktat scheitert — und dabei laden, was
Fleech braucht. Die Downloads beginnen, sobald die KI gewaehlt ist, und laufen
im Hintergrund weiter, waehrend man Mikrofon und Taste einstellt; eine Zeile am
unteren Rand zeigt Stand und Restzeit. Alles hier ist auch spaeter in den
Einstellungen aenderbar; aus Einstellungen → Allgemein erneut aufrufbar.

Die Seiten liegen in `ui/onboardingseiten/` (je Seite ein Modul); hier stehen der
Rahmen, die Navigation, das Mikrofon mit seinem Pegel-Stream und die Reaktionen.

Wann gilt die Einfuehrung als erledigt? Bei „Los geht's" und bei „Überspringen" —
beides ist eine Entscheidung. Das X (oder Esc) heisst „spaeter": Wer mitten in
der Einrichtung schliesst, bekommt sie beim naechsten Start wieder, statt mit
einem halb eingerichteten Fleech allein zu bleiben.

Qt-Fallen beachtet: keine Lambdas mit `self`-Fang in Kind-Widgets (Referenzzyklus →
Access Violations), Mikrofon-Pegel-Stream defensiv gekapselt und beim Seitenwechsel/
Schliessen IMMER gestoppt.
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from .onboardingseiten import modi, probediktat, taste, verlauf, willkommen
from .onboardingseiten.bausteine import NOTIZ_STIL, auswahl, notiz, text, titel
from .theme import ACCENT, BORDER_HAIRLINE, CARD, MUTED, TEXT, style_button

log = logging.getLogger(__name__)


class OnboardingDialog(QDialog):
    """settings: UserSettings (live — Aenderungen greifen sofort ueber on_changed).
    list_microphones: Callable() -> list[str].
    on_changed: Callable(section) — dieselbe Nahtstelle wie im Settings-Panel
        ("microphone", "recording", "hotkeys", "general", "ki").
    einrichtung: Callable() -> (endpoints, stt_model, base_url) — der Plan fuer die
        Downloads, erst NACH der KI-Wahl gefragt. Alternativ fest ueber
        endpoints/stt_model/llm_base_url (Tests).
    audio: False = kein Pegel-Stream; netz: False = keine Abrufe (Tests/Render).
    """

    def __init__(self, settings, list_microphones, on_changed=None, parent=None,
                 audio: bool = True, endpoints=None, stt_model: str = "",
                 llm_base_url: str = "http://127.0.0.1:11434", on_ready=None,
                 einrichtung=None, hotkey_capture_guard=None, netz: bool | None = None,
                 cache_ordner=None):
        super().__init__(parent)
        self.setWindowTitle("Willkommen bei Fleech")
        self.setMinimumSize(600, 560)
        self.setStyleSheet(
            f"QDialog {{ background: {CARD}; }}"
            f"QComboBox {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
            f"  padding: 6px 10px; }}"
            f"QLineEdit {{ background: rgba(255,255,255,0.04); color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
            f"  padding: 6px 10px; }}"
            f"QRadioButton {{ color: {TEXT}; font-size: 10pt; spacing: 8px; }}"
        )
        self.settings = settings
        self._on_changed = on_changed
        self._audio_allowed = audio
        self._netz = audio if netz is None else netz
        self._level_stream = None
        self._level = 0.0
        if einrichtung is None and (endpoints or stt_model):
            plan = (list(endpoints or []), stt_model, llm_base_url)
            einrichtung = lambda: plan          # noqa: E731 — faengt nur Daten
        self._einrichtung = einrichtung
        self._setup_page = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 18)
        outer.setSpacing(14)

        self._steps = QLabel("")
        self._steps.setStyleSheet(NOTIZ_STIL)
        outer.addWidget(self._steps)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)
        # Seiten-Index nach Namen: Einschieben oder Ueberspringen einer Seite darf
        # die Logik nicht verschieben (der Pegel haengt an "microphone").
        self._pages = {}
        self._add_page("welcome", willkommen.build(self))
        self._add_ki_page(cache_ordner, llm_base_url)
        self._add_setup_page(on_ready)
        self._add_page("microphone", self._page_microphone(list_microphones))
        self._add_page("controls", taste.build(self, hotkey_capture_guard))
        self._add_page("modes", modi.build(self))
        self._add_page("verlauf", verlauf.build(self))
        self._add_page("finish", probediktat.build(self))

        # Download-Stand auf allen Seiten nach der Einrichtung.
        self._download_zeile = notiz("")
        self._download_zeile.hide()
        outer.addWidget(self._download_zeile)

        nav = QHBoxLayout()
        self._back_btn = style_button(QPushButton("Zurück"))
        self._next_btn = style_button(QPushButton("Weiter"), "primary")
        self._skip_btn = QPushButton("Überspringen")
        self._skip_btn.setToolTip("Einführung beenden — sie kommt nicht wieder von "
                                  "selbst. Erneut aufrufbar unter Einstellungen → "
                                  "Allgemein.")
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

    def _add_page(self, name: str, widget: QWidget) -> None:
        self._pages[name] = self._stack.count()
        self._stack.addWidget(widget)

    def _add_ki_page(self, cache_ordner, base_url) -> None:
        from .onboardingseiten.ki import KiSeite

        if cache_ordner is None and self._netz:
            from ..platformpaths import user_data_dir

            cache_ordner = user_data_dir()
        self._ki_seite = KiSeite(self.settings, parent=self, netz=self._netz,
                                 cache_ordner=cache_ordner,
                                 ollama_adresse=base_url or "http://127.0.0.1:11434")
        self._add_page("ki", self._ki_seite)

    def _add_setup_page(self, on_ready) -> None:
        """Einrichtungs-Seite — nur mit Modell-Kontext (nicht in Tests/Render).

        Sie startet NICHT von selbst: Was zu laden ist, steht erst nach der
        KI-Wahl fest (`_plane_einrichtung`). Ist dann alles da, wird sie
        uebersprungen — niemand soll eine Seite mit drei Haken durchklicken.
        """
        if self._einrichtung is None:
            return
        try:
            from .setuppage import SetupPage

            endpoints, stt_model, base_url = self._einrichtung()
            self._setup_page = SetupPage(endpoints, stt_model, base_url,
                                         on_ready=on_ready, parent=self,
                                         autostart=False)
            self._setup_page.stand.connect(self._on_download_stand)
            self._add_page("setup", self._setup_page)
        except Exception:
            log.exception("Einrichtungs-Seite konnte nicht aufgebaut werden.")
            self._setup_page = None

    def _page_microphone(self, list_microphones) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        lay.addWidget(titel("Mikrofon"))
        lay.addWidget(text("Welches Mikrofon soll Fleech verwenden?"))
        combo = auswahl()
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
        lay.addWidget(notiz("Sprich einen Satz — der Balken soll sich deutlich "
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
        self._level_hint = notiz("")
        lay.addWidget(self._level_hint)
        lay.addStretch(1)
        return page

    # -- Navigation ------------------------------------------------------------------

    def _uebersprungen(self, index: int) -> bool:
        """Die Einrichtung entfaellt, wenn nichts zu laden ist und nichts laeuft."""
        if index == self._pages.get("setup") and self._setup_page is not None:
            return self._setup_page.alles_bereit() and not self._setup_page.laeuft()
        return False

    def _nachbar(self, index: int, richtung: int) -> int:
        i = index + richtung
        while 0 <= i < self._stack.count() and self._uebersprungen(i):
            i += richtung
        return i

    def _go_next(self) -> None:
        index = self._stack.currentIndex()
        if index == self._pages.get("ki"):
            fehler = self._ki_seite.fehler()
            if fehler:
                self._ki_seite.zeige_fehler(fehler)
                return
            if self._ki_seite.commit():
                self.settings.save()
                if self._on_changed is not None:
                    self._on_changed("ki")
            self._plane_einrichtung()
        ziel = self._nachbar(index, +1)
        if ziel >= self._stack.count():
            self._finish()
            return
        self._stack.setCurrentIndex(ziel)

    def _go_back(self) -> None:
        self._stack.setCurrentIndex(max(0, self._nachbar(self._stack.currentIndex(), -1)))

    def _plane_einrichtung(self) -> None:
        """Nach der KI-Wahl: Plan neu erheben und die Downloads anwerfen."""
        if self._setup_page is None or self._einrichtung is None:
            return
        try:
            self._setup_page.neu_planen(*self._einrichtung())
            self._setup_page.starte_wenn_moeglich()
        except Exception:
            log.exception("Einrichtung liess sich nicht planen.")

    def _on_page_changed(self, index: int) -> None:
        sichtbar = [i for i in range(self._stack.count()) if not self._uebersprungen(i)]
        nummer = sichtbar.index(index) + 1 if index in sichtbar else index + 1
        letzte = self._nachbar(index, +1) >= self._stack.count()
        self._steps.setText(f"Schritt {nummer} von {len(sichtbar)}")
        self._back_btn.setEnabled(index > 0)
        self._next_btn.setText("Los geht's" if letzte else "Weiter")
        self._skip_btn.setVisible(not letzte)
        self._download_zeile.setVisible(
            bool(self._download_zeile.text()) and index != self._pages.get("setup"))
        if index == self._pages.get("microphone"):
            self._start_level_stream()
        else:
            self._stop_level_stream()
        if index == self._pages.get("controls"):
            taste.beschrifte(self)
        if index == self._pages.get("finish"):
            probediktat.aktualisiere(self, self.einrichtung_laeuft())

    # -- Abschluss -------------------------------------------------------------------

    def einrichtung_laeuft(self) -> bool:
        return self._setup_page is not None and self._setup_page.laeuft()

    def zeige_einrichtung(self) -> None:
        """Erneut geoeffnet, waehrend noch geladen wird: gleich den Stand zeigen."""
        if "setup" in self._pages:
            self._stack.setCurrentIndex(self._pages["setup"])

    def _finish(self) -> None:
        # „Los geht's" und „Überspringen": nie wieder automatisch zeigen. Laufende
        # Downloads laufen weiter — die App waermt danach selbst auf (on_ready).
        self.settings.general.onboarding_done = True
        self.settings.save()
        self.accept()

    def _stop_setup(self) -> None:
        """Laufende Einrichtung nach dem aktuellen Schritt anhalten.

        Der Download selbst wird beim naechsten Start fortgesetzt — Ollama und
        HuggingFace nehmen angefangene Teile wieder auf.
        """
        if self._setup_page is not None:
            try:
                self._setup_page.stop()
            except Exception:
                log.debug("Einrichtung liess sich nicht stoppen.", exc_info=True)

    def closeEvent(self, event) -> None:
        # X = „spaeter": Flag bleibt, wie es war — beim Erststart kommt die
        # Einfuehrung beim naechsten Start wieder.
        self._stop_level_stream()
        self._stop_setup()
        super().closeEvent(event)

    def reject(self) -> None:
        self._stop_level_stream()
        self._stop_setup()
        super().reject()

    def accept(self) -> None:
        self._stop_level_stream()
        super().accept()

    # -- Reaktionen --------------------------------------------------------------------

    def _trigger_word(self) -> str:
        word = (self.settings.output.trigger_word or "").strip()
        return word or "Kimono"

    def _melde(self, section: str) -> None:
        self.settings.save()
        if self._on_changed is not None:
            self._on_changed(section)

    def _on_sprache_gewaehlt(self, _index: int) -> None:
        self.settings.general.language = str(self._sprache_box.currentData() or "de")
        self._melde("general")

    def _on_taste_gewaehlt(self, spec) -> None:
        if spec is None:
            # Ohne Diktat-Taste ginge nichts — Loeschen heisst hier: alte behalten.
            from ..hotkey import HotkeySpec

            self._taste_feld._spec = HotkeySpec.parse(self.settings.recording.hotkey
                                                      or "f9")
            self._taste_feld._refresh()
            return
        self.settings.recording.hotkey = spec.serialize()
        taste.beschrifte(self)
        self._melde("hotkeys")

    def _on_verlauf_toggled(self, an: bool) -> None:
        self.settings.general.save_history = bool(an)
        if self._on_changed is not None:
            self._on_changed("general")

    def _on_probe_text(self) -> None:
        probediktat.angekommen(self)

    def _on_download_stand(self, stand: str) -> None:
        self._download_zeile.setText(f"Im Hintergrund — {stand}")
        self._download_zeile.setVisible(
            self._stack.currentIndex() != self._pages.get("setup"))

    def _on_microphone_selected(self, _index: int) -> None:
        self.settings.recording.microphone = self._mic_combo.currentData()
        self._melde("microphone")
        # Pegel-Stream auf das neue Geraet umziehen.
        self._stop_level_stream()
        self._start_level_stream()

    def _on_mode_toggled(self, checked: bool) -> None:
        if not checked:
            return  # nur das NEU gewaehlte Radio schreibt, nicht das abgewaehlte
        if self._toggle_radio.isChecked():
            mode = "toggle"
        elif self._nudge_radio.isChecked():
            mode = "nudge"
        else:
            mode = "hold"
        self.settings.recording.mode = mode
        self._melde("recording")

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
