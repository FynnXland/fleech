"""Hotkey-Serialisierung, -Normalisierung, HotkeyManager (Combos, Debounce)."""

import pytest
from pynput import keyboard

from fleech.hotkey import (
    HotkeyManager, HotkeySpec, keys_equal, parse_key, pynput_token,
)

Key = keyboard.Key
KeyCode = keyboard.KeyCode


# -- Serialisierung / Anzeige / Migration ---------------------------------------------


def test_single_key_roundtrip():
    spec = HotkeySpec.parse("f9")
    assert spec.key == "f9"
    assert spec.modifiers == frozenset()
    assert spec.serialize() == "f9"
    assert spec.display() == "F9"


def test_combination_canonical_order():
    # Reihenfolge egal beim Parsen, kanonisch beim Serialisieren.
    spec = HotkeySpec.parse("shift+ctrl+space")
    assert spec.serialize() == "ctrl+shift+space"
    assert spec.display() == "Ctrl + Shift + Space"


def test_modifier_variants_normalized():
    assert HotkeySpec.parse("ctrl_l+d").serialize() == "ctrl+d"
    assert HotkeySpec.parse("cmd+a").serialize() == "win+a"


def test_legacy_values_are_valid():
    # Alte settings.json ("f9"/"f10") parst ohne Migration.
    assert HotkeySpec.parse("f10").serialize() == "f10"


def test_parse_requires_exactly_one_main_key():
    with pytest.raises(ValueError):
        HotkeySpec.parse("ctrl+shift")   # nur Modifier
    with pytest.raises(ValueError):
        HotkeySpec.parse("a+b")          # zwei Haupttasten
    with pytest.raises(ValueError):
        HotkeySpec.parse("")


# -- pynput-Token-Normalisierung -------------------------------------------------------


def test_pynput_token_named_and_modifiers():
    assert pynput_token(Key.f10) == "f10"
    assert pynput_token(Key.space) == "space"
    assert pynput_token(Key.ctrl_l) == "ctrl"
    assert pynput_token(Key.shift_r) == "shift"
    assert pynput_token(Key.alt_gr) == "alt"


def test_pynput_token_uses_vk_even_with_ctrl_char():
    # Klassisches pynput-Problem: Ctrl+D liefert char='\x04'. vk bleibt korrekt.
    assert pynput_token(KeyCode(vk=0x44, char="\x04")) == "d"
    assert pynput_token(KeyCode.from_char("d")) == "d"
    assert pynput_token(KeyCode(vk=0x35, char="5")) == "5"


def test_pynput_token_extended_function_keys_and_unknown_vk():
    # Gaming-Tastaturen (Corsair G-Tasten via iCUE, Logitech G HUB) senden ihre
    # Zusatztasten typischerweise als F13–F24 — pynput kennt F21+ nur als nackten
    # VK-Code (KeyCode statt Key-Enum). Beide Wege muessen dasselbe Token liefern.
    assert pynput_token(Key.f13) == "f13"           # F13–F20: Key-Enum
    assert pynput_token(KeyCode(vk=0x7C)) == "f13"  # …oder als VK gemeldet
    assert pynput_token(KeyCode(vk=0x84)) == "f21"  # F21–F24: nur als VK
    assert pynput_token(KeyCode(vk=0x87)) == "f24"
    # Voellig exotische Zusatztasten bleiben als vk-Token bindbar.
    assert pynput_token(KeyCode(vk=0xE3)) == "vk227"


def test_extended_function_key_binding_roundtrip():
    # F13 als Aufnahme-Hotkey: Serialisierung, Anzeige und Manager-Matching.
    spec = HotkeySpec.parse("f13")
    assert spec.serialize() == "f13"
    assert spec.display() == "F13"
    vk_spec = HotkeySpec.parse("vk227")
    assert "227" in vk_spec.display()  # als „Sondertaste (227)" lesbar

    h = ManagerHarness({"dictate": "f13"})
    h.press(KeyCode(vk=0x7C))    # G-Taste sendet F13 als VK
    h.release(KeyCode(vk=0x7C))
    assert h.events == [("on", "dictate"), ("off", "dictate")]


# -- HotkeyManager: Einzeltaste, Combo, Debounce, Release ------------------------------


class ManagerHarness:
    def __init__(self, bindings):
        self.events = []
        self.mgr = HotkeyManager(
            on_activate=lambda n: self.events.append(("on", n)),
            on_deactivate=lambda n: self.events.append(("off", n)),
        )
        self.mgr.set_bindings({k: HotkeySpec.parse(v) for k, v in bindings.items()})

    def press(self, key):
        self.mgr._on_press(key)

    def release(self, key):
        self.mgr._on_release(key)


def test_single_key_activate_deactivate():
    h = ManagerHarness({"dictate": "f9"})
    h.press(Key.f9)
    h.release(Key.f9)
    assert h.events == [("on", "dictate"), ("off", "dictate")]


