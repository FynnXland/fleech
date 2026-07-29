"""Timing-Verhalten der aktiven Clipboard-Verifikation (W1-3).

Der reale Fehlerfall war: Strg+V kam VOR dem Clipboard-Update an und fuegte den
ALTEN Inhalt ein — in Electron-Apps (VS Code, Discord) und VMs. Die Verifikation
liest deshalb zurueck, statt blind zu warten. Diese Tests bauen ein Clipboard-
Backend mit kuenstlicher Latenz nach, damit die Zeitachse ueberhaupt pruefbar ist:
ohne sie wuerde jeder Stub sofort den richtigen Wert liefern und die gesamte
Wartelogik waere ungetestet.

Die Uhr ist gefaked — die Tests duerfen nicht real warten (sonst laufen sie in
die Sekunden) und muessen unabhaengig von der Maschinenlast reproduzierbar sein.
"""

from __future__ import annotations

import pytest

from fleech import injection
from fleech.injection import TextInjector


class FakeClock:
    """Monotone Uhr, die nur durch sleep() vorrueckt — kein echtes Warten."""

    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class LaggyClipboard:
    """Clipboard, das den geschriebenen Wert erst nach `delay` Sekunden zeigt.

    delay=None bedeutet: der Wert erscheint nie (haengendes Backend)."""

    def __init__(self, clock: FakeClock, delay: float | None = 0.0,
                 unreadable: bool = False):
        self.clock = clock
        self.delay = delay
        self.unreadable = unreadable
        self.pending: str | None = None
        self.visible_at = 0.0
        self.reads = 0

    def set(self, text: str) -> None:
        self.pending = text
        self.visible_at = (self.clock.now + self.delay
                           if self.delay is not None else float("inf"))

    def get(self):
        self.reads += 1
        if self.unreadable:
            return None
        if self.pending is not None and self.clock.now >= self.visible_at:
            return self.pending
        return "ALTER INHALT"


def _wire(monkeypatch, clock: FakeClock, clip: LaggyClipboard) -> tuple[TextInjector, list]:
    monkeypatch.setattr(injection.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(injection.time, "sleep", clock.sleep)
    events: list = []
    inj = TextInjector(restore_clipboard=False)
    inj._get_clipboard = clip.get
    inj._set_clipboard = lambda text: (clip.set(text), events.append(("clip", text)))[1]
    inj._paste_keystroke = lambda: events.append(("paste", clip.get()))
    return inj, events


def test_paste_wartet_bis_der_text_wirklich_steht(monkeypatch):
    """Der Kern: 200 ms Verzoegerung (Electron/VM) — gepastet wird trotzdem der NEUE
    Text, nicht der alte Inhalt."""
    clock = FakeClock()
    clip = LaggyClipboard(clock, delay=0.2)
    inj, events = _wire(monkeypatch, clock, clip)

    assert inj._await_clipboard("Neuer Text") is False  # noch nichts geschrieben
    clip.set("Neuer Text")
    assert inj._await_clipboard("Neuer Text") is True

    inj.inject("Neuer Text")
    paste = [e for e in events if e[0] == "paste"][0]
    assert paste[1] == "Neuer Text"


def test_schnelles_clipboard_wartet_nicht_unnoetig(monkeypatch):
    """Steht der Wert sofort, darf gar nicht geschlafen werden — die Verifikation
    soll im Normalfall SCHNELLER sein als die alten pauschalen 50 ms."""
    clock = FakeClock()
    clip = LaggyClipboard(clock, delay=0.0)
    inj, _events = _wire(monkeypatch, clock, clip)

    clip.set("Sofort da")
    assert inj._await_clipboard("Sofort da") is True
    assert clock.slept == []
    assert clip.reads == 1


def test_timeout_pastet_trotzdem_fail_open(monkeypatch):
    """Haengendes Backend: nach dem Deckel wird eingefuegt statt aufzugeben —
    lieber ein Versuch als gar kein Text."""
    clock = FakeClock()
    clip = LaggyClipboard(clock, delay=None)   # erscheint nie
    inj, events = _wire(monkeypatch, clock, clip)

    start = clock.now
    assert inj._await_clipboard("Kommt nie") is False
    waited = clock.now - start
    assert waited >= injection._CLIPBOARD_TIMEOUT_S
    # Deckel eingehalten (eine Poll-Runde Toleranz) — nicht endlos warten.
    assert waited <= injection._CLIPBOARD_TIMEOUT_S + injection._CLIPBOARD_POLL_S

    inj.inject("Kommt nie")
    assert any(e[0] == "paste" for e in events)


def test_unlesbares_clipboard_faellt_auf_kurze_wartezeit_zurueck(monkeypatch):
    """Nicht lesbar (Rechte/Backend) → Verifikation unmoeglich. Dann EINMAL kurz
    warten wie frueher, statt in den vollen Timeout zu laufen."""
    clock = FakeClock()
    clip = LaggyClipboard(clock, delay=0.0, unreadable=True)
    inj, _events = _wire(monkeypatch, clock, clip)

    assert inj._await_clipboard("Egal") is False
    assert clock.slept == [injection._CLIPBOARD_SETTLE_S]
    assert clip.reads == 1


def test_lesefehler_zaehlt_wie_unlesbar(monkeypatch):
    """Eine werfende Clipboard-Anbindung darf das Diktat nie reissen."""
    clock = FakeClock()
    clip = LaggyClipboard(clock, delay=0.0)
    inj, _events = _wire(monkeypatch, clock, clip)

    def boom():
        raise OSError("Zwischenablage belegt")

    inj._get_clipboard = boom
    assert inj._await_clipboard("Egal") is False


@pytest.mark.parametrize("delay", [0.02, 0.06, 0.19, 0.39])
def test_verschiedene_latenzen_bestaetigen_immer(monkeypatch, delay):
    """Fuzz ueber die Latenzen unterhalb des Deckels: alle muessen bestaetigen."""
    clock = FakeClock()
    clip = LaggyClipboard(clock, delay=delay)
    inj, _events = _wire(monkeypatch, clock, clip)

    clip.set("Text")
    assert inj._await_clipboard("Text") is True


def test_alte_zwischenablage_wird_nach_dem_paste_zurueckgeschrieben(monkeypatch):
    """Reihenfolge unter Latenz: sichern → setzen → paste → zuruecksetzen."""
    clock = FakeClock()
    clip = LaggyClipboard(clock, delay=0.05)
    clip.pending = "VORHER"
    clip.visible_at = 0.0
    inj, events = _wire(monkeypatch, clock, clip)
    inj.restore_clipboard = True

    inj.inject("Diktat")

    kinds = [e[0] for e in events]
    assert kinds == ["clip", "paste", "clip"]
    assert events[0][1] == "Diktat"
    assert events[-1][1] == "VORHER"      # Original wiederhergestellt
    assert events[1][1] == "Diktat"       # und trotzdem der NEUE Text gepastet
