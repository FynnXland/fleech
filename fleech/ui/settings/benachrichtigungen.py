"""Benachrichtigungs-Zeilen der Seite „Ruhe": Banner, „Nicht stören", Spiele.

Seit 6.5.0 ein Baustein: „Nicht stören", Banner-Stufe und Spiel-Erkennung oben,
die Feineinstellungen unter „Mehr Optionen".
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

from ...i18n import tr
from ...usersettings import TOAST_LEVELS, apply_toast_level, toast_level


def zeilen(panel, form, mehr) -> None:
    s = panel.settings
    f = s.focus
    panel._check(form, tr("Windows Do Not Disturb respektieren"), f.respect_dnd, "focus",
                 lambda v: setattr(f, "respect_dnd", v),
                 tr("Bei „Nicht stören“: keine unwichtigen Banner."))
    panel._check(mehr, tr("Sounds bei DND stummschalten"), f.dnd_mute_sounds, "focus",
                 lambda v: setattr(f, "dnd_mute_sounds", v),
                 tr("Bei „Nicht stören“ zusätzlich alle Fleech-Töne stumm."))
    # Frueher fuenf einzelne Toast-Schalter. Die Entscheidung, die man wirklich
    # trifft, ist "wie viel darf mich unterbrechen" — nicht Banner fuer Banner.
    panel._combo(
        form, tr("Windows-Banner"),
        [(wert, tr(text)) for wert, text in TOAST_LEVELS],
        toast_level(f), "focus",
        lambda v: apply_toast_level(f, v),
        hint_text=tr("„Wichtiges“ meldet nur Probleme (Fehler, Anbieter-Quota); "
                     "„Alles“ zusätzlich Statusmeldungen wie „läuft im Hintergrund“."),
    )
    panel._check(mehr, tr("Akzent-Sound bei kritischen Toasts"), f.notification_sounds,
                 "focus", lambda v: setattr(f, "notification_sounds", v),
                 tr("Eigener Ton bei kritischen Bannern."))
    panel._check(form, tr("Gaming-/Fullscreen-Erkennung"), f.gaming_detection, "focus",
                 lambda v: setattr(f, "gaming_detection", v),
                 tr("Erkennt Spiele und Vollbild-Apps automatisch."))
    panel._combo(
        mehr, tr("Overlay im Gaming-Modus"),
        [("activity_only", tr("Nur bei Aufnahme/Verarbeitung (empfohlen)")),
         ("compact", tr("Compact")), ("hidden", tr("Versteckt")),
         ("unchanged", tr("Unverändert"))],
        f.gaming_overlay, "focus", lambda v: setattr(f, "gaming_overlay", v),
        hint_text=tr("Verhalten der Pille, während ein Spiel läuft."),
    )
    panel._slider(mehr, tr("Fleech-eigene Töne im Spiel"), f.gaming_sound_factor,
                  "focus", lambda v: setattr(f, "gaming_sound_factor", v),
                  hint_text=tr("Lautstärke der Fleech-Töne im Spiel. 0 % = stumm."))
    exceptions = QLineEdit(", ".join(f.gaming_exceptions))
    exceptions.editingFinished.connect(lambda: (
        setattr(f, "gaming_exceptions",
                [e.strip() for e in exceptions.text().split(",") if e.strip()]),
        panel._changed("focus"),
    ))
    label_w, _ = panel._row_label(
        tr("Ausnahmen (Prozesse)"),
        tr("Prozesse, die nicht als Spiel gelten — durch Komma getrennt."),
    )
    mehr.addRow(label_w, exceptions)
    buttons = QWidget()
    row = QHBoxLayout(buttons)
    row.setContentsMargins(0, 0, 0, 0)
    test_toast = QPushButton(tr("Test-Toast"))
    test_toast.clicked.connect(lambda: panel._test_hooks.get("toast", lambda: None)())
    test_sound = QPushButton(tr("Test-Sound"))
    test_sound.clicked.connect(lambda: panel._test_hooks.get("sound", lambda: None)())
    row.addWidget(test_toast)
    row.addWidget(test_sound)
    row.addStretch(1)
    label_w, _ = panel._row_label(tr("Testen"), tr("Probe-Banner und Probe-Ton abspielen."))
    mehr.addRow(label_w, buttons)
