"""Lizenzschluessel eintragen — der einzige Weg, Fleech freizuschalten.

Der Dialog erscheint, wenn ohne gueltigen Schluessel aufgenommen werden soll, und
ist ueber die Einstellungen jederzeit erreichbar. Er prueft sofort beim Einfuegen:
ein Schluessel, der erst nach dem Schliessen als ungueltig auffaellt, waere eine
Zumutung — der Nutzer sitzt dann ohne Rueckmeldung da.

Qt: keine Lambdas mit `self`-Fang in Kind-Widgets (Referenzzyklus → Access
Violation), Karten per objectName gescopet.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout,
)

from ..licensing import check, verify
from .main_window import ACCENT, BORDER_HAIRLINE, CARD, MUTED, TEXT, style_button

log = logging.getLogger(__name__)

_OK_FARBE = ACCENT
_FEHLER_FARBE = "#E08585"


class LicenseDialog(QDialog):
    """settings: UserSettings (wird bei Erfolg gespeichert).

    on_changed: Callable(section) — dieselbe Nahtstelle wie im Settings-Panel.
    """

    def __init__(self, settings, on_changed=None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._on_changed = on_changed

        self.setWindowTitle("Fleech freischalten")
        self.setMinimumWidth(520)
        self.setStyleSheet(f"QDialog {{ background: {CARD}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(12)

        titel = QLabel("Fleech freischalten")
        titel.setStyleSheet(f"color: {TEXT}; font-size: 14pt; font-weight: 600;")
        lay.addWidget(titel)

        text = QLabel(
            "Fleech braucht einen persönlichen Lizenzschlüssel. Du hast ihn von "
            "der Person bekommen, die dir die Installationsdatei gegeben hat — "
            "füge ihn hier ein."
        )
        text.setWordWrap(True)
        text.setStyleSheet(f"color: {TEXT}; font-size: 10pt;")
        lay.addWidget(text)

        self._feld = QTextEdit()
        self._feld.setPlaceholderText("FLEECH-1.…")
        self._feld.setFixedHeight(92)
        self._feld.setStyleSheet(
            f"QTextEdit {{ background: rgba(255,255,255,0.04); color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; border-radius: 8px;"
            f"  font-family: Consolas, monospace; font-size: 9pt; padding: 8px; }}"
        )
        self._feld.setPlainText(settings.general.license_key or "")
        self._feld.textChanged.connect(self._on_text_changed)
        lay.addWidget(self._feld)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        lay.addWidget(self._status)

        hinweis = QLabel(
            "Der Schlüssel gilt für dich persönlich und wird nur auf diesem Rechner "
            "gespeichert. Geprüft wird ohne Internet."
        )
        hinweis.setWordWrap(True)
        hinweis.setStyleSheet(f"color: {MUTED}; font-size: 9pt;")
        lay.addWidget(hinweis)

        knoepfe = QHBoxLayout()
        self._spaeter = style_button(QPushButton("Später"))
        self._spaeter.clicked.connect(self.reject)
        knoepfe.addWidget(self._spaeter)
        knoepfe.addStretch(1)
        self._ok = style_button(QPushButton("Freischalten"), "primary")
        self._ok.clicked.connect(self._uebernehmen)
        knoepfe.addWidget(self._ok)
        lay.addLayout(knoepfe)

        self._on_text_changed()

    # -- Interaktion ---------------------------------------------------------------

    def _aktueller_zustand(self):
        return verify(self._feld.toPlainText())

    def _on_text_changed(self) -> None:
        """Sofortige Rueckmeldung beim Tippen/Einfuegen."""
        roh = self._feld.toPlainText().strip()
        if not roh:
            self._status.setText("")
            self._ok.setEnabled(False)
            return
        zustand = self._aktueller_zustand()
        if zustand.ok:
            gueltig = (f"gültig bis {zustand.expires}" if zustand.expires
                       else "unbefristet gültig")
            self._status.setText(f"✓ Schlüssel für {zustand.name or 'diese Installation'} "
                                 f"— {gueltig}.")
            self._status.setStyleSheet(f"color: {_OK_FARBE}; font-size: 9pt;")
        else:
            self._status.setText(zustand.reason)
            self._status.setStyleSheet(f"color: {_FEHLER_FARBE}; font-size: 9pt;")
        self._ok.setEnabled(zustand.ok)

    def _uebernehmen(self) -> None:
        zustand = self._aktueller_zustand()
        if not zustand.ok:
            return
        from ..licensing import normalize

        self.settings.general.license_key = normalize(self._feld.toPlainText())
        self.settings.save()
        log.info("Lizenz eingetragen (%s).", zustand.name or "ohne Namen")
        if self._on_changed is not None:
            try:
                self._on_changed("general")
            except Exception:
                log.debug("Lizenz-Hook fehlgeschlagen.", exc_info=True)
        self.accept()


def license_summary(settings) -> str:
    """Einzeiler fuer die Einstellungen ("Lizenz: Name, unbefristet")."""
    zustand = check(settings)
    if not zustand.ok:
        return zustand.reason
    if zustand.expires:
        return f"{zustand.name or 'Freigeschaltet'} — gültig bis {zustand.expires}"
    return f"{zustand.name or 'Freigeschaltet'} — unbefristet"
