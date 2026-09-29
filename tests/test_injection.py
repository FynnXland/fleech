"""Cursor-Rueckkehr in der Injection — ohne echte Tastendruecke/Clipboard-Zugriffe.

Die Low-Level-Aktionen (Clipboard lesen/schreiben, Strg+V) sind als Methoden
gekapselt und werden hier gestubbt, damit der Test die Reihenfolge Restore→Paste
verifizieren kann, ohne die reale Zwischenablage oder Tastatur zu beruehren.
"""

from __future__ import annotations

from fleech.injection import TextInjector


def _instrument(inj: TextInjector) -> list:
    """Ersetzt die Low-Level-Aktionen durch Rekorder; gibt die Ereignisliste zurueck."""
    events: list = []
    inj._get_clipboard = lambda: None
    inj._set_clipboard = lambda text: events.append(("clip", text))
    inj._paste_keystroke = lambda: events.append(("paste",))
    return events


def test_inject_restores_focus_before_paste():
    restored: list = []
    inj = TextInjector(restore_clipboard=False,
                       focus_restorer=lambda target: restored.append(target) or True)
    events = _instrument(inj)
    inj.set_focus_target(("fenster", (100, 200)))

    inj.inject("Hallo Welt")

    assert restored == [("fenster", (100, 200))]     # Ziel-Feld wurde zurueckgeholt
    kinds = [e[0] for e in events]
    assert kinds == ["clip", "paste"]                # Clipboard gesetzt, dann Paste
    # Restore muss VOR dem Paste passieren (sonst landet Strg+V im falschen Feld).
    assert restored and events[-1] == ("paste",)


def test_inject_without_target_does_not_restore():
    calls: list = []
    inj = TextInjector(restore_clipboard=False,
                       focus_restorer=lambda target: calls.append(target) or True)
    _instrument(inj)
    inj.set_focus_target(None)                       # Option aus / kein Ziel

    inj.inject("Text")

    assert calls == []                               # ohne Ziel keine Fokus-Aktion


def test_inject_no_restorer_is_safe():
    inj = TextInjector(restore_clipboard=False)      # focus_restorer=None (Default)
    events = _instrument(inj)
    inj.set_focus_target(object())                   # Ziel gesetzt, aber kein Restorer

    inj.inject("Text")                               # darf nicht crashen

    assert ("paste",) in events


def test_focusrestore_fallbacks_never_crash():
    import sys

    from fleech.ui import focusrestore

    # Plattformunabhaengig: None-Ziele sind immer False, nie ein Crash.
    assert focusrestore.restore_foreground(None) is False
    assert focusrestore.restore_focus_target(None) is False
    # Windows (GetGUIThreadInfo) UND Linux/X11 (EWMH) liefern ein Ziel mit
    # gueltigem Fenster-Handle — oder None (kein Fenster/kein Display), nie einen Crash.
    target = focusrestore.capture_focus_target()
    assert target is None or target.hwnd


# -- Aktive Clipboard-Verifikation ------------------------------------------------
# Ersetzt die fruehere blinde 50-ms-Pause. Electron-Apps/VMs/Remote-Desktop
# bestaetigen das Clipboard-Update spaeter — dort pastete Fleech vorher den ALTEN
# Inhalt. Hier mit kuenstlich verzoegertem Mock-Backend geprueft.


class SlowClipboard:
    """Mock-Zwischenablage, die den geschriebenen Wert erst nach N Lesungen meldet."""

    def __init__(self, delay_reads: int = 5, previous: str = "alter Inhalt"):
        self.value = previous
        self._pending = None
        self._left = 0
        self.delay_reads = delay_reads
        self.reads = 0

    def read(self):
        self.reads += 1
        if self._pending is not None:
            self._left -= 1
            if self._left <= 0:
                self.value, self._pending = self._pending, None
        return self.value

    def write(self, text):
        self._pending, self._left = text, self.delay_reads


def _wire(inj, clip):
    events = []
    inj._get_clipboard = clip.read
    inj._set_clipboard = lambda t: (clip.write(t), events.append(("clip", t)))
    inj._paste_keystroke = lambda: events.append(("paste", clip.value))
    return events


def test_paste_waits_until_clipboard_confirms():
    """Strg+V darf erst raus, wenn die Zwischenablage den neuen Text wirklich fuehrt."""
    clip = SlowClipboard(delay_reads=5)
    inj = TextInjector(restore_clipboard=False, paste_delay_ms=0)
    events = _wire(inj, clip)

    inj.inject("Neuer Text")

    paste = [e for e in events if e[0] == "paste"]
    assert paste and paste[0][1] == "Neuer Text"   # nicht mehr der alte Inhalt
    assert clip.reads >= 5                          # es wurde tatsaechlich gepollt


def test_paste_happens_even_if_clipboard_never_confirms():
    """Fail-Open: bestaetigt die Zwischenablage nie, wird trotzdem eingefuegt —
    lieber ein Versuch als gar kein Text."""
    import fleech.injection as inj_mod

    clip = SlowClipboard(delay_reads=10**6)
    inj = TextInjector(restore_clipboard=False, paste_delay_ms=0)
    events = _wire(inj, clip)
    original = inj_mod._CLIPBOARD_TIMEOUT_S
    inj_mod._CLIPBOARD_TIMEOUT_S = 0.06            # Test kurz halten
    try:
        inj.inject("Neuer Text")
    finally:
        inj_mod._CLIPBOARD_TIMEOUT_S = original
    assert any(e[0] == "paste" for e in events)


