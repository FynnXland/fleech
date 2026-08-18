"""Textersetzung — Woerterbuch, Bausteine, Kontext.

Baut die Seite in das uebergebene SettingsPanel; die Widget-Bauer
(`panel._combo`, `panel._check`, ...) bleiben dort.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPushButton

from ..theme import style_button
from .common import hint


def build(panel) -> None:
    s = panel.settings
    _, form = panel._page()
    form.addRow("", hint(
        "Eigene Begriffe, die die Spracherkennung kennen soll — eine Zeile pro Eintrag."
    ))
    panel._dictionary_editor = panel._lines_editor(
        form, "Wörterbuch", s.output.dictionary, "dictionary",
        lambda lines: setattr(s.output, "dictionary", lines),
        placeholder="Fleech\nKimono\ngithub => GitHub\nCosinus => Kosinus",
        hint_text="„Begriff“ = besser erkennen. „falsch => richtig“ = zusätzlich "
                  "automatisch ersetzen.",
        height=220,
    )
    # Einsprech-Test: Man traegt ein Wort ein und weiss nicht, ob es etwas
    # gebracht hat — bis es mitten im Diktat wieder falsch dasteht.
    if panel._wortprobe_fn is not None:
        panel._probe_btn = style_button(QPushButton("Eintrag einsprechen …"), "ghost")
        panel._probe_btn.setToolTip(
            "Markiere im Wörterbuch eine Zeile (oder setz den Cursor hinein) "
            "und sprich das Wort einmal ins Mikrofon. Fleech zeigt, was ankommt."
        )
        panel._probe_btn.clicked.connect(panel._wortprobe_starten)
        form.addRow("", panel._probe_btn)
    # Transparenz zum Priming-Limit: ueber 60 Begriffen kann die Erkennung nicht
    # alle vorab kennen — sichtbar machen, statt still abzuschneiden.
    panel._priming_hint = hint("")
    panel._refresh_priming_hint()
    form.addRow("", panel._priming_hint)
    # Ignorier-Liste: abgelehnte Rueckfragen + weggeklickte Insights-Vorschlaege.
    # Sichtbar und editierbar, DAMIT „Ignorieren" dauerhaft sein darf — Zeile
    # loeschen holt den Vorschlag bzw. die Rueckfrage zurueck.
    panel._ignores_editor = panel._lines_editor(
        form, "Ignoriert", s.output.dictionary_ignores, "dictionary",
        lambda lines: setattr(s.output, "dictionary_ignores", lines),
        placeholder="kimano => kimono",
        hint_text="Paare, die nie mehr vorgeschlagen werden — aus abgelehnten "
                  "Rückfragen und „Ignorieren“ in den Insights. Zeile löschen "
                  "holt den Vorschlag zurück.",
        height=90,
    )

    # Projekt-Gedaechtnis: gelerntes Fachvokabular je App/Fenster. Bewusst
    # HIER, direkt unter dem Woerterbuch: Es ist dieselbe Sache, nur
    # automatisch — beides primt die Erkennung. Wer sucht, warum ein Wort
    # anders geschrieben wird, schaut an einer Stelle.
    panel._kontext_cb = panel._check(
        form, "Gedächtnis", getattr(s.advanced, "kontext_lernen", True),
        "output", panel._on_kontext_toggled,
        hint_text="Gelerntes Fachvokabular als Erkennungs-Hinweis. "
                  "Aus = weder lernen noch verwenden.",
    )
    form.addRow("", hint(
        "Fleech merkt sich je Programm und Fenster die Fachbegriffe, die dort "
        "vorkommen (alles mit Binnenversalien, Ziffern oder Punkten — "
        "„MCP-Server“, „PySide6“, „x_3“), und gibt sie beim nächsten Diktat "
        "als Hinweis an die Erkennung. Nur Schreibweisen: Der Inhalt geht nie "
        "an die KI, das Diktat wird dadurch nicht langsamer."
    ))
    panel._kontext_zeile = hint("")
    form.addRow("", panel._kontext_zeile)
    # Einzeln vergessen (V-14): Im Gedaechtnis stehen auch Hoerfehler
    # (`Cloud-Code`, `FLEACH` — echt aus kontext.db), und sie primen sich ueber
    # den initial_prompt selbst weiter. Bisher liess sich dagegen nur ALLES
    # loeschen — also loeschte niemand etwas.
    einzeln = QHBoxLayout()
    panel._kontext_begriffe = QComboBox()
    panel._kontext_begriffe.setMinimumWidth(220)
    panel._kontext_begriffe.setToolTip(
        "Was Fleech in diesem Programm gelernt hat, häufigste zuerst. "
        "Steht hier eine falsche Schreibweise, vergiss genau sie."
    )
    einzeln.addWidget(panel._kontext_begriffe, 1)
    einzeln_btn = style_button(QPushButton("Begriff vergessen"), "ghost")
    einzeln_btn.clicked.connect(panel._kontext_begriff_vergessen)
    einzeln.addWidget(einzeln_btn)
    form.addRow("", einzeln)
    vergessen = style_button(QPushButton("Gelerntes vergessen"), "ghost")
    vergessen.clicked.connect(panel._kontext_vergessen)
    form.addRow("", vergessen)
    panel._refresh_kontext_zeile()

    # Bausteine — gesprochenes Kuerzel fuegt einen festen Textblock ein.
    # BEWUSST auf derselben Seite wie das Woerterbuch (v3.12.0, aus einem
    # externen Gutachten): Beides sind Text-Ersetzungen — eines wortbasiert,
    # eines kuerzelbasiert. Als zwei getrennte Bereiche musste man raten, wo
    # man sucht.
    form.addRow("", hint(
        "Feste Textblöcke, die du per Sprache abrufst — z. B. „Baustein Signatur“ "
        "am Ende einer Mail. Der Text wird genau so eingefügt, wie er hier steht: "
        "keine KI schaut ihn an, nichts wird umformuliert."
    ))
    panel._snippets_editor = panel._lines_editor(
        form, "Bausteine", s.output.snippets, "snippets",
        lambda lines: setattr(s.output, "snippets", lines),
        placeholder=("Signatur => Viele Grüße\\nVorname Nachname\n"
                     "Absage => Vielen Dank für die Anfrage — leider muss ich absagen.\n"
                     "Docstring => \\\"\\\"\\\"\\n\\n\\\"\\\"\\\""),
        hint_text="Eine Zeile pro Baustein: „Kürzel => Text“. „\\n“ im Text "
                  "erzeugt einen Zeilenumbruch.",
        height=220,
    )
    keyword = QLineEdit(s.output.snippet_keyword)
    keyword.setPlaceholderText("leer = „Baustein“")
    keyword.editingFinished.connect(
        lambda: (setattr(s.output, "snippet_keyword", keyword.text().strip()),
                 panel._changed("snippets"))
    )
    label_w, _ = panel._row_label(
        "Signalwort",
        "Das gesprochene Wort vor dem Kürzel. Bewusst getrennt vom Safe-Word für "
        "Befehle: Bausteine fügen nur ein, Befehle verändern vorhandenen Text.",
    )
    form.addRow(label_w, keyword)
    form.addRow("", hint(
        "Wird das Signalwort erkannt, aber kein Kürzel getroffen, steht das im "
        "Log — dann hat die Erkennung das Kürzel verhört und ein kürzeres, "
        "deutlicheres Wort hilft."
    ))
