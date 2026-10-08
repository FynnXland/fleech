"""Der Tresor an der Oberflaeche: Startpruefung, Entsperren, Wiederherstellungscode.

`tresor_bereitstellen()` laeuft in `run_desktop` VOR `DesktopApp()` — also bevor
irgendetwas Einstellungen, Verlauf oder Gedaechtnis oeffnet. Zwei Faelle:

* Kein Schluessel, aber verschluesselte Daten (Windows neu installiert, anderes
  Konto): `EntsperrDialog` fragt nach dem Wiederherstellungscode. Ohne Code
  laesst sich neu beginnen — die alten Daten werden dann beiseitegelegt, nicht
  geloescht. Stillschweigend mit Vorgaben zu starten waere der schlechteste Weg:
  Der erste Speichervorgang haette die Einstellungen mit einem neuen Schluessel
  ueberschrieben, und der Code haette danach nur noch die Haelfte geoeffnet.
* Klartext von frueher: die einmalige Umstellung (`tresor.umstellung`).

`CodeDialog` zeigt den Wiederherstellungscode — nach der Umstellung einmal von
selbst, sonst ueber Einstellungen → Allgemein.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from .theme import AMBER, BG, BORDER_HAIRLINE, CARD, MUTED, TEXT, style_button

log = logging.getLogger(__name__)

_CODE_QSS = (f"background: {CARD}; color: {TEXT}; border: 1px solid {BORDER_HAIRLINE};"
             f" border-radius: 8px; padding: 12px; font-family: Consolas, monospace;"
             f" font-size: 12pt; letter-spacing: 1px;")


def _text(inhalt: str, farbe: str = MUTED, groesse: str = "9pt") -> QLabel:
    label = QLabel(inhalt)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {farbe}; font-size: {groesse};")
    return label


class CodeDialog(QDialog):
    """Den Wiederherstellungscode zeigen. `on_notiert` laeuft bei „Ich habe ihn notiert"."""

    def __init__(self, parent=None, nach_umstellung: bool = False, on_notiert=None):
        super().__init__(parent)
        from ..tresor import schluessel

        self._on_notiert = on_notiert
        self._code = schluessel.code_aus(schluessel.hauptschluessel())
        self.setWindowTitle("Wiederherstellungscode")
        self.setStyleSheet(f"QDialog {{ background: {BG}; }}")
        self.resize(560, 0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 16)
        outer.setSpacing(10)
        if nach_umstellung:
            outer.addWidget(_text(
                "Fleech hat deinen Verlauf, das gelernte Vokabular und die "
                "Einstellungen verschlüsselt. Die alten Protokolle mit Diktattext "
                "sind gelöscht.", TEXT, "10pt"))
        outer.addWidget(_text(
            f"Der Schlüssel ist {schluessel.ablage().beschreibung()}. Geht dieses "
            "Konto verloren (Neuinstallation, neuer Rechner), öffnet nur dieser Code "
            "deine Daten wieder. Schreib ihn auf Papier oder leg ihn in deinen "
            "Passwort-Manager, aber nicht als Datei neben Fleech."))
        code = QLabel(self._code)
        code.setTextInteractionFlags(Qt.TextSelectableByMouse)
        code.setAlignment(Qt.AlignCenter)
        code.setWordWrap(True)
        code.setStyleSheet(_CODE_QSS)
        outer.addWidget(code)
        outer.addWidget(_text("Wer diesen Code und deine Dateien hat, kann sie lesen. "
                              "Behandle ihn wie ein Passwort.", AMBER, "8.5pt"))

        knoepfe = QHBoxLayout()
        self._kopieren = style_button(QPushButton("Kopieren"))
        self._kopieren.clicked.connect(self._kopiere)
        spaeter = style_button(QPushButton("Später"), "ghost")
        spaeter.clicked.connect(self.reject)
        notiert = style_button(QPushButton("Ich habe ihn notiert"), "primary")
        notiert.clicked.connect(self._bestaetige)
        knoepfe.addWidget(self._kopieren)
        knoepfe.addStretch(1)
        knoepfe.addWidget(spaeter)
        knoepfe.addWidget(notiert)
        outer.addLayout(knoepfe)

    def _kopiere(self) -> None:
        from ..clipboard import copy_text   # privat: nicht im Win+V-Verlauf

        copy_text(self._code)
        self._kopieren.setText("Kopiert ✓")

    def _bestaetige(self) -> None:
        if self._on_notiert:
            self._on_notiert()
        self.accept()


