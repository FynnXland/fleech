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


# -- Drei Threads, ein Zustand (Befund D-8) ---------------------------------------


def test_stille_wache_und_tastendruck_stoppen_nie_doppelt():
    """Befund D-8: `_active_kind` wurde geprueft und dann gesetzt — ohne Schloss.

    Bedient wird der Controller aus drei Threads: pynput-Listener (Hotkey),
    GUI-Timer (Stille-Wache im Anstupsen-Modus) und Qt-Signale von Pille/Tray. In
    20.000 nachgestellten Laeufen kamen 420 doppelte `on_stop` durch — der zweite
    mit `kind=None`, und der laeuft den vollen Stopp-Weg: zweiter Stoppton, Pille
    auf „nichts erkannt", Worker-Thread mit 0 Samples.

    Genau der Alltagsfall: Im Anstupsen-Modus greift die Stille, waehrend der
    Nutzer die Taste zum vorzeitigen Beenden drueckt (der Modus sieht das vor).
    """
    import sys
    import threading

    alt = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)          # Thread-Wechsel provozieren
    try:
        for _ in range(2000):
            c, events = make("nudge")
            c.press("dictate")           # Aufnahme laeuft
            c.release("dictate")
            los = threading.Barrier(2)

            def wache():
                los.wait()
                c.stop_if_active()       # GUI-Timer: Stille erkannt

            def taste():
                los.wait()
                c.press("dictate")       # pynput: vorzeitig beenden

            threads = [threading.Thread(target=wache), threading.Thread(target=taste)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            stopps = [e for e in events if e[0] == "stop"]
            assert len(stopps) == 1, events
            assert stopps[0][1] == "dictate", events   # nie mit kind=None
    finally:
        sys.setswitchinterval(alt)


def test_abbruch_aus_dem_start_callback_verklemmt_nicht():
    """`_on_record_start` ruft in seinen Abbruchzweigen `cancel()` — also aus dem
    on_start-Callback heraus wieder in den Controller hinein (Befund D-10). Mit
    einem einfachen Lock waere das ein Deadlock; deshalb steht dort ein RLock."""
    abgebrochen = []
    c = RecordingController(
        "hold",
        on_start=lambda kind: abgebrochen.append(c.cancel()),
        on_stop=lambda kind: abgebrochen.append(("stop", kind)),
    )
    c.press("dictate")
    assert abgebrochen == ["dictate"]
    assert not c.active


def test_verworfener_druck_hinterlaesst_eine_spur(caplog):
    """Der `_key_down`-Waechter ist die zweite Stelle, an der ein Druck lautlos
    verschwand. Verwerfen bleibt richtig — schweigen nicht."""
    from fleech.recording_control import RecordingController

    starts = []
    c = RecordingController("toggle", on_start=starts.append, on_stop=lambda k: None)
    c.press("dictate")
    assert starts == ["dictate"]
    with caplog.at_level("INFO"):
        c.press("dictate")          # Release ging verloren → zweiter Druck faellt raus
    assert "dictate" in caplog.text
