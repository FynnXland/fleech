from fleech.recording_control import RecordingController


def make(mode):
    events = []
    c = RecordingController(
        mode,
        on_start=lambda kind: events.append(("start", kind)),
        on_stop=lambda kind: events.append(("stop", kind)),
    )
    return c, events


def test_hold_press_release():
    c, events = make("hold")
    c.press("dictate")
    assert c.active
    c.release("dictate")
    assert events == [("start", "dictate"), ("stop", "dictate")]
    assert not c.active


def test_hold_auto_repeat_ignored():
    c, events = make("hold")
    c.press("dictate")
    c.press("dictate")  # Auto-Repeat waehrend des Haltens
    c.press("dictate")
    c.release("dictate")
    assert events == [("start", "dictate"), ("stop", "dictate")]


def test_toggle_two_presses():
    c, events = make("toggle")
    c.press("dictate")
    c.release("dictate")   # Loslassen stoppt im Toggle NICHT
    assert c.active
    c.press("dictate")     # zweiter Druck stoppt und verarbeitet
    c.release("dictate")
    assert events == [("start", "dictate"), ("stop", "dictate")]


def test_toggle_holding_key_does_not_immediately_stop():
    c, events = make("toggle")
    c.press("dictate")
    c.press("dictate")  # Auto-Repeat des ersten (gehaltenen) Drucks
    c.press("dictate")
    assert c.active     # laeuft noch — Repeat hat nicht gestoppt
    c.release("dictate")
    c.press("dictate")
    assert events == [("start", "dictate"), ("stop", "dictate")]


def test_toggle_other_hotkey_during_recording_is_ignored():
    c, events = make("toggle")
    c.press("dictate")
    c.release("dictate")
    c.press("math")      # anderer Hotkey mitten in der Aufnahme: ignoriert
    c.release("math")
    assert events == [("start", "dictate")]
    c.press("dictate")
    assert events[-1] == ("stop", "dictate")


def test_math_kind_is_passed_through():
    c, events = make("hold")
    c.press("math")
    c.release("math")
    assert events == [("start", "math"), ("stop", "math")]


def test_mode_switch_stops_active_recording():
    c, events = make("toggle")
    c.press("dictate")
    c.release("dictate")
    c.set_mode("hold")
    assert events == [("start", "dictate"), ("stop", "dictate")]
    assert c.mode == "hold"


def test_ui_toggle_works_in_any_mode():
    c, events = make("hold")
    c.start_via_ui()
    assert c.active
    c.start_via_ui()
    assert events == [("start", "dictate"), ("stop", "dictate")]


def test_invalid_mode_keeps_current():
    c, _ = make("hold")
    c.set_mode("quatsch")
    assert c.mode == "hold"


def test_cancel_discards_without_processing():
    c, events = make("toggle")
    c.press("dictate")
    c.release("dictate")
    assert c.cancel() == "dictate"
    assert events == [("start", "dictate")]  # KEIN stop-Event → keine Verarbeitung
    assert not c.active


def test_cancel_when_idle_returns_none():
    c, events = make("hold")
    assert c.cancel() is None
    assert events == []


def test_hold_release_after_cancel_is_noop():
    # Nutzer haelt F9, klickt Overlay-X, laesst dann erst los.
    c, events = make("hold")
    c.press("dictate")
    assert c.cancel() == "dictate"
    c.release("dictate")  # darf keinen stop ausloesen
    assert events == [("start", "dictate")]
