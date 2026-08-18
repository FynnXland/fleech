"""Aufnahme — Hotkeys, Mikrofon, Freihand.

Baut die Seite in das uebergebene SettingsPanel; die Widget-Bauer
(`panel._combo`, `panel._check`, ...) bleiben dort.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from ..theme import style_button
from ..widgets import WortListe
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
    _freihand_block(panel, s, form)

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


def _freihand_block(panel, s, form) -> None:
    """Der Freihand-Abschnitt der Seite.

    Eigene Funktion, seit `build()` mit dem Stillgelegt-Hinweis ueber die
    Zeilengrenze gewachsen ist. Die Antwort darauf ist laut CLAUDE.md ein
    eigener Ort fuer das Thema, nicht eine groessere Zahl im Test.
    """
    # -- Freihand: diktieren ohne Taste (F1) ---------------------------------
    # Bewusst HIER, direkt unter den Hotkeys: Es ist der zweite Weg, eine
    # Aufnahme zu starten — wer nach „wie beginne ich" sucht, schaut hier.
    from ...freihand import STILLGELEGT

    f = s.freihand
    if STILLGELEGT:
        form.addRow("", hint(
            "— Freihand —  vorerst abgeschaltet.\n"
            "Ein dauerhaft offenes Mikrofon per Startwort auszulösen war in einem "
            "Raum mit Nebengeräuschen nicht zuverlässig zu bekommen — und jeder "
            "Fehlstart tippt Text in das Fenster, in dem du gerade arbeitest.\n"
            "Was du eigentlich wolltest, kann der Bedienmodus „Anstupsen“ oben: "
            "einmal drücken, reden, es hört von selbst auf. Auslösen kann dort nur, "
            "wer die Taste drückt."
        ))
    else:
        form.addRow("", hint(
            "— Freihand —  Startwort sagen, sprechen, aufhören. Kommt zusätzlich "
            "zum Hotkey, ersetzt ihn nicht.\n"
            "Wenn dir am automatischen Ende gelegen ist: Der Bedienmodus "
            "„Anstupsen“ oben kann das auch — und kann nicht durch ein Video oder "
            "ein Gespräch im Raum ausgelöst werden."
        ))
    panel._freihand_cb = panel._check(
        form, "Freihand", f.aktiv and not STILLGELEGT, "freihand",
        lambda v: setattr(f, "aktiv", v),
        hint_text=("Vorerst abgeschaltet. Der Modus ist nicht entfernt, nur "
                   "stillgelegt — die Erklärung steht darüber."
                   if STILLGELEGT else
                   "Fleech hört dauerhaft auf das Startwort. Ein sparsamer "
                   "Sprach-Erkenner läuft dafür mit (~1 % CPU); Audio wird nie "
                   "gespeichert, erst ab dem Startwort überhaupt gesammelt. "
                   "Wirkt nach einem Neustart von Fleech."),
    )
    if STILLGELEGT:
        # Ausgegraut statt versteckt: Wer den Modus kennt, soll sehen, dass es
        # ihn noch gibt und warum er gerade nicht geht — ein spurlos
        # verschwundener Schalter wirkt wie ein Fehler.
        panel._freihand_cb.setEnabled(False)
    # Mehrere Startwörter: Welches Wort die eigene Aussprache zuverlässig
    # trifft, lässt sich nicht vorhersagen — mit zwei oder drei Kandidaten
    # nebeneinander entfällt das Herumprobieren mit einem einzigen.
    from ...freihand import zerlege_woerter

    def startwoerter_gesetzt(woerter, _ziel=f):
        _ziel.startwort = "\n".join(woerter)

    panel._startwort_liste = WortListe(
        zerlege_woerter(f.startwort),
        platzhalter="Startwort eintippen, dann Enter",
        on_changed=lambda w: (startwoerter_gesetzt(w), panel._changed("freihand")),
    )
    label_w, _ = panel._row_label(
        "Startwörter",
        "Ein Wort pro Zeile — Fleech startet bei jedem davon. Mehrsilbig und "
        "im Alltag selten, sonst löst es im Gespräch ständig versehentlich "
        "aus. „Kimono“ hat sich bewährt. Kunstwörter, die wie ein Alltagswort "
        "klingen, sind eine schlechte Wahl: „Fleech“ etwa kommt als „Fleisch“ "
        "an und würde beim Kochrezept auslösen.")
    form.addRow(label_w, panel._startwort_liste)
    if panel._wortprobe_fn is not None:
        # Ob ein Startwort taugt, hängt an der eigenen Aussprache — das lässt
        # sich nicht vorhersagen, nur ausprobieren. Zehn Sekunden statt eines
        # halben Tages Rätselraten, warum Freihand nicht reagiert.
        panel._startwort_probe_btn = style_button(
            QPushButton("Startwort einsprechen …"), "ghost")
        panel._startwort_probe_btn.setToolTip(
            "Sprich das Startwort einmal beiläufig ins Mikrofon. Fleech zeigt, "
            "was ankommt und ob Freihand darauf anspringen würde."
        )
        panel._startwort_probe_btn.clicked.connect(panel._startwort_probe_starten)
        form.addRow("", panel._startwort_probe_btn)
    panel._combo(
        form, "Genauigkeit", [
            ("diktat", "Wie beim Diktat — empfohlen"),
            ("tiny", "Sparsam (schwache Rechner)"),
            ("base", "Sparsam, etwas genauer"),
            ("small", "Sparsam, am genauesten (langsam)"),
        ],
        getattr(f, "modell", "diktat") or "diktat", "freihand",
        lambda v: setattr(f, "modell", v),
        hint_text="Wie genau auf das Startwort gehört wird. „Wie beim Diktat“ "
                  "nimmt dasselbe Modell, das deine Diktate erkennt — es liegt "
                  "ohnehin auf der Grafikkarte, ist am genauesten und mit 140 ms "
                  "je Prüfung auch am schnellsten. Die sparsamen Varianten "
                  "rechnen stattdessen auf dem Prozessor: für Rechner ohne "
                  "brauchbare Grafikkarte, dafür deutlich schlechter im Hören. "
                  "Wirkt nach einem Neustart von Fleech.",
    )
    panel._text_field(
        form, "Abbruchwort", f.abbruchwort, "freihand",
        lambda v: setattr(f, "abbruchwort", v),
        hint_text="Fällt dieses Wort im Diktat, wird verworfen statt eingefügt. "
                  "Es startet bewusst KEINE neue Aufnahme — sonst würde ein "
                  "Versprecher zur Endlosschleife.",
    )
    # „Sprechpause bis Ende" steht jetzt oben beim Bedienmodus: Sie beendet
    # auch den Anstupsen-Modus, und derselbe Wert an zwei Stellen zu regeln
    # wäre eine Einladung, ihn zweimal verschieden einzustellen.
    panel._check(
        form, "Fehlersuche", getattr(f, "diagnose", False), "freihand",
        lambda v: setattr(f, "diagnose", v),
        hint_text="NUR zur Fehlersuche: Hebt die geprüften Startwort-Fenster "
                  "als Tondateien auf, damit nachvollziehbar wird, was beim "
                  "Lauschen wirklich ankommt. Es werden zwei Sekunden je "
                  "Prüfung gespeichert, höchstens 60 Stück, in "
                  "%APPDATA%\\Fleech\\freihand-diagnose. Danach bitte wieder "
                  "ausschalten — sonst wird dauerhaft Ton mitgeschrieben. "
                  "Wirkt nach einem Neustart von Fleech.",
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

    if STILLGELEGT:
        # Den ganzen Block ausgrauen, nicht nur den Schalter: Ein aktives
        # Startwort-Feld unter einem toten Schalter sieht aus, als koennte man
        # damit etwas erreichen. Nur die Widgets, die das Panel ohnehin
        # festhaelt — ein Durchlauf durch das Layout waere ein Umweg ueber eine
        # Qt-API, die je nach Bindung anders heisst.
        for name in ("_freihand_cb", "_startwort_liste", "_startwort_probe_btn"):
            widget = getattr(panel, name, None)
            if widget is not None:
                widget.setEnabled(False)
