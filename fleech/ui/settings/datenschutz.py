"""Seite „Datenschutz" — was Fleech speichert, wie es geschuetzt ist, wie man es loescht.

Bis 6.4 standen diese Zeilen auf „Allgemein" (Verlauf, Aufbewahrung,
Verschluesselung) und „Advanced" (Protokoll). Seit 6.5.0 eine eigene Seite: Wer
wissen will, was auf der Platte liegt, soll an einer Stelle suchen. Oben Verlauf,
Aufbewahrung, Wiederherstellungscode und Loeschen; das Protokoll unter
„Mehr Optionen" (`advanced.protokoll`).
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from ...i18n import N_, tr
from ..theme import style_button
from . import advanced
from .common import hint
from .mehr import angleichen, bereich

# 0 = unbegrenzt. Die Vorgabe (90) steht in GeneralSettings/history.
AUFBEWAHRUNG = [(30, N_("30 Tage")), (90, N_("90 Tage")), (180, N_("180 Tage")),
                (365, N_("1 Jahr")), (0, N_("Unbegrenzt"))]


def tresor_zeile() -> str:
    """Ein Satz: was verschluesselt ist und wo der Schluessel liegt."""
    try:
        from ...tresor import schluessel

        return tr("Verlauf, gelerntes Vokabular und Einstellungen liegen verschlüsselt "
                  "(AES-256); der Schlüssel ist {ort}.",
                  ort=tr(schluessel.ablage().beschreibung()))
    except Exception:
        return tr("Verschlüsselung: Status nicht abrufbar.")


def build(panel) -> None:
    s = panel.settings
    seite, form = panel._page()
    form.addRow("", hint(
        tr("Was Fleech speichert, wie es geschützt ist — und wie du es löschst.")
    ))
    mehr = bereich(seite, form)
    panel._check(form, tr("Diktat-Verlauf speichern"), s.general.save_history, "general",
                 lambda v: setattr(s.general, "save_history", v),
                 tr("Speichert Diktate lokal für Home und Insights — keine Cloud, "
                    "verschlüsselt auf der Platte."))
    _verschluesselung(panel, form)
    clear_btn = style_button(QPushButton(tr("Verlauf löschen …")), "danger")
    clear_btn.clicked.connect(lambda: (panel._on_clear_history or (lambda: None))())
    label_w, _ = panel._row_label(
        tr("Verlauf"), tr("Löscht alle Diktate endgültig — dazu „Delete“ eintippen."))
    form.addRow(label_w, clear_btn)
    advanced.protokoll(panel, mehr)
    angleichen(form, mehr)


def _verschluesselung(panel, form) -> None:
    """Aufbewahrung, Wiederherstellungscode und der Hinweis, solange er fehlt."""
    s = panel.settings
    panel._combo(
        form, tr("Verlauf aufbewahren"), [(w, tr(t)) for w, t in AUFBEWAHRUNG],
        s.general.verlauf_tage if s.general.verlauf_tage in dict(AUFBEWAHRUNG) else 90,
        "datenschutz", lambda v: setattr(s.general, "verlauf_tage", int(v)),
        hint_text=tr("Ältere Diktate löscht Fleech automatisch. Die Zahlen für "
                     "Insights (Serie, Wörter) bleiben erhalten, Text, App und "
                     "Fenstertitel nicht."))
    code_btn = style_button(QPushButton(tr("Wiederherstellungscode …")))
    label_w, _ = panel._row_label(
        tr("Verschlüsselung"),
        tresor_zeile() + " " + tr("Der Code öffnet deine Daten, falls das Windows-Konto "
                                  "verloren geht (Neuinstallation, neuer Rechner). Ohne ihn sind sie dann "
                                  "nicht mehr lesbar."))
    form.addRow(label_w, code_btn)
    # Einzeilig: Umbrechende Labels bekommen im QFormLayout zu viel Hoehe.
    panel._code_offen = hint(tr("Noch nicht notiert. Ohne Code sind die Daten nach einer "
                                "Neuinstallation weg."))
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
