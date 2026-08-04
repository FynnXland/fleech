"""Aufnahme — Hotkeys, Mikrofon, Freihand.

Baut die Seite in das uebergebene SettingsPanel; die Widget-Bauer
(`panel._combo`, `panel._check`, ...) bleiben dort.
"""

from __future__ import annotations

from .common import hint


def build(panel) -> None:
    s = panel.settings
    _, form = panel._page()
    form.addRow("", hint(
        "Wie du das Diktat auslöst — und welches Mikrofon genutzt wird."
    ))
    panel._combo(
        form, "Bedienmodus",
        [("hold", "Hold-to-talk (halten)"), ("toggle", "Toggle (drücken/drücken)")],
        s.recording.mode, "recording", lambda v: setattr(s.recording, "mode", v),
        help_map={
            "hold": "Taste halten = aufnehmen, loslassen = fertig.",
            "toggle": "Einmal drücken = Start, nochmal = fertig.",
        },
    )
    panel._add_hotkey_field(
        form, "Diktat-Hotkey", "hotkey", "dictate", "f9",
        hint_text="„Aufnehmen“ klicken, dann Taste, Kombination oder Maustaste "
                  "4/5/Mitte drücken. Esc = abbrechen.",
    )
    # Das Feld „Mathe-Umschalt" ist mit v3.7.2 entfallen: Den Modus gibt es seit
    # v3.0.0 nicht mehr (Formeln entstehen im lokalen Parser), die Taste war also
    # seit sieben Versionen wirkungslos einstellbar.
    panel._add_hotkey_field(
        form, "KI-Prompting", "prompt_toggle_hotkey", "prompt_toggle", "ctrl+alt+p",
        hint_text="Nur WÄHREND einer Aufnahme: dieses Diktat wird als strukturierter "
                  "KI-Prompt formuliert. Dauerhaft umschalten: Punkt in der Pille.",
    )
    panel._add_hotkey_field(
        form, "Rohtext einsetzen", "undo_hotkey", "undo", "ctrl+alt+z",
        hint_text="Ersetzt die zuletzt eingefügte Fassung durch das wörtliche "
                  "Transkript — für den Fall, dass die Bereinigung danebengriff. "
                  "Nur direkt danach und solange der Cursor noch dort steht.",
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
    # -- Freihand: diktieren ohne Taste (F1) ---------------------------------
    # Bewusst HIER, direkt unter den Hotkeys: Es ist der zweite Weg, eine
    # Aufnahme zu starten — wer nach „wie beginne ich" sucht, schaut hier.
    f = s.freihand
    form.addRow("", hint(
        "— Freihand —  Startwort sagen, sprechen, aufhören. Kommt zusätzlich "
        "zum Hotkey, ersetzt ihn nicht."
    ))
    panel._freihand_cb = panel._check(
        form, "Freihand", f.aktiv, "freihand",
        lambda v: setattr(f, "aktiv", v),
        hint_text="Fleech hört dauerhaft auf das Startwort. Ein sparsamer "
                  "Sprach-Erkenner läuft dafür mit (~1 % CPU); Audio wird nie "
                  "gespeichert, erst ab dem Startwort überhaupt gesammelt. "
                  "Wirkt nach einem Neustart von Fleech.",
    )
    panel._text_field(
        form, "Startwort", f.startwort, "freihand",
        lambda v: setattr(f, "startwort", v),
        hint_text="Mehrsilbig und im Alltag selten — sonst löst es im Gespräch "
                  "ständig versehentlich aus. „Kimono“ hat sich bewährt.",
    )
    panel._combo(
        form, "Genauigkeit", [
            ("tiny", "Schnell (schwache Rechner)"),
            ("base", "Ausgewogen — empfohlen"),
            ("small", "Genau (langsamer)"),
        ],
        getattr(f, "modell", "base") or "base", "freihand",
        lambda v: setattr(f, "modell", v),
        hint_text="Wie genau auf das Startwort gehört wird. „Schnell“ überhört "
                  "es je nach Aussprache („Kimono“ wurde als „Kimu“ verstanden); "
                  "„Genau“ braucht rund 1,5 Sekunden je Prüfung. Wirkt nach "
                  "einem Neustart von Fleech.",
    )
    panel._text_field(
        form, "Abbruchwort", f.abbruchwort, "freihand",
        lambda v: setattr(f, "abbruchwort", v),
        hint_text="Fällt dieses Wort im Diktat, wird verworfen statt eingefügt. "
                  "Es startet bewusst KEINE neue Aufnahme — sonst würde ein "
                  "Versprecher zur Endlosschleife.",
    )
    panel._spin(
        form, "Sprechpause bis Ende", f.stille_s, 1.0, 4.0, "freihand",
        lambda v: setattr(f, "stille_s", v),
        hint_text="So lange still = Diktat fertig. Kürzer schneidet Denkpausen "
                  "ab, länger lässt dich warten.",
    )
    panel._lines_editor(
        form, "Nicht lauschen in", f.ausgeschlossene_apps, "freihand",
        lambda lines: setattr(f, "ausgeschlossene_apps", lines),
        placeholder="Teams.exe\nDiscord.exe\ncs2.exe",
        hint_text="Programme, in denen Freihand ruht — ein Prozessname je "
                  "Zeile. Für Spiele und Besprechungen: Dort ist Sprache im "
                  "Raum die Regel, und eine Fehlauslösung fällt mitten hinein.",
        height=80,
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