def test_unreadable_clipboard_does_not_stall():
    """Ist die Zwischenablage nicht lesbar, darf NICHT in den Timeout gelaufen
    werden — kurz warten und einfuegen (Verhalten wie vor der Verifikation)."""
    import time

    inj = TextInjector(restore_clipboard=False, paste_delay_ms=0)
    events = []
    inj._get_clipboard = lambda: None
    inj._set_clipboard = lambda t: events.append(("clip", t))
    inj._paste_keystroke = lambda: events.append(("paste",))

    started = time.monotonic()
    inj.inject("Text")
    assert time.monotonic() - started < 0.3        # deutlich unter dem 400-ms-Deckel
    assert ("paste",) in events


# -- Nur TEXT wird gesichert (Befund B-10) ----------------------------------------
# Vorher wurde blind `paste_text()` gesichert und nach dem Einfuegen zurueck-
# geschrieben. Bei einem kopierten Bild lieferte das Lesen "" — und der leere
# String landete danach in der Ablage. Der Screenshot war weg.


def _clipboard_lauf(hat_text: bool, vorher: str = "alter Text"):
    inj = TextInjector(restore_clipboard=True, paste_delay_ms=0)
    events = []
    inj._clipboard_has_text = lambda: hat_text
    inj._get_clipboard = lambda: vorher
    inj._set_clipboard = lambda t: events.append(t)
    inj._paste_keystroke = lambda: events.append("PASTE")
    inj._await_clipboard = lambda text: True     # Verifikation ist hier nicht das Thema
    inj.inject("Diktierter Text")
    return events


def test_alter_text_wird_wie_bisher_wiederhergestellt():
    assert _clipboard_lauf(hat_text=True) == ["Diktierter Text", "PASTE", "alter Text"]


def test_ein_kopiertes_bild_wird_nicht_ueberschrieben():
    """Kein Text in der Ablage → nach dem Einfuegen wird nichts zurueckgeschrieben."""
    assert _clipboard_lauf(hat_text=False) == ["Diktierter Text", "PASTE"]


def test_has_text_ist_auf_jeder_plattform_beantwortbar():
    """Die Nahtstelle muss immer eine Antwort geben — ein Fehler beim Abfragen
    darf das Einfuegen nie reissen (fail-open: dann wie bisher verfahren)."""
    from fleech.clipboard import has_text

    assert isinstance(has_text(), bool)


# -- Spät fertig und der Nutzer ist woanders -------------------------------------------


def _spaet(inj: TextInjector, sekunden: float, monkeypatch) -> None:
    """Das Aufnahmeende `sekunden` in die Vergangenheit legen."""
    import fleech.injection as inj_mod

    jetzt = inj_mod.time.monotonic()
    inj._aufnahmeende = jetzt - sekunden


def test_spaet_und_woanders_klickt_nicht_hinein(monkeypatch):
    """Am 2026-09-24 kam ein Diktat 8,5 min nach dem Sprechen an; 19 s vorher
    hatte ein Spiel angefangen. Fleech haette das Ziel-Fenster nach vorn geholt,
    hineingeklickt und Strg+V gedrueckt. Jetzt: Text in die Zwischenablage, nichts
    anfassen — und der Aufrufer erfaehrt es."""
    wiederhergestellt = []
    inj = TextInjector(restore_clipboard=True,
                       focus_restorer=lambda t: wiederhergestellt.append(t) or True)
    events = _instrument(inj)
    inj._get_clipboard = lambda: "Der Text"          # bestaetigt die Ablage sofort
    inj.vordergrund_pruefer = lambda t: False         # anderes Fenster vorn
    inj.set_focus_target(("fenster", (100, 200)))
    _spaet(inj, 60, monkeypatch)

    assert inj.inject("Der Text") is False
    assert ("paste",) not in events                   # kein Strg+V
    assert wiederhergestellt == []                    # kein Fenster nach vorn geholt
    assert ("clip", "Der Text") in events             # aber in der Zwischenablage


def test_spaet_aber_noch_im_feld_wird_normal_eingefuegt(monkeypatch):
    """Wer bei einem langen Diktat im Feld wartet, bekommt seinen Text wie immer —
    das Alter allein entscheidet nicht."""
    inj = TextInjector(restore_clipboard=False, focus_restorer=lambda t: True)
    events = _instrument(inj)
    inj.vordergrund_pruefer = lambda t: True          # Ziel-Fenster ist noch vorn
    inj.set_focus_target(("fenster", (100, 200)))
    _spaet(inj, 600, monkeypatch)

    assert inj.inject("Langes Diktat") is True
    assert ("paste",) in events


def test_rechtzeitig_und_woanders_holt_das_feld_zurueck_wie_bisher(monkeypatch):
    """Die Cursor-Rueckkehr bleibt, was sie war: kurz weggeklickt → zurueckgeholt."""
    wiederhergestellt = []
    inj = TextInjector(restore_clipboard=False,
                       focus_restorer=lambda t: wiederhergestellt.append(t) or True)
    events = _instrument(inj)
    inj.vordergrund_pruefer = lambda t: False
    inj.set_focus_target(("fenster", (100, 200)))
    _spaet(inj, 5, monkeypatch)

    assert inj.inject("Kurz") is True
    assert wiederhergestellt and ("paste",) in events


def test_ohne_auskunft_ueber_den_vordergrund_bleibt_alles_beim_alten(monkeypatch):
    """Linux oder ein Fehler in der Abfrage: None heisst unbekannt, nicht „woanders"."""
    inj = TextInjector(restore_clipboard=False, focus_restorer=lambda t: True)
    events = _instrument(inj)
    inj.vordergrund_pruefer = lambda t: None
    inj.set_focus_target(("fenster", (100, 200)))
    _spaet(inj, 600, monkeypatch)

    assert inj.inject("Text") is True and ("paste",) in events