def test_missing_release_self_heals_after_grace():
    """Makro-/G-Tasten (iCUE) senden je nach Zuweisung nur KeyDOWN ohne KeyUP —
    das Binding bliebe sonst dauerhaft „aktiv" und jeder weitere Druck wuerde als
    Auto-Repeat verschluckt (real aufgetreten: F14 nach dem ersten Druck tot).
    Nach der Schonfrist zaehlt ein erneuter Druck als NEUER Druck."""
    h = ManagerHarness({"prompt_toggle": "f14"})
    clock = {"t": 0.0}
    h.mgr._clock = lambda: clock["t"]

    key = KeyCode(vk=0x7D)  # F14
    h.press(key)                     # Druck 1 — KEIN Release folgt (Makro-Taste)
    assert h.events == [("on", "prompt_toggle")]

    clock["t"] = 0.03                # echtes Auto-Repeat (~30 ms): unterdrueckt
    h.press(key)
    assert h.events == [("on", "prompt_toggle")]

    clock["t"] = 1.0                 # bewusster zweiter Druck → zaehlt wieder
    h.press(key)
    assert h.events == [("on", "prompt_toggle"), ("on", "prompt_toggle")]

    clock["t"] = 2.0                 # und jeder weitere auch
    h.press(key)
    assert h.events.count(("on", "prompt_toggle")) == 3


def test_single_key_autorepeat_debounced():
    h = ManagerHarness({"dictate": "f9"})
    h.press(Key.f9)
    h.press(Key.f9)   # Auto-Repeat
    h.press(Key.f9)
    h.release(Key.f9)
    assert h.events == [("on", "dictate"), ("off", "dictate")]


def test_combination_activates_only_with_all_modifiers():
    h = ManagerHarness({"dictate": "ctrl+shift+space"})
    h.press(Key.ctrl_l)
    h.press(Key.space)          # nur Ctrl+Space → kein Match (Shift fehlt)
    assert h.events == []
    h.release(Key.space)
    h.press(Key.shift_l)
    h.press(Key.space)          # jetzt Ctrl+Shift+Space
    assert h.events == [("on", "dictate")]
    h.release(Key.space)
    assert h.events[-1] == ("off", "dictate")


def test_combination_ends_when_modifier_released():
    h = ManagerHarness({"dictate": "ctrl+space"})
    h.press(Key.ctrl_l)
    h.press(Key.space)
    assert ("on", "dictate") in h.events
    h.release(Key.ctrl_l)       # Modifier los → Combo endet
    assert h.events[-1] == ("off", "dictate")


def test_exact_modifier_match_no_extra_modifiers():
    h = ManagerHarness({"dictate": "ctrl+space"})
    h.press(Key.ctrl_l)
    h.press(Key.shift_l)
    h.press(Key.space)          # Ctrl+Shift+Space ≠ Ctrl+Space
    assert h.events == []


def test_two_bindings_independent():
    h = ManagerHarness({"dictate": "f9", "math": "f10"})
    h.press(Key.f10)
    h.release(Key.f10)
    assert h.events == [("on", "math"), ("off", "math")]


def test_removing_binding_deactivates_it():
    h = ManagerHarness({"dictate": "f9"})
    h.press(Key.f9)
    h.mgr.set_bindings({})       # Bindung entfernt, waehrend aktiv
    assert h.events[-1] == ("off", "dictate")


# -- Maustasten -----------------------------------------------------------------------


def test_mouse_tokens_parse_serialize_display():
    from fleech.hotkey import HotkeySpec

    spec = HotkeySpec.parse("mouse5")
    assert spec.serialize() == "mouse5"
    assert spec.display() == "Maustaste 5"
    combo = HotkeySpec.parse("ctrl+mouse4")
    assert combo.serialize() == "ctrl+mouse4"
    assert combo.display() == "Ctrl + Maustaste 4"
    assert HotkeySpec.parse("mouse_middle").display() == "Mittlere Maustaste"


def test_pynput_mouse_token_mapping():
    import sys

    from pynput.mouse import Button

    from fleech.hotkey import pynput_mouse_token

    # Die Zusatztasten heissen je Backend anders: Windows x1/x2, X11 button8/button9.
    if sys.platform == "win32":
        assert pynput_mouse_token(Button.x2) == "mouse5"
        assert pynput_mouse_token(Button.x1) == "mouse4"
    else:
        assert pynput_mouse_token(Button.button9) == "mouse5"
        assert pynput_mouse_token(Button.button8) == "mouse4"
    assert pynput_mouse_token(Button.middle) == "mouse_middle"
    assert pynput_mouse_token(Button.left) is None
    assert pynput_mouse_token(Button.right) is None


def test_mouse_msg_token_win32():
    from fleech.hotkey import mouse_msg_token

    assert mouse_msg_token(0x0207, 0) == "mouse_middle"          # MBUTTONDOWN
    assert mouse_msg_token(0x020B, 1 << 16) == "mouse4"          # XBUTTONDOWN, X1
    assert mouse_msg_token(0x020C, 2 << 16) == "mouse5"          # XBUTTONUP, X2
    assert mouse_msg_token(0x0200, 0) is None                    # MOUSEMOVE
    assert mouse_msg_token(0x0201, 0) is None                    # LBUTTONDOWN


