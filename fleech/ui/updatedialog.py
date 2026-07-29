"""Update-Dialog: Version zeigen, laden, installieren — im Design-System.

Bewusst getrennt vom Einstellungsfenster: Ein Update kann auch dann anstehen, wenn
niemand die Einstellungen offen hat (Tray-Meldung → dieser Dialog). Der Ablauf ist
immer derselbe und nie stiller als hier sichtbar:

    pruefen (automatisch) → laden (automatisch erlaubt) → INSTALLIEREN NUR AUF KLICK

Qt: Der Download laeuft in einem Thread und meldet ueber Signale (`_Bridge`) — kein
Qt-Zugriff aus dem Worker, keine Lambdas mit `self`-Fang in Kind-Widgets.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextEdit, QVBoxLayout,
)

from ..usersettings import SETTINGS_DIR
from .main_window import ACCENT, BORDER_HAIRLINE, CARD, MUTED, TEXT, style_button
from .updates import download_update, install_update, update_token

log = logging.getLogger(__name__)

UPDATE_DIR = SETTINGS_DIR / "updates"


class _Bridge(QObject):
    progress = Signal(int, str)
    done = Signal(str)          # Pfad der geladenen Datei ("" = fehlgeschlagen)


class UpdateDialog(QDialog):
    """`info` ist das Ergebnis von check_for_updates() mit status "update_available".

    on_quit: Callable() — beendet die App, nachdem der Installer gestartet ist.
    fertige_datei: bereits geladene Installationsdatei (dann direkt installierbar).
    """

    def __init__(self, info: dict, on_quit=None, parent=None, fertige_datei=None,
                 settings=None):
        super().__init__(parent)
        self._info = dict(info or {})
        self._on_quit = on_quit
        self._token = update_token(settings)
        self._datei = fertige_datei
        self._thread = None

        self.setWindowTitle("Update verfügbar")
        self.setMinimumWidth(460)
        self.setStyleSheet(f"QDialog {{ background: {CARD}; }}")

        self._bridge = _Bridge(self)
        self._bridge.progress.connect(self._on_progress)
        self._bridge.done.connect(self._on_done)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(12)

        titel = QLabel(f"Fleech {self._info.get('latest', '?')} ist verfügbar")
        titel.setStyleSheet(f"color: {TEXT}; font-size: 14pt; font-weight: 600;")
        titel.setWordWrap(True)
        lay.addWidget(titel)

        groesse = int(self._info.get("size") or 0)
        mb = f" · Download {groesse / (1024 * 1024):.0f} MB" if groesse else ""
        unter = QLabel(f"Installiert: {self._info.get('current', '')}{mb}")
        unter.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        lay.addWidget(unter)

        notizen = str(self._info.get("notes") or "").strip()
        if notizen:
            feld = QTextEdit()
            feld.setReadOnly(True)
            feld.setPlainText(notizen)
            feld.setFixedHeight(140)
            feld.setStyleSheet(
                f"QTextEdit {{ background: rgba(255,255,255,0.03); color: {TEXT};"
                f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
                f"  font-size: 9.5pt; padding: 8px; }}"
            )
            lay.addWidget(feld)

        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            f"QProgressBar {{ background: rgba(255,255,255,0.07); border: none;"
            f"  border-radius: 3px; }}"
            f"QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}"
        )
        self._bar.hide()
        lay.addWidget(self._bar)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        lay.addWidget(self._status)

        knoepfe = QHBoxLayout()
        self._spaeter = style_button(QPushButton("Später"))
        self._spaeter.clicked.connect(self.reject)
        knoepfe.addWidget(self._spaeter)
        knoepfe.addStretch(1)
        self._btn = style_button(QPushButton("Herunterladen"), "primary")
        self._btn.clicked.connect(self._on_button)
        knoepfe.addWidget(self._btn)
        lay.addLayout(knoepfe)

        if self._datei is not None:
            self._bereit()

    # -- Ablauf ------------------------------------------------------------------

    def _bereit(self) -> None:
        self._btn.setText("Installieren und neu starten")
        self._btn.setEnabled(True)
        self._status.setText(
            "Geladen und geprüft. Beim Installieren beendet sich Fleech kurz."
        )

    def _on_button(self) -> None:
        if self._datei is not None:
            self._installieren()
        else:
            self._laden()

    def _laden(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._btn.setEnabled(False)
        self._btn.setText("Lädt …")
        self._bar.show()
        self._bar.setRange(0, 100)
        bridge = self._bridge                  # nur die Bridge fangen, nicht `self`
        info = dict(self._info)
        marke = self._token

        def arbeite():
            pfad = None
            try:
                pfad = download_update(
                    info.get("url", ""), UPDATE_DIR,
                    on_progress=lambda p, t: bridge.progress.emit(int(p), str(t)),
                    expected_size=int(info.get("size") or 0),
                    expected_sha256=str(info.get("sha256") or ""),
                    token=marke, dateiname=str(info.get("name") or ""),
                )
            except Exception:
                log.exception("Update-Download fehlgeschlagen.")
            bridge.done.emit(str(pfad) if pfad else "")

        self._thread = threading.Thread(target=arbeite, daemon=True,
                                        name="fleech-update-download")
        self._thread.start()

    def _installieren(self) -> None:
        self._btn.setEnabled(False)
        self._status.setText("Installation startet …")
        if not install_update(self._datei):
            self._status.setText(
                "Der Installer ließ sich nicht starten. Die Datei liegt in "
                f"{UPDATE_DIR} und kann von Hand ausgeführt werden."
            )
            self._btn.setEnabled(True)
            return
        self.accept()
        if self._on_quit is not None:
            try:
                self._on_quit()
            except Exception:
                log.exception("App-Beenden nach Update-Start fehlgeschlagen.")

    # -- Signale -----------------------------------------------------------------

    def _on_progress(self, prozent: int, text: str) -> None:
        if prozent < 0:
            self._bar.setRange(0, 0)
        else:
            self._bar.setRange(0, 100)
            self._bar.setValue(prozent)
        self._status.setText(text)

    def _on_done(self, pfad: str) -> None:
        self._thread = None
        self._bar.hide()
        if not pfad:
            self._btn.setText("Erneut versuchen")
            self._btn.setEnabled(True)
            self._status.setText(
                "Download oder Prüfung fehlgeschlagen — nichts wurde installiert. "
                "Details stehen im Log."
            )
            return
        from pathlib import Path

        self._datei = Path(pfad)
        self._bereit()

    def closeEvent(self, event) -> None:
        # Ein laufender Download ist ein Daemon-Thread; er endet mit der App. Nichts
        # zu stoppen, aber der Dialog darf nicht auf ihn warten.
        super().closeEvent(event)