class EntsperrDialog(QDialog):
    """Verschluesselte Daten ohne Schluessel: Code eingeben, neu beginnen oder beenden."""

    def __init__(self, ordner, parent=None):
        super().__init__(parent)
        self._ordner = ordner
        self.beiseitegelegt = None
        self.setWindowTitle("Fleech – Daten entsperren")
        self.setStyleSheet(f"QDialog {{ background: {BG}; }}")
        self.resize(560, 0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 16)
        outer.setSpacing(10)
        outer.addWidget(_text("Deine Fleech-Daten sind verschlüsselt, aber der "
                              "Schlüssel fehlt auf diesem Konto.", TEXT, "10.5pt"))
        outer.addWidget(_text(
            "Das passiert nach einer Neuinstallation von Windows, auf einem neuen "
            "Benutzerkonto oder wenn der Ordner von einem anderen Rechner stammt. "
            "Gib den Wiederherstellungscode ein, den Fleech dir nach der "
            "Verschlüsselung gezeigt hat."))
        self._eingabe = QLineEdit()
        self._eingabe.setPlaceholderText("XXXXX-XXXXX-XXXXX-…")
        self._eingabe.setStyleSheet(_CODE_QSS)
        self._eingabe.returnPressed.connect(self._entsperre)
        outer.addWidget(self._eingabe)
        self._meldung = _text("", AMBER, "9pt")
        self._meldung.hide()
        outer.addWidget(self._meldung)

        knoepfe = QHBoxLayout()
        neu = style_button(QPushButton("Neu beginnen …"), "danger")
        neu.clicked.connect(self._neu_beginnen)
        beenden = style_button(QPushButton("Beenden"), "ghost")
        beenden.clicked.connect(self.reject)
        entsperren = style_button(QPushButton("Entsperren"), "primary")
        entsperren.clicked.connect(self._entsperre)
        knoepfe.addWidget(neu)
        knoepfe.addStretch(1)
        knoepfe.addWidget(beenden)
        knoepfe.addWidget(entsperren)
        outer.addLayout(knoepfe)

    def _melde(self, text: str) -> None:
        self._meldung.setText(text)
        self._meldung.show()

    def _entsperre(self) -> None:
        from ..tresor import schluessel

        try:
            kandidat = schluessel.schluessel_aus(self._eingabe.text())
        except ValueError as exc:
            self._melde(str(exc))
            return
        if not schluessel.passt_zu_daten(kandidat, self._ordner):
            self._melde("Der Code ist gültig, passt aber nicht zu diesen Daten.")
            return
        schluessel.uebernimm(kandidat)
        self.accept()

    def _neu_beginnen(self) -> None:
        from ..tresor import umstellung

        antwort = QMessageBox.question(
            self, "Neu beginnen",
            "Fleech startet mit frischen Einstellungen und leerem Verlauf.\n\n"
            "Die verschlüsselten Daten werden nicht gelöscht, sondern in einen Ordner "
            "„gesperrt-…“ im Fleech-Datenordner verschoben. Taucht der Code später "
            "auf, lassen sie sich zurückholen.")
        if antwort != QMessageBox.Yes:
            return
        self.beiseitegelegt = umstellung.beiseitelegen(self._ordner)
        self.accept()


def tresor_bereitstellen():
    """Schluessel sicherstellen und Klartext umstellen — vor allem anderen.

    Rueckgabe: der `Bericht` der Umstellung (auch leer), oder None, wenn der
    Nutzer ohne Schluessel beenden will.
    """
    from ..tresor import schluessel, umstellung

    ordner = schluessel.DATENORDNER
    if schluessel.fehlt():
        log.warning("Tresor: verschluesselte Daten, aber kein Schluessel — frage nach "
                    "dem Wiederherstellungscode.")
        dialog = EntsperrDialog(ordner)
        if dialog.exec() != QDialog.Accepted:
            log.info("Tresor: ohne Schluessel beendet.")
            return None
    try:
        if umstellung.noetig(ordner):
            return umstellung.fuehre_aus(ordner)
    except Exception:
        log.exception("Tresor: Umstellung fehlgeschlagen — die Daten bleiben vorerst "
                      "unverschluesselt, der naechste Start versucht es erneut.")
        return umstellung.Bericht(fehlgeschlagen=True)
    return umstellung.Bericht()