class _MouseHarness(ManagerHarness):
    def __init__(self, bindings):
        super().__init__(bindings)
        self.suppressed = []
        self.mgr._suppress_mouse_event = lambda: self.suppressed.append(True)

    def click(self, msg, mouse_data=0):
        class Data:
            mouseData = mouse_data

        self.mgr._win32_mouse_filter(msg, Data())


def test_mouse_listener_only_started_when_mouse_binding_exists(monkeypatch):
    """Der Low-Level-Maus-Hook feuert fuer JEDES Maus-Event (auch Bewegungen) —
    ohne gebundene Maustaste darf er gar nicht erst installiert werden."""
    import pynput

    from fleech.hotkey import HotkeyManager, HotkeySpec

    class FakeListener:
        def __init__(self, *a, **kw):
            self.running = False

        def start(self):
            self.running = True

        def stop(self):
            self.running = False

    created_mouse = []

    class FakeMouseListener(FakeListener):
        def __init__(self, *a, **kw):
            super().__init__()
            created_mouse.append(self)

    monkeypatch.setattr(pynput.keyboard, "Listener", FakeListener)
    monkeypatch.setattr(pynput.mouse, "Listener", FakeMouseListener)

    mgr = HotkeyManager(lambda n: None, lambda n: None)
    mgr.set_bindings({"dictate": HotkeySpec.parse("f9")})
    mgr.start()
    assert created_mouse == []                     # nur Tastatur → kein Maus-Hook

    mgr.set_bindings({"dictate": HotkeySpec.parse("mouse5")})
    assert len(created_mouse) == 1                 # live nachgezogen
    assert created_mouse[0].running

    mgr.set_bindings({"dictate": HotkeySpec.parse("f9"),
                      "math": HotkeySpec.parse("ctrl+mouse4")})
    assert len(created_mouse) == 1                 # blieb bestehen (weiter noetig)
    assert created_mouse[0].running

    mgr.set_bindings({"dictate": HotkeySpec.parse("f9")})
    assert not created_mouse[0].running            # kein Maus-Binding mehr → Hook weg
    mgr.stop()


def test_mouse_button_hold_cycle_with_suppression():
    h = _MouseHarness({"dictate": "mouse5"})
    h.click(0x020B, 2 << 16)   # X2 down
    h.click(0x020C, 2 << 16)   # X2 up
    assert h.events == [("on", "dictate"), ("off", "dictate")]
    assert len(h.suppressed) == 2  # down UND up unterdrueckt


def test_unbound_mouse_button_passes_through():
    h = _MouseHarness({"dictate": "mouse5"})
    h.click(0x020B, 1 << 16)   # X1 (mouse4) — nicht gebunden
    h.click(0x020C, 1 << 16)
    assert h.events == []
    assert h.suppressed == []  # normale Funktion bleibt erhalten


def test_mouse_with_keyboard_modifier_combo():
    h = _MouseHarness({"math": "ctrl+mouse5"})
    h.click(0x020B, 2 << 16)   # ohne Ctrl → kein Match, nicht unterdrueckt
    assert h.events == [] and h.suppressed == []
    h.press(Key.ctrl_l)
    h.click(0x020B, 2 << 16)   # Ctrl+Mouse5 → aktiviert + unterdrueckt
    assert h.events == [("on", "math")]
    h.click(0x020C, 2 << 16)
    assert h.events[-1] == ("off", "math")
    assert len(h.suppressed) == 2


def test_mouse_toggle_mode_end_to_end():
    from fleech.recording_control import RecordingController

    events = []
    rc = RecordingController("toggle",
                             on_start=lambda k: events.append(("start", k)),
                             on_stop=lambda k: events.append(("stop", k)))
    mgr = HotkeyManager(on_activate=rc.press, on_deactivate=rc.release)
    mgr._suppress_mouse_event = lambda: None
    mgr.set_bindings({"dictate": HotkeySpec.parse("mouse5")})

    class Data:
        mouseData = 2 << 16

    mgr._win32_mouse_filter(0x020B, Data())  # Klick 1: down
    mgr._win32_mouse_filter(0x020C, Data())  #          up
    assert events == [("start", "dictate")]  # Toggle: laeuft weiter
    mgr._win32_mouse_filter(0x020B, Data())  # Klick 2: down → stop
    mgr._win32_mouse_filter(0x020C, Data())
    assert events == [("start", "dictate"), ("stop", "dictate")]


# -- Legacy parse_key ------------------------------------------------------------------


def test_parse_key_single_and_combo_fallback():
    assert keys_equal(parse_key("f9"), Key.f9)
    # Combo im CLI → nur Haupttaste
    assert keys_equal(parse_key("ctrl+shift+f9"), Key.f9)


def test_parse_key_rejects_mouse_tokens_with_clear_message():
    with pytest.raises(ValueError, match="Desktop-App"):
        parse_key("mouse5")
