"""Aufnahme — Bedienmodus, Hotkeys, Mikrofon.

Baut die Seite in das uebergebene SettingsPanel; die Widget-Bauer
(`panel._combo`, `panel._check`, ...) bleiben dort.

Der Freihand-Block (Schalter, Startwoerter, Genauigkeit, Abbruchwort,
Fehlersuche, Sperrliste) ist in 5.11.0 entfallen: Der Modus ist seit 5.10.1
stillgelegt, vier seiner fuenf Bedienelemente waren trotzdem bedienbar und
versprachen Wirkung, die es nicht gab (Befunde E-8/E-9/E-12). Der Code bleibt
eingefroren in `fleech/freihand.py`; der Nachfolger ist der Bedienmodus
„Anstupsen". Sein Regler „Sprechpause bis Ende" steht deshalb hier weiter —
er gehoert zu Anstupsen, nicht zu Freihand.
"""

from __future__ import annotations

from .common import hint


def build(panel) -> None:
    s = panel.settings
    _, form = panel._page()
    form.addRow("", hint(
        "Wie du das Diktat auslöst — und welches Mikrofon genutzt wird."
    ))
    # Der Sprechpause-Regler gehoert zum Anstupsen-Modus und wird mit ihm
    # ein- und ausgeblendet. Er entsteht aber erst NACH dem Combo (er steht
    # ja darunter) — deshalb der Umweg ueber diese Liste statt eines direkten
    # Zugriffs im Setter.
    #
    # Der Setter faengt BEWUSST nur `s` und diese Liste, NIEMALS `panel`: Ein
    # Lambda, das den Qt-Parent faengt und in einem Kind-Widget haengt, baut
    # einen Referenzzyklus. Die Widgets sterben dann per GC in undefinierter
    # Reihenfolge — real aufgetreten als wandernde „access violation", deren
    # Absturzort nichts mit der Ursache zu tun hatte (siehe CLAUDE.md).
    pausen_zeilen: list = []

    def modus_gesetzt(v, _ziel=s.recording, _zeilen=pausen_zeilen):
        _ziel.mode = v
        for layout, box in _zeilen:
            layout.setRowVisible(box, v == "nudge")

    panel._combo(
        form, "Bedienmodus",
        [("hold", "Hold-to-talk (halten)"), ("toggle", "Toggle (drücken/drücken)"),
         ("nudge", "Anstupsen (endet von selbst)")],
        s.recording.mode, "recording", modus_gesetzt,
        help_map={
            "hold": "Taste halten = aufnehmen, loslassen = fertig.",
            "toggle": "Einmal drücken = Start, nochmal = fertig.",
            "nudge": "Einmal drücken = Start. Hörst du auf zu reden, ist das "
                     "Diktat fertig — ohne dass du die Taste nochmal anfasst. "
                     "Ein zweiter Druck beendet trotzdem sofort.",
        },
    )
    panel._sprechpause_box = panel._spin(
        form, "Sprechpause bis Ende", s.freihand.stille_s, 1.0, 4.0, "freihand",
        lambda v: setattr(s.freihand, "stille_s", v),
        hint_text="Nur beim Anstupsen: So lange still = Diktat fertig. Kürzer "
                  "schneidet Denkpausen ab, länger lässt dich warten.",
    )
    pausen_zeilen.append((form, panel._sprechpause_box))
    form.setRowVisible(panel._sprechpause_box, s.recording.mode == "nudge")
    panel._add_hotkey_field(
        form, "Diktat-Hotkey", "hotkey", "dictate", "f9",
        hint_text="„Aufnehmen“ klicken, dann Taste, Kombination oder Maustaste "
                  "4/5/Mitte drücken. Esc, Entf oder Backspace = Bindung löschen.",
    )
    # Das Feld „Mathe-Umschalt" ist mit v3.7.2 entfallen: Den Modus gibt es seit
    # v3.0.0 nicht mehr (Formeln entstehen im lokalen Parser), die Taste war also
    # seit sieben Versionen wirkungslos einstellbar.
    panel._add_hotkey_field(
        form, "KI-Prompting", "prompt_toggle_hotkey", "prompt_toggle", "ctrl+alt+p",
        hint_text="Nur WÄHREND einer Aufnahme: dieses Diktat wird als strukturierter "
                  "KI-Prompt formuliert. Dauerhaft: Profil „KI-Prompt“ wählen.",
    )
    panel._add_hotkey_field(
        form, "Rohtext einsetzen", "undo_hotkey", "undo", "ctrl+alt+z",
        # Befund A-12: Hier stand „solange der Cursor noch dort steht". Geprüft
        # wird aber allein der Fensterwechsel — eigenes Tippen sieht Fleech nicht.
        hint_text="Ersetzt die zuletzt eingefügte Fassung durch das wörtliche "
                  "Transkript — für den Fall, dass die Bereinigung danebengriff. "
                  "Nur direkt danach und nur, solange du das Fenster nicht "
                  "gewechselt hast. Ob du selbst getippt hast, kann Fleech nicht "
                  "erkennen — dann lösche lieber von Hand.",
    )
    panel._add_hotkey_field(
        form, "Profil wechseln", "profile_hotkey", "profile", "",
        hint_text="Kurz drücken = nächstes Profil. GEDRÜCKT HALTEN = Liste aller "
                  "Profile am Mauszeiger, dort direkt anklicken. Sinnvoll auf "
                  "einer Maus-Zusatztaste (mouse4/mouse5) — deshalb ohne "
                  "Vorbelegung. Esc im Aufnahmefeld löscht eine Bindung.",
    )
    panel._add_hotkey_field(
        form, "Pause", "pause_hotkey", "pause", "ctrl+alt+space",
        hint_text="Hält die laufende Aufnahme an — währenddessen wird nichts "
                  "aufgezeichnet, du kannst also frei sprechen. Nochmal drücken "
                  "setzt dasselbe Diktat fort. Auch als Knopf in der Pille.",
    )
    mics = [(None, "Systemstandard")] + [(name, name) for name in panel._list_microphones()]
    panel._combo(
        form, "Mikrofon", mics, s.recording.microphone, "microphone",
        lambda v: setattr(s.recording, "microphone", v),
        hint_text="Wirkt ab der nächsten Aufnahme.",
    )
    panel._lines_editor(
        form, "Gesperrte Geräte", s.recording.blocked_devices, "microphone",
        lambda lines: setattr(s.recording, "blocked_devices", lines),
        placeholder="Stereomix\nCABLE Output\nAufnahmesumme",
        hint_text="Geräte, die nie als Mikrofon gelten sollen — ein Namensteil "
                  "je Zeile. Fleech erkennt die gängigen Loopback-Geräte schon "
                  "selbst; diese Liste ist für die Fälle, die dabei durchrutschen.",
        height=90,
    )
