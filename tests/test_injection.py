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
