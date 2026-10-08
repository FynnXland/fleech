"""Einrichtungs-Seite der Einfuehrung: zeigt, was Fleech gerade selbst besorgt.

Der Kaltstart holt rund 5 GB (Ollama-Dienst, Sprachmodell, Erkennungsmodell). Das
darf nicht in einem Terminal passieren und schon gar nicht unsichtbar — hier laeuft
es im Hintergrund-Thread, waehrend die Seite im Design-System darstellt, welcher
Schritt gerade dran ist und wie weit er ist.

Qt-Regeln, die hier zaehlen:
- Der Worker ruft NIE Qt an. Er meldet ueber `_Bridge`-Signale (Thread-Wechsel).
- Keine Lambdas, die `self` fangen und in Kind-Widgets liegen (Referenzzyklus →
  Access Violation). Verbunden werden nur gebundene Methoden.
- Karten per `objectName` scopen, sonst kaskadiert das QFrame-QSS auf jedes Label.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from ..provisioning import SetupRunner, build_steps
from .theme import ACCENT, BORDER_HAIRLINE, MUTED, TEXT, style_button

log = logging.getLogger(__name__)

# Zustand → (Glyphe, Farbe). Bewusst Text-Glyphen: sie skalieren mit der Schrift
# und brauchen keine Icon-Dateien im Paket.
_GLYPHEN = {
    "pending": ("○", MUTED),
    "running": ("◐", ACCENT),
    "done": ("✓", ACCENT),
    "failed": ("!", "#E08585"),
    "manual": ("↗", "#E0B585"),
}


class _Bridge(QObject):
    """Worker-Thread → UI-Thread. Signale sind der einzige erlaubte Weg."""

    state = Signal(str, str, str)          # key, state, note
    progress = Signal(str, str, int)       # key, text, percent (<0 = unbestimmt)
    done = Signal(bool)


class _StepRow(QFrame):
    """Eine Zeile: Glyphe, Titel, Erklaerung, Status — plus Balken, wenn es laeuft."""

    def __init__(self, step, parent=None):
        super().__init__(parent)
        self.setObjectName("stepRow")
        self.setStyleSheet(
            f"QFrame#stepRow {{ background: rgba(255,255,255,0.03);"
            f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 10px; }}"
        )
        self.key = step.key
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        kopf = QHBoxLayout()
        kopf.setSpacing(10)
        self._glyph = QLabel()
        self._glyph.setFixedWidth(16)
        self._glyph.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        kopf.addWidget(self._glyph)

        self._title = QLabel(step.title)
        self._title.setStyleSheet(f"color: {TEXT}; font-size: 10pt; font-weight: 600;")
        kopf.addWidget(self._title)
        kopf.addStretch(1)
        self._note = QLabel(step.note)
        self._note.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        kopf.addWidget(self._note)
        lay.addLayout(kopf)

        if step.detail:
            detail = QLabel(step.detail)
            detail.setWordWrap(True)
            detail.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
            detail.setContentsMargins(26, 0, 0, 0)
            lay.addWidget(detail)

        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            f"QProgressBar {{ background: rgba(255,255,255,0.07); border: none;"
            f"  border-radius: 3px; margin-left: 26px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}"
        )
        self._bar.hide()
        lay.addWidget(self._bar)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setContentsMargins(26, 0, 0, 0)
        self._hint.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        self._hint.hide()
        lay.addWidget(self._hint)

        self.set_state(step.state, step.note)
        if step.manual:
            self.set_hint(step.manual)

    def set_state(self, state: str, note: str = "") -> None:
        glyphe, farbe = _GLYPHEN.get(state, _GLYPHEN["pending"])
        self._glyph.setText(glyphe)
        self._glyph.setStyleSheet(f"color: {farbe}; font-size: 11pt;")
        if note:
            self._note.setText(note)
        if state != "running":
            self._bar.hide()

    def set_progress(self, text: str, percent: int) -> None:
        self._note.setText(text)
        self._bar.show()
        if percent < 0:
            self._bar.setRange(0, 0)            # Qt-Bordmittel fuer "unbestimmt"
        else:
            self._bar.setRange(0, 100)
            self._bar.setValue(percent)

    def set_hint(self, text: str) -> None:
        self._hint.setText(text)
        self._hint.setVisible(bool(text))


class SetupPage(QWidget):
    """Seite „Einrichtung" — erhebt den Stand und arbeitet ihn auf Klick ab.

    Signale fuer die Einfuehrung, die den Download auf den folgenden Seiten in
    einer Zeile weiter anzeigt: `stand(text)` je Fortschritt, `fertig(ok)` am Ende.

    endpoints: LLM-Endpoints (fuer die Modellnamen), stt_model: Whisper-Groesse.
    on_ready: Callable() — wird gerufen, wenn am Ende alles bereit ist (damit die
    App Modelle vorladen kann, ohne auf den ersten Diktat-Fehlschlag zu warten).
    """

    stand = Signal(str)
    fertig = Signal(bool)

    def __init__(self, endpoints, stt_model: str,
                 base_url: str = "http://127.0.0.1:11434",
                 on_ready=None, parent=None, autostart: bool = True):
        super().__init__(parent)
        self._endpoints = list(endpoints or [])
        self._stt_model = stt_model
        self._base_url = base_url
        self._on_ready = on_ready
        self._runner = None
        self._thread = None
        self._rows = {}

        self._bridge = _Bridge(self)
        self._bridge.state.connect(self._on_state)
        self._bridge.progress.connect(self._on_progress)
        self._bridge.done.connect(self._on_done)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(0, 0, 0, 0)

        titel = QLabel("Einrichtung")
        titel.setStyleSheet(f"color: {TEXT}; font-size: 14pt; font-weight: 600;")
        lay.addWidget(titel)
        self._intro = QLabel(
            "Damit die Erkennung ohne Internet läuft, müssen die Modelle einmal auf "
            "diesen Rechner. Das übernimmt Fleech selbst — du kannst schon "
            "weiterklicken, der Download läuft im Hintergrund weiter."
        )
        self._intro.setWordWrap(True)
        self._intro.setStyleSheet(f"color: {TEXT}; font-size: 10pt;")
        lay.addWidget(self._intro)

        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(8)
        lay.addLayout(self._rows_box)

        knopf_reihe = QHBoxLayout()
        self._btn = style_button(QPushButton("Jetzt einrichten"), "primary")
        self._btn.clicked.connect(self.start)
        knopf_reihe.addWidget(self._btn)
        self._recheck = style_button(QPushButton("Erneut prüfen"))
        self._recheck.clicked.connect(self.refresh)
        knopf_reihe.addWidget(self._recheck)
        knopf_reihe.addStretch(1)
        lay.addLayout(knopf_reihe)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        lay.addWidget(self._status)
        lay.addStretch(1)

        self.refresh()
        # Es gibt keinen Grund, den Nutzer erst klicken zu lassen, wenn ohnehin
        # nur Downloads fehlen — aber die Ollama-INSTALLATION bleibt ein Klick
        # (fremde Software installiert man nicht als Nebenwirkung eines Starts).
        if autostart and self._only_downloads_missing():
            self.start()

    # -- Plan aendern (Einfuehrung: erst nach der KI-Wahl steht er fest) -----------

    def neu_planen(self, endpoints, stt_model: str, base_url: str) -> None:
        """Neuen Plan uebernehmen. Laeuft gerade ein Download fuer den alten, wird
        er nach dem laufenden Schritt angehalten und danach der neue erhoben."""
        self._endpoints = list(endpoints or [])
        self._stt_model = stt_model
        self._base_url = base_url
        if self.laeuft():
            self._neu_nach_lauf = True
            self.stop()
            return
        self.refresh()

    def starte_wenn_moeglich(self) -> None:
        """Downloads ohne Klick anwerfen — nie aber die Ollama-Installation."""
        if not self.laeuft() and self._only_downloads_missing():
            self.start()

    def laeuft(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def alles_bereit(self) -> bool:
        return all(s.state == "done" for s in getattr(self, "_steps", []))

    # -- Stand erheben ------------------------------------------------------------

    def refresh(self) -> None:
        """Stand neu erheben und die Zeilen aufbauen."""
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            schritte = build_steps(self._endpoints, self._stt_model, self._base_url)
        except Exception:
            log.exception("Einrichtungsstand nicht ermittelbar.")
            schritte = []
        self._steps = schritte

        while self._rows_box.count():
            item = self._rows_box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        self._rows = {}
        for schritt in schritte:
            row = _StepRow(schritt, self)
            self._rows[schritt.key] = row
            self._rows_box.addWidget(row)

        offen = [s for s in schritte if s.state != "done"]
        manuell = [s for s in schritte if s.state == "manual"]
        # Ein manueller Schritt sperrt nur SICH — das Erkennungsmodell kommt von
        # HuggingFace und laesst sich auch ohne Ollama laden.
        machbar = [s for s in offen if s.state != "manual"]
        self._btn.setEnabled(bool(machbar))
        self._btn.setText("Jetzt einrichten" if offen else "Alles bereit")
        if not offen:
            self._status.setText("Fleech ist einsatzbereit — du kannst gleich diktieren.")
        elif manuell:
            rest = (" Den Rest holt Fleech trotzdem." if machbar else "")
            self._status.setText(
                "Ollama kann Fleech auf diesem System nicht selbst installieren. "
                f"Nach der Installation auf „Erneut prüfen“ klicken.{rest}"
            )
        else:
            self._status.setText(
                "Der Download läuft im Hintergrund — du kannst das Fenster offen "
                "lassen und weiterarbeiten."
            )

    def _only_downloads_missing(self) -> bool:
        """Fehlt nur noch Herunterladbares (Ollama laeuft schon)?"""
        offen = [s for s in getattr(self, "_steps", []) if s.state != "done"]
        if not offen:
            return False
        return all(s.key != "ollama" for s in offen)

    # -- Ausfuehrung --------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._btn.setEnabled(False)
        self._btn.setText("Läuft …")
        self._status.setText(
            "Der Download läuft im Hintergrund — du kannst das Fenster offen "
            "lassen und weiterarbeiten."
        )
        bridge = self._bridge          # nur die Bridge fangen, nicht `self`

        def melde_state(key, state, note):
            bridge.state.emit(key, state, note)

        def melde_progress(key, text, percent):
            bridge.progress.emit(key, text, percent)

        runner = SetupRunner(
            endpoints=self._endpoints, stt_model=self._stt_model,
            base_url=self._base_url,
            on_state=melde_state, on_progress=melde_progress,
        )
        self._runner = runner

        def arbeite():
            ok = False
            try:
                ok = runner.run()
            except Exception:
                log.exception("Einrichtung fehlgeschlagen.")
            bridge.done.emit(bool(ok))

        self._thread = threading.Thread(target=arbeite, daemon=True, name="fleech-setup")
        self._thread.start()

    def stop(self) -> None:
        """Beim Schliessen aufrufen: laufende Schritte nicht weiter melden."""
        if self._runner is not None:
            self._runner.cancel()

    # -- Signale ------------------------------------------------------------------

    def _on_state(self, key: str, state: str, note: str) -> None:
        for schritt in getattr(self, "_steps", []):
            if schritt.key == key:
                schritt.state = state
                schritt.note = note or schritt.note
        row = self._rows.get(key)
        if row is not None:
            row.set_state(state, note)
            if state == "manual":
                from .. import ollama_setup

                row.set_hint(note if "\n" in note else ollama_setup.manual_hint())

    def _on_progress(self, key: str, text: str, percent: int) -> None:
        row = self._rows.get(key)
        if row is not None:
            row.set_progress(text, percent)
        titel = next((s.title for s in getattr(self, "_steps", []) if s.key == key), "")
        self.stand.emit(f"{titel}: {text}" if titel else text)

    def _on_done(self, ok: bool) -> None:
        self._thread = None
        if getattr(self, "_neu_nach_lauf", False):
            # Die KI-Wahl hat sich waehrend des Downloads geaendert: den neuen
            # Plan erheben und — wenn nur Downloads fehlen — gleich weitermachen.
            self._neu_nach_lauf = False
            self._runner = None
            self.refresh()
            self.starte_wenn_moeglich()
            return
        self.fertig.emit(bool(ok))
        self.stand.emit("Alles geladen — Fleech ist einsatzbereit." if ok
                        else "Ein Download ist offen geblieben — siehe Einrichtung.")
        self._btn.setText("Alles bereit" if ok else "Erneut versuchen")
        self._btn.setEnabled(not ok)
        if ok:
            self._status.setText(
                "Fertig — Fleech ist einsatzbereit. Weiter zum nächsten Schritt."
            )
            if self._on_ready is not None:
                try:
                    self._on_ready()
                except Exception:
                    log.debug("on_ready-Hook fehlgeschlagen.", exc_info=True)
        else:
            self._status.setText(
                "Ein Schritt ist offen geblieben — die Zeile oben sagt, welcher. "
                "Fleech versucht es beim nächsten Start automatisch erneut."
            )
