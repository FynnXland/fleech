"""Datenschutz-Zeilen der Seite „Allgemein": Aufbewahrung, Verschluesselung, Code.

Eigener Baustein statt weiterer Zeilen in `allgemein.py`: Das Thema hat eigene
Logik (Status des Tresors, der Code-Dialog), und die Seite soll Seite bleiben.
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from ..theme import style_button
from .common import hint

# 0 = unbegrenzt. Die Vorgabe (90) steht in GeneralSettings/history.
AUFBEWAHRUNG = [(30, "30 Tage"), (90, "90 Tage"), (180, "180 Tage"),
                (365, "1 Jahr"), (0, "Unbegrenzt")]


def tresor_zeile() -> str:
    """Ein Satz: was verschluesselt ist und wo der Schluessel liegt."""
    try:
        from ...tresor import schluessel

        return ("Verlauf, gelerntes Vokabular und Einstellungen liegen verschlüsselt "
                f"(AES-256); der Schlüssel ist {schluessel.ablage().beschreibung()}.")
    except Exception:
        return "Verschlüsselung: Status nicht abrufbar."


def baue(panel, form) -> None:
    s = panel.settings
    panel._combo(
        form, "Verlauf aufbewahren", AUFBEWAHRUNG,
        s.general.verlauf_tage if s.general.verlauf_tage in dict(AUFBEWAHRUNG) else 90,
        "datenschutz", lambda v: setattr(s.general, "verlauf_tage", int(v)),
        hint_text="Ältere Diktate löscht Fleech automatisch. Die Zahlen für "
                  "Insights (Serie, Wörter) bleiben erhalten, Text, App und "
                  "Fenstertitel nicht.")
    code_btn = style_button(QPushButton("Wiederherstellungscode …"))
    label_w, _ = panel._row_label(
        "Verschlüsselung",
        tresor_zeile() + " Der Code öffnet deine Daten, falls das Windows-Konto "
        "verloren geht (Neuinstallation, neuer Rechner). Ohne ihn sind sie dann "
        "nicht mehr lesbar.")
    form.addRow(label_w, code_btn)
    # Einzeilig: Umbrechende Labels bekommen im QFormLayout zu viel Hoehe.
    panel._code_offen = hint("Noch nicht notiert. Ohne Code sind die Daten nach einer "
                             "Neuinstallation weg.")
    panel._code_offen.setWordWrap(False)
    panel._code_offen.setStyleSheet("color: #E0A030; font-size: 8pt;")
    panel._code_offen.setHidden(bool(s.general.wiederherstellung_notiert))
    form.addRow("", panel._code_offen)

    _ref = s
    _hinweis = panel._code_offen

    def notiert() -> None:
        _ref.general.wiederherstellung_notiert = True
        _ref.save()
        _hinweis.setHidden(True)

    def zeige() -> None:
        from ..tresordialoge import CodeDialog

        CodeDialog(code_btn.window(), on_notiert=notiert).exec()

    code_btn.clicked.connect(zeige)
