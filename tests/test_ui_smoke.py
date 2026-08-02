"""Qt-Smoke-Tests (offscreen): Widgets bauen, Zustaende schalten, Persistenz-Callbacks.

Laeuft ohne Display (QT_QPA_PLATFORM=offscreen). Prueft keine Optik, aber dass
Overlay-Modi, Statuswechsel und das Settings-Fenster ohne Fehler funktionieren.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from fleech.ui.state import AppState, StateBus  # noqa: E402
from fleech.usersettings import UserSettings  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_statebus_transitions(qapp):
    bus = StateBus()
    seen = []
    bus.state_changed.connect(seen.append)
    bus.set_state(AppState.LISTENING)
    bus.set_state(AppState.PROCESSING)
    bus.set_state(AppState.IDLE)
    qapp.processEvents()
    assert seen == [AppState.LISTENING, AppState.PROCESSING, AppState.IDLE]


def test_overlay_visibility_modes_and_position_persistence(qapp):
    from fleech.ui.overlay_qt import OverlayWindow

    saved = []
    s = UserSettings().overlay
    o = OverlayWindow(s, on_geometry_changed=lambda: saved.append(True))

    # Default-Position wurde gesetzt (rechtsseitig): x/y nicht mehr None.
    assert s.x is not None and s.y is not None

    # during_activity: idle → versteckt, listening → sichtbar
    o.set_app_state(AppState.LISTENING)
    assert o.isVisible()
    o.set_app_state(AppState.IDLE)
    qapp.processEvents()
    assert not o.isVisible()

    # off: bleibt versteckt, auch bei Aktivitaet
    s.visibility = "off"
    o.apply_settings()
    o.set_app_state(AppState.LISTENING)
    assert not o.isVisible()

    # always: sofort sichtbar
    s.visibility = "always"
    o.apply_settings()
    assert o.isVisible()

    # Tooltip-Feedback crasht nicht
    o.set_mode_line("Hold | Fokus: soft_duck")
    o.set_feedback("eingefuegt")
    o.close()


def test_overlay_presets_and_reset(qapp):
    from fleech.ui.overlay_qt import PILL_WIDTH, OverlayWindow, preset_position

    saved = []
    s = UserSettings().overlay
    o = OverlayWindow(s, on_geometry_changed=lambda: saved.append(True))

    o.apply_preset("bottom_center")
    assert s.position == "bottom_center"
    from PySide6.QtWidgets import QApplication
    geom = QApplication.primaryScreen().availableGeometry()
    exp_x, exp_y = preset_position("bottom_center", geom, o.width(), o.height())
    assert (s.x, s.y) == (exp_x, exp_y)
    assert saved  # persistiert

    # Reset → zurueck auf right_center
    o.apply_preset("left_center")
    o.reset_position()
    assert s.position == "right_center"
    o.close()


def test_overlay_custom_position_survives_apply_settings(qapp):
    from fleech.ui.overlay_qt import OverlayWindow

    s = UserSettings().overlay
    s.position = "custom"
    s.x, s.y = 123, 456
    o = OverlayWindow(s)
    o.apply_settings()  # darf custom nicht ueberschreiben
    assert (s.x, s.y) == (123, 456)
    o.close()


def test_overlay_legacy_settings_migrate_to_custom(qapp):
    from fleech.ui.overlay_qt import OverlayWindow

    # Alte settings.json: x/y gesetzt, position-Feld fehlt (== "").
    s = UserSettings().overlay
    s.position = ""
    s.x, s.y = 200, 300
    o = OverlayWindow(s)  # __init__ ruft apply_settings
    assert s.position == "custom"
    assert (s.x, s.y) == (200, 300)  # Position bleibt erhalten
    o.close()


def test_overlay_hat_keinen_befehls_knopf_mehr(qapp):
    """Der »-Knopf (Befehls-Modus) ist aus der Pille entfernt — er wurde nie
    benutzt und hat den Platz belegt, den jetzt die Pause hat. Das gesprochene
    Safe-Word bleibt davon unberuehrt (Routing, nicht UI)."""
    from fleech.ui.overlay_qt import OverlayWindow

    o = OverlayWindow(UserSettings().overlay)
    assert not hasattr(o, "_trigger_btn")
    assert not hasattr(o, "trigger_requested")
    assert not hasattr(o, "set_trigger_available")
    o.close()


def _hotkey_fake(recording: bool):
    """Fake-DesktopApp fuer die Hotkey-Routing-Tests (mit/ohne laufende Aufnahme)."""
    import types

    from fleech.ui.desktop import DesktopApp

    calls = {"prompt": [], "sound": [], "press": [], "release": []}
    fake = types.SimpleNamespace(
        _prompt_latched=False,
        _prompt_oneshot=False,
        overlay=types.SimpleNamespace(
            set_prompt_latched=lambda v: calls["prompt"].append(v),
        ),
        notifier=types.SimpleNamespace(sound=lambda e: calls["sound"].append(e)),
        settings=types.SimpleNamespace(math=types.SimpleNamespace(enabled=True)),
        controller=types.SimpleNamespace(
            active=recording,
            press=lambda n: calls["press"].append(n),
            release=lambda n: calls["release"].append(n),
        ),
        recorder=types.SimpleNamespace(recording=recording),
    )
    for m in ("_toggle_prompt_latch", "_toggle_prompt_oneshot",
              "_cycle_overlay_mode", "_safe_overlay_latch"):
        setattr(fake, m, types.MethodType(getattr(DesktopApp, m), fake))
    return fake, calls


def test_punkt_schaltet_reihum_durch_die_profile(qapp):
    """Der Punkt war erst ein Modus-Zyklus (Mathe/Prompting), dann funktionslos.
    Jetzt waehlt er das Profil — inklusive Station „automatisch" am Ende."""
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import APP_STANDARD

    gezeigt = []
    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=types.SimpleNamespace(
            enabled=True, active="",
            items=[{"name": "Standard", "default": True},
                   {"name": "E-Mail", "mode": "email"}])),
        overlay=types.SimpleNamespace(show_profile=gezeigt.append),
    )
    fake.current_app = lambda: ""        # kein App-Filter in diesem Test
    fake.profile_names = lambda: DesktopApp.profile_names(fake)
    fake.active_profile_name = lambda: DesktopApp.active_profile_name(fake)
    fake._set_profile = lambda n: DesktopApp._set_profile(fake, n)
    fake.settings.save = lambda: None
    DesktopApp.cycle_profile(fake)
    assert fake.settings.profiles.active == "Standard"
    DesktopApp.cycle_profile(fake)
    assert fake.settings.profiles.active == "E-Mail"
    DesktopApp.cycle_profile(fake)
    assert fake.settings.profiles.active == ""          # zurueck auf automatisch
    assert gezeigt[-1].startswith(APP_STANDARD)


def test_profilwechsel_geht_auch_waehrend_der_aufnahme(qapp):
    """Erst beim Verarbeiten wird aufgeloest — deshalb darf man mitten im
    Sprechen noch entscheiden, ob daraus eine Mail wird."""
    import types

    from fleech.ui.desktop import DesktopApp

    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=types.SimpleNamespace(
            enabled=True, active="", items=[{"name": "E-Mail", "mode": "email"}])),
        overlay=types.SimpleNamespace(show_profile=lambda n: None),
        recorder=types.SimpleNamespace(recording=True),
        controller=types.SimpleNamespace(active=True),
    )
    fake.current_app = lambda: ""        # kein App-Filter in diesem Test
    fake.profile_names = lambda: DesktopApp.profile_names(fake)
    fake.active_profile_name = lambda: DesktopApp.active_profile_name(fake)
    fake._set_profile = lambda n: DesktopApp._set_profile(fake, n)
    fake.settings.save = lambda: None
    DesktopApp.cycle_profile(fake)
    assert fake.settings.profiles.active == "E-Mail"


def test_overlay_edit_mode_keeps_pill_visible(qapp):
    from fleech.ui.overlay_qt import OverlayWindow

    s = UserSettings().overlay  # during_activity
    o = OverlayWindow(s)
    assert not o.is_edit_mode()

    assert o.toggle_edit_mode() is True
    assert o.is_edit_mode() and o.isVisible()
    # idle wuerde normalerweise verstecken — im Edit-Modus nicht
    o.set_app_state(AppState.IDLE)
    qapp.processEvents()
    assert o.isVisible()

    assert o.toggle_edit_mode() is False
    qapp.processEvents()
    assert not o.is_edit_mode() and not o.isVisible()  # zurueck auf normale Sichtbarkeit
    o.close()


def test_overlay_transcript_caption_respects_toggle(qapp):
    from fleech.ui.overlay_qt import OverlayWindow

    s = UserSettings().overlay
    s.show_transcript = True
    o = OverlayWindow(s)
    o.show_transcript("Das ist der erkannte Text.")
    assert o._caption.isVisible()
    o._caption.hide()

    s.show_transcript = False
    o.show_transcript("Wird nicht gezeigt.")
    assert not o._caption.isVisible()

    # Im Edit-Modus wird das Transkript ebenfalls nicht eingeblendet
    s.show_transcript = True
    o.toggle_edit_mode()
    o._caption.hide()
    o.show_transcript("Auch nicht im Edit-Modus.")
    # Caption zeigt hoechstens den Edit-Hinweis, nicht den Transkripttext
    assert "erkannt" not in o._caption._label.text()
    o.toggle_edit_mode()
    o.close()


def test_overlay_dropped_tail_warns_even_without_transcript(qapp):
    """Eine Loeschung muss ankommen, auch wenn die Transkript-Blase AUS ist.

    Genau dieser Fehler wurde schon einmal gemeldet: Der Hinweis hing an der
    Transkript-Anzeige und war deshalb bei abgeschalteter Blase nie zu sehen. Wer
    sie ausblendet, will weniger Bestaetigung — nicht weniger Sicherheit.
    """
    from fleech.ui.overlay_qt import OverlayWindow

    s = UserSettings().overlay
    s.show_transcript = False
    o = OverlayWindow(s)
    o.show_dropped_tail("Polski Der Konflikt L conflicts des Klausulnotation Kurv")
    assert o._caption.isVisible()
    text = o._caption._label.text()
    assert "verworfen" in text and "Polski" in text
    o._caption.hide()

    # Ist die Blase AN, reist der Hinweis mit dem Transkript — nicht als zweite
    # Blase, die die erste sofort ueberschreibt.
    s.show_transcript = True
    o.show_dropped_tail("Polski Der Konflikt")
    o.show_transcript("Der echte Text.")
    both = o._caption._label.text()
    assert "Der echte Text." in both and "verworfen" in both
    o.close()


def _expected_btn(pill_h: int) -> int:
    # Symmetrische Ableitung wie in OverlayWindow._apply_scale: Button fuellt die
    # Hoehe zwischen gleichen oberen/unteren Raendern.
    vmargin = max(5, round(pill_h * 0.18))
    return pill_h - 2 * vmargin


def test_overlay_size_presets_scale_pill_and_buttons(qapp):
    from fleech.ui.overlay_qt import PILL_HEIGHT, PILL_WIDTH, OverlayWindow

    s = UserSettings().overlay
    s.size = "large"
    o = OverlayWindow(s)
    large_h = round((PILL_HEIGHT + s.edge_top + s.edge_bottom) * 1.2)
    exp_w = round((PILL_WIDTH + s.edge_left + s.edge_right) * 1.2)  # Rand nach aussen
    assert (o.width(), o.height()) == (exp_w, large_h)
    # Button-Groesse haengt an der INNEREN Hoehe (ohne Nutzer-Raender).
    assert o._cancel_btn.width() == _expected_btn(round(PILL_HEIGHT * 1.2))
    # Buttons sind quadratisch und passen mit gleichem Rand oben/unten (Symmetrie).
    assert o._cancel_btn.width() == o._cancel_btn.height()
    assert o._cancel_btn.height() <= large_h
    # Alle Zellen (Mathe-Dot, X, ✓, Pause) gleich groß → linke/rechte Seite symmetrisch.
    assert o._math_dot.width() == o._cancel_btn.width() == o._pause_btn.width()

    s.size = "compact"
    o.apply_settings()
    compact_h = round((PILL_HEIGHT + s.edge_top + s.edge_bottom) * 0.85)
    exp_w = round((PILL_WIDTH + s.edge_left + s.edge_right) * 0.85)
    assert (o.width(), o.height()) == (exp_w, compact_h)
    assert o._finish_btn.width() == _expected_btn(round(PILL_HEIGHT * 0.85))

    # Vier separat einstellbare Raender: Fenster waechst exakt um die Randwerte.
    s.size = "normal"
    s.edge_left, s.edge_right, s.edge_top, s.edge_bottom = 20, 4, 6, 2
    o.apply_settings()
    assert (o.width(), o.height()) == (PILL_WIDTH + 20 + 4, PILL_HEIGHT + 6 + 2)
    o.close()


def test_waveform_gain_amplifies_level(qapp):
    """Der Nutzer-Regler wirkt weiterhin — jetzt zusaetzlich zum Auto-Gain, das
    leise Mikrofone von sich aus sichtbar macht (v2.2.0)."""
    from fleech.ui.overlay_qt import WaveformWidget

    gain = {"v": 1.0}
    w = WaveformWidget(lambda: 0.02, gain_provider=lambda: gain["v"])
    w.set_state(AppState.LISTENING)
    for _ in range(20):          # Auto-Gain einschwingen lassen
        w._tick()
    base = w._levels[-1]
    gain["v"] = 3.0
    w._tick()
    assert w._levels[-1] > base   # lauter Regler = hoeherer Ausschlag
    # Gain-Fehler faellt sicher auf 1.0 zurueck
    w._gain = lambda: (_ for _ in ()).throw(RuntimeError("kaputt"))
    w._tick()  # darf nicht raisen


def test_overlay_follow_timer_tracks_setting_and_visibility(qapp):
    from fleech.ui.overlay_qt import OverlayWindow

    s = UserSettings().overlay
    s.visibility = "always"
    s.follow_mouse_screen = True
    o = OverlayWindow(s)
    qapp.processEvents()
    assert o._follow_timer.isActive()        # sichtbar + Setting an

    s.follow_mouse_screen = False
    o.apply_settings()
    assert not o._follow_timer.isActive()    # Setting aus → Timer aus

    s.follow_mouse_screen = True
    o.apply_settings()
    assert o._follow_timer.isActive()
    o.hide()
    assert not o._follow_timer.isActive()    # unsichtbar → Timer aus
    # Tick waehrend Edit-Modus/Drag ist ein No-Op (kein Kampf gegen das Ziehen)
    o._edit_mode = True
    o._follow_mouse_screen_tick()
    o.close()


def test_overlay_live_text_only_while_listening_and_enabled(qapp):
    from fleech.ui.overlay_qt import OverlayWindow

    s = UserSettings().overlay
    s.live_preview = True
    o = OverlayWindow(s)
    o.set_app_state(AppState.LISTENING)
    o.show_live_text("hallo welt das ist die vorschau")
    assert not o._caption.isHidden()
    assert "vorschau" in o._caption._label.text()

    # PROCESSING beendet die Live-Anzeige (finales Transkript kommt separat)
    o.set_app_state(AppState.PROCESSING)
    assert o._caption.isHidden()
    o.show_live_text("zu spaet")             # nicht mehr LISTENING → ignoriert
    assert o._caption.isHidden()

    # Feature aus → nie anzeigen
    o.set_app_state(AppState.LISTENING)
    o._caption.hide()
    s.live_preview = False
    o.show_live_text("aus")
    assert o._caption.isHidden()
    o.close()


def test_live_preview_is_single_line_and_shows_recent_words(qapp):
    from fleech.ui.overlay_qt import OverlayWindow

    s = UserSettings().overlay
    s.live_preview = True
    o = OverlayWindow(s)
    o.set_app_state(AppState.LISTENING)
    long = " ".join(f"wort{i}" for i in range(60))
    o.show_live_text(long)
    # Einzeilig (kein Umbruch) und links elidiert (nur die letzten Woerter tragen).
    assert o._caption._label.wordWrap() is False
    assert o._caption._label.text().startswith("…")
    assert "wort59" in o._caption._label.text()   # das zuletzt erkannte Wort ist dabei
    assert "wort0 " not in o._caption._label.text()
    o.close()


def test_live_preview_hidden_on_cancel(qapp):
    """Regression: X (Abbrechen) waehrend der Live-Vorschau ging LISTENING→IDLE ohne
    PROCESSING — die sticky Blase blieb bis zum Neustart haengen."""
    from fleech.ui.overlay_qt import OverlayWindow

    s = UserSettings().overlay
    s.live_preview = True
    o = OverlayWindow(s)
    o.set_app_state(AppState.LISTENING)
    o.show_live_text("hallo das laeuft gerade auf")
    assert not o._caption.isHidden()

    o.set_app_state(AppState.IDLE)   # Abbruch-Pfad
    assert o._caption.isHidden()
    assert o._caption_is_live is False
    o.close()


def test_final_transcript_survives_idle_after_live_preview(qapp):
    """Nach echtem Diktat kommt transcript_ready (setzt _is_live=False) VOR
    set_state(IDLE) — das Endtranskript darf dann nicht faelschlich versteckt werden."""
    from fleech.ui.overlay_qt import OverlayWindow

    s = UserSettings().overlay
    s.live_preview = True
    s.show_transcript = True
    o = OverlayWindow(s)
    o.set_app_state(AppState.LISTENING)
    o.show_live_text("zwischenstand")
    o.set_app_state(AppState.PROCESSING)     # Live-Vorschau weg
    o.show_transcript("Das ist das fertige Ergebnis.")   # Endtext (is_live=False)
    o.set_app_state(AppState.IDLE)           # darf den Endtext NICHT verstecken
    assert not o._caption.isHidden()
    assert "fertige Ergebnis" in o._caption._label.text()
    o.close()


def test_overlay_command_armed_visuals_and_reset(qapp):
    from fleech.ui.overlay_qt import OverlayWindow

    o = OverlayWindow(UserSettings().overlay)
    o.set_app_state(AppState.LISTENING)
    assert o._command_armed is False

    o.set_command_armed(True)
    assert o._command_armed is True
    assert o._wave._armed is True                # Waveform in Befehls-Optik
    assert not o.grab().isNull()                 # paintEvent (Akzent-Rahmen) crasht nicht

    o.set_app_state(AppState.PROCESSING)         # Aufnahme endet → Optik zurueck
    assert o._command_armed is False
    assert o._wave._armed is False

    o.set_app_state(AppState.LISTENING)          # neue Aufnahme startet neutral
    assert o._command_armed is False
    o.close()


def test_desktop_preview_text_arms_overlay_on_trigger(qapp):
    import types

    from fleech.ui.desktop import DesktopApp

    armed = []
    fake = types.SimpleNamespace(
        overlay=types.SimpleNamespace(
            show_live_text=lambda t: None,
            set_command_armed=lambda v: armed.append(v),
        ),
        pipeline=types.SimpleNamespace(trigger_word="Kimono"),
    )
    DesktopApp._on_preview_text(fake, "also der text laeuft und kimono mach mal")
    assert armed == [True]
    DesktopApp._on_preview_text(fake, "ganz normaler text ohne signalwort")
    assert armed == [True]                       # kein weiterer Aufruf


def test_preview_streamer_start_stop_wiring(qapp, monkeypatch):
    """Race-Guard: der Start-Worker (laedt Modell, dauert Sekunden) darf den Streamer
    nur starten, wenn die Aufnahme noch laeuft und kein Stop dazwischenkam.
    Threads laufen hier ECHT (mit join) — kein globales threading.Thread-Patching."""
    import types

    import fleech.overlay as overlay_mod
    from fleech.ui.desktop import DesktopApp

    class FakeStreamer:
        def __init__(self, **kw):
            self.started = False

        def start(self):
            self.started = True

        def stop(self):
            self.started = False

    monkeypatch.setattr(overlay_mod, "PreviewStreamer", FakeStreamer)

    started_threads = []
    fake = types.SimpleNamespace(
        bus=types.SimpleNamespace(state=AppState.LISTENING,
                                  preview_text=types.SimpleNamespace(emit=lambda t: None)),
        recorder=types.SimpleNamespace(snapshot=lambda: None),
        config=types.SimpleNamespace(audio=types.SimpleNamespace(samplerate=16000)),
        _preview=None, _preview_gen=0,
        _ensure_preview_model=lambda: types.SimpleNamespace(transcribe_segments=lambda a: []),
    )

    import threading as _threading

    real_thread = _threading.Thread

    class TrackingThread(real_thread):
        def start(self):
            started_threads.append(self)
            super().start()

    monkeypatch.setattr("fleech.ui.desktop.threading.Thread", TrackingThread)

    DesktopApp._start_preview_async(fake)
    for t in started_threads:
        t.join(timeout=3)
    assert fake._preview.started               # Aufnahme laeuft → gestartet

    DesktopApp._stop_preview(fake)
    assert not fake._preview.started

    # Stop WAEHREND des Ladens: gen wird entwertet → Worker startet nicht mehr.
    fake.bus.state = AppState.IDLE
    DesktopApp._start_preview_async(fake)
    for t in started_threads:
        t.join(timeout=3)
    assert not fake._preview.started


def test_overlay_pill_opacity_and_fixed_size(qapp):
    from fleech.ui.overlay_qt import PILL_HEIGHT, PILL_WIDTH, OverlayWindow

    s = UserSettings().overlay
    s.opacity = 0.5
    o = OverlayWindow(s)
    assert o.windowOpacity() == pytest.approx(0.5, abs=0.01)  # Qt quantisiert auf 1/255
    # Pille fix — plus einstellbarer horizontaler Rand (verbreitert nach aussen).
    assert (o.width(), o.height()) == (
        PILL_WIDTH + s.edge_left + s.edge_right,
        PILL_HEIGHT + s.edge_top + s.edge_bottom,
    )
    o.close()


def test_overlay_buttons_emit_cancel_and_finish(qapp):
    from fleech.ui.overlay_qt import OverlayWindow

    o = OverlayWindow(UserSettings().overlay)
    events = []
    o.cancel_requested.connect(lambda: events.append("cancel"))
    o.finish_requested.connect(lambda: events.append("finish"))
    o.set_app_state(AppState.LISTENING)  # Buttons nur waehrend Aufnahme aktiv
    assert o._cancel_btn.isEnabled() and o._finish_btn.isEnabled()
    o._cancel_btn.click()
    o._finish_btn.click()
    assert events == ["cancel", "finish"]
    o.set_app_state(AppState.PROCESSING)
    assert not o._cancel_btn.isEnabled() and not o._finish_btn.isEnabled()
    o.close()


def test_overlay_buttons_never_take_focus(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.overlay_qt import OverlayWindow

    o = OverlayWindow(UserSettings().overlay)
    assert o._cancel_btn.focusPolicy() == Qt.NoFocus
    assert o._finish_btn.focusPolicy() == Qt.NoFocus
    assert bool(o.windowFlags() & Qt.WindowDoesNotAcceptFocus)
    o.close()


def test_waveform_renders_all_states(qapp):
    from fleech.ui.overlay_qt import WaveformWidget

    levels = iter([0.05, 0.2, 0.4])
    w = WaveformWidget(lambda: next(levels, 0.0))
    w.resize(90, 28)
    for state in (AppState.IDLE, AppState.LISTENING, AppState.PROCESSING):
        w.set_state(state)
        if state is AppState.LISTENING:
            w._tick()
            w._tick()
        assert not w.grab().isNull()  # paintEvent laeuft ohne Crash
    assert max(w._levels) > 0  # Pegel kam an


def test_waveform_timer_only_runs_while_animating(qapp):
    """Idle-Punktreihe ist statisch — der 50-ms-Tick darf nur waehrend
    Aufnahme/Verarbeitung laufen (sonst dauerhafte Hintergrundlast bei
    Sichtbarkeit "immer")."""
    from fleech.ui.overlay_qt import WaveformWidget

    w = WaveformWidget(lambda: 0.1)
    w.show()
    qapp.processEvents()
    assert not w._timer.isActive()          # sichtbar + idle → kein Tick
    w.set_state(AppState.LISTENING)
    assert w._timer.isActive()
    w.set_state(AppState.PROCESSING)
    assert w._timer.isActive()
    w.set_state(AppState.IDLE)
    assert not w._timer.isActive()          # zurueck zu statisch
    w.hide()
    w.set_state(AppState.LISTENING)         # unsichtbar → trotz busy kein Tick
    assert not w._timer.isActive()
    w.close()


def test_progress_caption_shows_and_clears(qapp):
    """Waehrend eines Kaltstarts (~13 s) sah man bisher nur „verarbeitet". Der
    Zwischenschritt erscheint jetzt in der Blase ueber der Pille — und bleibt danach
    nicht stehen."""
    from fleech.ui.overlay_qt import OverlayWindow
    from fleech.ui.state import AppState

    s = UserSettings().overlay
    s.visibility = "always"
    o = OverlayWindow(s)

    o.set_app_state(AppState.PROCESSING)
    o.show_progress("KI-Modell wird geladen …")
    qapp.processEvents()
    assert o._caption_is_status is True
    assert not o._caption.isHidden()

    # Endtranskript loest den Hinweis ab (und wird vom IDLE-Wechsel nicht versteckt).
    o.show_transcript("Der fertige Text.")
    assert o._caption_is_status is False
    o.set_app_state(AppState.IDLE)
    qapp.processEvents()
    assert not o._caption.isHidden()

    # Ohne Endtranskript (z. B. Abbruch) raeumt der Zustandswechsel selbst auf.
    o.set_app_state(AppState.PROCESSING)
    o.show_progress("Formel wird berechnet …")
    assert o._caption_is_status is True
    o.set_app_state(AppState.IDLE)
    qapp.processEvents()
    assert o._caption_is_status is False
    assert o._caption.isHidden()

    # Ausserhalb der Verarbeitung erscheint gar kein Hinweis.
    o.show_progress("sollte nicht erscheinen")
    assert o._caption_is_status is False
    o.close()


def test_fallback_flash_marks_check_and_caption_amber(qapp):
    """Rohtext-Fallback war bisher nur hörbar (Ton) und in der Statuszeile lesbar —
    an der Pille selbst gab es kein Signal. Jetzt: Haken amber + amber Blasenrahmen,
    danach automatisch zurueck auf Akzent."""
    from fleech.ui.overlay_qt import _ACCENT, _PROMPT_ACCENT, OverlayWindow

    s = UserSettings().overlay
    s.visibility = "always"
    o = OverlayWindow(s)

    o.flash_fallback()
    qapp.processEvents()
    assert o._fallback_active is True
    o.show_transcript("Roher Text ohne Bereinigung.")
    qapp.processEvents()
    assert o._caption._accent_color == _PROMPT_ACCENT      # amber gerahmt

    o._clear_fallback_flash()                              # Timer-Ablauf simulieren
    o.show_transcript("Sauber bereinigter Text.")
    qapp.processEvents()
    assert o._fallback_active is False
    assert o._caption._accent_color is None                # wieder randlos
    # Der Edit-Hinweis nutzt weiterhin den Brand-Akzent (accent=True).
    o._caption.show_above(o.frameGeometry(), "Ziehen …", sticky=True, accent=True)
    assert o._caption._accent_color == _ACCENT
    o.close()


def test_overlapping_processings_are_serialized():
    """Zwei Diktat-Verarbeitungen duerfen sich nie ueberlappen — sonst schreiben beide
    auf denselben DocumentTracker und der Bezugspunkt fuer Safe-Word-Ersetzungen
    stimmt nicht mehr. Der zweite Lauf wartet, statt parallel zu starten."""
    import threading
    import time as _t
    import types

    from fleech.ui.desktop import DesktopApp

    events = []
    fake = types.SimpleNamespace(
        _process_lock=threading.Lock(),
        _llms_unloaded=False,
        bus=types.SimpleNamespace(
            progress=types.SimpleNamespace(emit=lambda _t: None),
        ),
    )

    def slow(audio, math_mode, force_command=False, math_jobs=None,
             prompt_oneshot=False):
        events.append(("start", audio))
        _t.sleep(0.15)
        events.append(("ende", audio))

    fake._process_locked = slow
    run = lambda tag: DesktopApp._process(fake, tag, False)

    threads = [threading.Thread(target=run, args=(tag,)) for tag in ("A", "B")]
    threads[0].start()
    _t.sleep(0.03)          # B startet, waehrend A noch laeuft
    threads[1].start()
    for th in threads:
        th.join()

    # Streng abwechselnd start/ende — kein verschachteltes start,start,ende,ende.
    assert [e[0] for e in events] == ["start", "ende", "start", "ende"]
    assert events[0][1] == events[1][1]      # A vollstaendig vor B
    assert events[2][1] == events[3][1]


def _keep_warm_fake(monkeypatch, gaming: bool = False):
    """Fake-DesktopApp fuer die Warmhalte-/Entlade-Tests (synchrone Threads)."""
    import time as _t
    import types

    import fleech.ui.desktop as desktop_mod
    from fleech.ui.desktop import DesktopApp

    calls = {"warm": [], "unload": []}

    class SyncThread:
        def __init__(self, target=None, daemon=None, args=()):
            self._target, self._args = target, args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(desktop_mod.threading, "Thread", SyncThread)

    fake = types.SimpleNamespace(
        settings=UserSettings(),
        _last_dictation=_t.monotonic(),
        _keep_llm_warm=lambda: calls["warm"].append(1),
        _unload_llms_async=lambda reason: calls["unload"].append(reason),
        notifier=types.SimpleNamespace(
            context=object(),
            policy=types.SimpleNamespace(gaming_active=lambda ctx: gaming),
        ),
    )
    fake._idle_unload_window_s = types.MethodType(
        DesktopApp._idle_unload_window_s, fake
    )
    return fake, calls


def test_keep_warm_tick_respects_mode(monkeypatch):
    """Smart-Warmhaltung: Tick haelt nur innerhalb des (einstellbaren) Idle-Fensters
    warm; danach wird AKTIV entladen (RAM frei). "off" nie, "always" immer."""
    import time as _t

    from fleech.ui.desktop import DesktopApp

    fake, calls = _keep_warm_fake(monkeypatch)

    fake.settings.advanced.llm_keep_warm = "off"
    DesktopApp._keep_warm_tick(fake)
    assert calls == {"warm": [], "unload": []}

    fake.settings.advanced.llm_keep_warm = "smart"
    DesktopApp._keep_warm_tick(fake)
    assert calls["warm"] == [1]              # frisch aktiv → warmhalten

    window = fake.settings.advanced.llm_idle_unload_minutes * 60
    fake._last_dictation = _t.monotonic() - (window + 60)
    DesktopApp._keep_warm_tick(fake)
    assert calls["warm"] == [1]              # Idle-Fenster abgelaufen → nicht warmhalten
    assert calls["unload"] == ["Leerlauf"]   # … sondern AKTIV entladen

    fake.settings.advanced.llm_keep_warm = "always"
    DesktopApp._keep_warm_tick(fake)
    assert calls["warm"] == [1, 1]           # dauerhaft: unabhaengig vom Fenster


def test_idle_unload_window_reads_setting():
    """Das Idle-Fenster kommt aus der Einstellung (Minuten → Sekunden), 0 erlaubt."""
    import types

    from fleech.ui.desktop import DesktopApp

    fake = types.SimpleNamespace(settings=UserSettings())
    fake.settings.advanced.llm_idle_unload_minutes = 3
    assert DesktopApp._idle_unload_window_s(fake) == 180
    fake.settings.advanced.llm_idle_unload_minutes = 45
    assert DesktopApp._idle_unload_window_s(fake) == 2700


def test_keep_warm_tick_unloads_while_gaming(monkeypatch):
    """Laeuft ein Spiel (Gaming-Erkennung), entlaedt der Smart-Modus die Modelle
    SOFORT — auch mitten im Aktivitaets-Fenster. RAM zaehlt beim Zocken."""
    from fleech.ui.desktop import DesktopApp

    fake, calls = _keep_warm_fake(monkeypatch, gaming=True)
    fake.settings.advanced.llm_keep_warm = "smart"
    DesktopApp._keep_warm_tick(fake)         # letztes Diktat gerade eben — egal: Spiel!
    assert calls["warm"] == []
    assert calls["unload"] == ["Spiel erkannt"]

    # "always" respektiert den ausdruecklichen Nutzerwunsch (kein Auto-Entladen).
    fake.settings.advanced.llm_keep_warm = "always"
    DesktopApp._keep_warm_tick(fake)
    assert calls["warm"] == [1]


def test_unload_llms_async_is_idempotent(monkeypatch):
    """Nach einem Entladen feuert der 4-min-Tick nicht weiter Requests gegen ein
    ohnehin leeres Ollama; erst ein Aufwaermen erlaubt das naechste Entladen."""
    import types

    import fleech.ui.desktop as desktop_mod
    from fleech.ui.desktop import DesktopApp

    unloads = []

    class SyncThread:
        def __init__(self, target=None, daemon=None, args=()):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(desktop_mod.threading, "Thread", SyncThread)
    import fleech.llm.client as client_mod
    monkeypatch.setattr(client_mod, "ollama_unload", lambda ep: unloads.append(ep))

    fake = types.SimpleNamespace(
        _llms_unloaded=False,
        _llm_endpoints=lambda: ["ep1", "ep2"],
    )
    DesktopApp._unload_llms_async(fake, "Test")
    assert unloads == ["ep1", "ep2"]
    DesktopApp._unload_llms_async(fake, "Test")   # zweiter Aufruf: No-op
    assert unloads == ["ep1", "ep2"]
    assert fake._llms_unloaded is True


def test_waveform_provider_errors_are_swallowed(qapp):
    from fleech.ui.overlay_qt import WaveformWidget

    def boom():
        raise RuntimeError("mic weg")

    w = WaveformWidget(boom)
    w.set_state(AppState.LISTENING)
    w._tick()  # darf nicht raisen
    assert max(w._levels) == 0.0


def test_overlay_focus_override(qapp):
    from fleech.ui.overlay_qt import OverlayWindow

    s = UserSettings().overlay
    s.visibility = "always"
    o = OverlayWindow(s)
    assert o.isVisible()

    # Gaming: "activity_only" — idle versteckt, Aufnahme sichtbar
    o.set_focus_override("activity_only")
    assert not o.isVisible()
    o.set_app_state(AppState.LISTENING)
    assert o.isVisible()
    o.set_app_state(AppState.IDLE)
    assert not o.isVisible()

    # "hidden": auch bei Aufnahme unsichtbar
    o.set_focus_override("hidden")
    o.set_app_state(AppState.LISTENING)
    assert not o.isVisible()

    # Override aufgehoben: Nutzereinstellung "always" gilt wieder
    o.set_app_state(AppState.IDLE)
    o.set_focus_override(None)
    assert o.isVisible()
    # Nutzereinstellungen wurden nie veraendert
    assert s.visibility == "always"
    o.close()


def test_tray_icons_for_all_states(qapp):
    from fleech.ui.tray import _STATE_COLOR, _make_icon

    for state, color in _STATE_COLOR.items():
        assert not _make_icon(color).isNull(), state


def _key_event(key, modifiers=None, vk=0, autorep=False):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    mods = modifiers if modifiers is not None else Qt.NoModifier
    if vk:
        return QKeyEvent(QKeyEvent.KeyPress, key, mods, 0, vk, 0, "", autorep, 1)
    return QKeyEvent(QKeyEvent.KeyPress, key, mods, "", autorep, 1)


def test_hotkey_recorder_single_key(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.keyPressEvent(_key_event(Qt.Key_F10))
    assert d.result_spec is not None
    assert d.result_spec.serialize() == "f10"
    assert not d.cleared


def test_hotkey_recorder_combination(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    # Nur Modifier: noch nicht final
    d.keyPressEvent(_key_event(Qt.Key_Control, Qt.ControlModifier))
    assert d.result_spec is None
    # Haupttaste mit Ctrl+Shift
    d.keyPressEvent(_key_event(Qt.Key_Space, Qt.ControlModifier | Qt.ShiftModifier))
    assert d.result_spec.serialize() == "ctrl+shift+space"


def test_hotkey_recorder_letter_uses_native_vk(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.keyPressEvent(_key_event(Qt.Key_D, Qt.ControlModifier, vk=0x44))
    assert d.result_spec.serialize() == "ctrl+d"


def test_hotkey_recorder_escape_clears(qapp):
    """Escape LOESCHT die Bindung (vorher: Abbruch ohne Aenderung).

    Nutzererwartung im Alltag: „ich will die Taste nicht mehr" — und genau danach
    hat er gesucht und nichts gefunden. Ein Abbruch ist ohnehin trivial: dieselbe
    Taste nochmal druecken."""
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.keyPressEvent(_key_event(Qt.Key_Escape))
    assert d.result_spec is None
    assert d.cleared


def test_hotkey_recorder_delete_clears(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.keyPressEvent(_key_event(Qt.Key_Delete))
    assert d.cleared is True


def test_hotkey_recorder_pynput_fallback_captures_gkeys(qapp):
    """G-/Makrotasten (z. B. Corsair via iCUE als F13–F24) kommen NICHT als
    Qt-Key-Event an — der pynput-Fallback-Slot muss sie finalisieren und dabei
    dieselben Tokens erzeugen, die der globale HotkeyManager matcht."""
    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d._on_global_key("f13", frozenset())
    assert d.result_spec is not None
    assert d.result_spec.serialize() == "f13"

    # Mit Modifiern + exotischem VK-Token; und: nach _done keine Doppel-Finalisierung.
    d2 = HotkeyRecorderDialog()
    d2._on_global_key("vk227", frozenset({"ctrl"}))
    assert d2.result_spec.serialize() == "ctrl+vk227"
    d2._on_global_key("f10", frozenset())
    assert d2.result_spec.serialize() == "ctrl+vk227"  # _done-Guard haelt

    # Esc ueber den Fallback bricht ab statt „esc" zu binden.
    d3 = HotkeyRecorderDialog()
    d3._on_global_key("esc", frozenset())
    assert d3.result_spec is None
    assert not d3.cleared


def test_hotkey_recorder_ignores_autorepeat(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.keyPressEvent(_key_event(Qt.Key_F10, autorep=True))
    assert d.result_spec is None  # Auto-Repeat ignoriert


def _mouse_event(button, modifiers=None):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    mods = modifiers if modifiers is not None else Qt.NoModifier
    return QMouseEvent(QMouseEvent.MouseButtonPress, QPointF(10, 10), QPointF(10, 10),
                       button, button, mods)


def test_hotkey_recorder_mouse_button5(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.mousePressEvent(_mouse_event(Qt.XButton2))
    assert d.result_spec is not None
    assert d.result_spec.serialize() == "mouse5"
    assert "Maustaste 5" in d._live.text()


def test_hotkey_recorder_mouse_with_modifier(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.mousePressEvent(_mouse_event(Qt.MiddleButton, Qt.ControlModifier))
    assert d.result_spec.serialize() == "ctrl+mouse_middle"


def test_hotkey_recorder_left_and_right_click_ignored(qapp):
    from PySide6.QtCore import Qt

    from fleech.ui.hotkey_recorder import HotkeyRecorderDialog

    d = HotkeyRecorderDialog()
    d.mousePressEvent(_mouse_event(Qt.LeftButton))
    d.mousePressEvent(_mouse_event(Qt.RightButton))
    assert d.result_spec is None  # Dialog laeuft weiter, nichts gebunden


def test_collision_warning():
    from fleech.hotkey import HotkeySpec
    from fleech.ui.hotkey_recorder import collision_warning

    spec = HotkeySpec.parse("f10")
    assert collision_warning(spec, {"Mathe": HotkeySpec.parse("f10")})
    assert not collision_warning(spec, {"Mathe": HotkeySpec.parse("f9")})
    # Windows-reservierte Combo
    assert collision_warning(HotkeySpec.parse("alt+f4"), {})


def test_hotkey_field_pauses_global_hotkeys_during_capture(qapp):
    """Regression: waehrend der Hotkey-Aufnahme muss der globale pynput-Listener
    pausieren — sonst startet der Druck auf den aktuellen Hotkey beim Neubelegen
    eine Diktat-Aufnahme im Hintergrund."""
    from PySide6.QtWidgets import QDialog

    from fleech.hotkey import HotkeySpec
    from fleech.ui.hotkey_recorder import HotkeyField, HotkeyRecorderDialog

    calls = []
    field = HotkeyField(
        HotkeySpec.parse("f9"), lambda: {},
        capture_guard=(lambda: calls.append("stop"), lambda: calls.append("start")),
    )
    monkey = HotkeyRecorderDialog.exec
    HotkeyRecorderDialog.exec = lambda self: QDialog.Rejected  # Nutzer bricht ab
    try:
        field._record()
    finally:
        HotkeyRecorderDialog.exec = monkey
    # Guard MUSS auch bei Abbruch wieder freigeben (try/finally):
    assert calls == ["stop", "start"]


def test_hotkey_field_records_and_emits(qapp):
    from PySide6.QtCore import Qt

    from fleech.hotkey import HotkeySpec
    from fleech.ui.hotkey_recorder import HotkeyField, HotkeyRecorderDialog

    field = HotkeyField(HotkeySpec.parse("f9"), others_provider=lambda: {})
    assert "F9" in field._display.text()

    emitted = []
    field.changed.connect(emitted.append)
    # Recorder-Ergebnis simulieren, ohne echten Dialog zu oeffnen
    monkey = HotkeyRecorderDialog.exec
    HotkeyRecorderDialog.exec = lambda self: (
        setattr(self, "result_spec", HotkeySpec.parse("ctrl+shift+space")),
        QDialog_Accepted(),
    )[1]
    try:
        field._record()
    finally:
        HotkeyRecorderDialog.exec = monkey
    assert emitted and emitted[0].serialize() == "ctrl+shift+space"
    assert "Ctrl + Shift + Space" in field._display.text()


def QDialog_Accepted():
    from PySide6.QtWidgets import QDialog

    return QDialog.Accepted


def _make_main_window(tmp_path, monkeypatch, with_data=False):
    import time

    import fleech.usersettings as us

    monkeypatch.setattr(us, "SETTINGS_PATH", tmp_path / "settings.json")
    from fleech.history import DictationRecord, HistoryStore
    from fleech.ui.main_window import MainWindow
    from fleech.ui.settings_window import SettingsPanel

    settings = UserSettings()
    store = HistoryStore(tmp_path / "history.db")
    if with_data:
        for i, app_name in enumerate(("Code.exe", "comet.exe", "Code.exe")):
            store.add(DictationRecord(
                ts=time.time() - i * 3600, raw=f"also äh eintrag {i} halt",
                cleaned=f"Eintrag {i} ist fertig geworden.", audio_seconds=3.0,
                app=app_name,
            ))
    changed = []
    panel = SettingsPanel(settings, changed.append, lambda: ["Mikrofon A"])
    window = MainWindow(settings, store, panel, lambda: changed.append("tray"))
    return window, panel, store, settings, changed


def test_settings_panel_builds_all_pages(qapp, tmp_path, monkeypatch):
    _w, panel, _s, _st, _c = _make_main_window(tmp_path, monkeypatch)
    from fleech.ui.settings_window import SettingsPanel

    assert panel._pages.count() == len(SettingsPanel.PAGES)


def test_autostart_toggle_warns_but_keeps_wish_when_write_fails(qapp, tmp_path, monkeypatch):
    """Schlaegt das Schreiben fehl (Antivirus blockt den Run-Key), wird gewarnt —
    der WUNSCH bleibt aber gespeichert.

    Frueher sprang die Checkbox zurueck und `general.autostart` wurde False. Das
    war ein selbstverstaerkender Fehler: Beim naechsten Start sah der Abgleich
    „Wunsch = aus, Eintrag da" und loeschte den Eintrag aktiv — ein einziger
    fehlgeschlagener Schreibversuch schaltete den Autostart dauerhaft ab. Real im
    Log nachweisbar gewesen.
    """
    from fleech.ui import autostart

    monkeypatch.setattr(autostart, "set_autostart", lambda enabled: False)
    monkeypatch.setattr(autostart, "is_autostart_enabled", lambda: False)
    monkeypatch.setattr(autostart, "blocked_by_system", lambda: False)

    _w, panel, _s, settings, _c = _make_main_window(tmp_path, monkeypatch)
    panel._autostart_cb.setChecked(True)     # Nutzer aktiviert Autostart
    qapp.processEvents()
    assert settings.general.autostart is True         # Wunsch ueberlebt
    assert not panel._autostart_warn.isHidden()       # aber ehrlich gewarnt


def test_autostart_toggle_persists_when_write_succeeds(qapp, tmp_path, monkeypatch):
    from fleech.ui import autostart

    state = {"on": False}
    monkeypatch.setattr(autostart, "set_autostart",
                        lambda enabled: (state.update(on=enabled), True)[1])
    monkeypatch.setattr(autostart, "is_autostart_enabled", lambda: state["on"])

    _w, panel, _s, settings, _c = _make_main_window(tmp_path, monkeypatch)
    panel._autostart_cb.setChecked(True)
    qapp.processEvents()
    assert panel._autostart_cb.isChecked() is True
    assert settings.general.autostart is True
    assert panel._autostart_warn.isHidden()           # keine Warnung noetig


def test_settings_save_button_and_commit(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLineEdit

    _w, panel, _s, settings, _c = _make_main_window(tmp_path, monkeypatch)
    # Anzeigename-Feld finden und Text setzen OHNE editingFinished auszuloesen.
    name_field = None
    for le in panel.findChildren(QLineEdit):
        if le.placeholderText().startswith("leer = Windows"):
            name_field = le
            break
    assert name_field is not None
    name_field.setText("Alex")
    assert settings.general.display_name == ""   # noch nicht committet

    panel._save_now()                            # Speichern-Button
    assert settings.general.display_name == "Alex"   # commit() hat uebernommen
    assert "Gespeichert" in panel._save_status.text()


def test_main_window_close_saves_geometry_and_goes_to_tray(qapp, tmp_path, monkeypatch):
    window, _p, _st, settings, changed = _make_main_window(tmp_path, monkeypatch)
    window.close()  # closeEvent → Geometrie gespeichert + Tray-Callback
    qapp.processEvents()
    assert "tray" in changed
    assert settings.window.width > 0
    assert (tmp_path / "settings.json").is_file()


def test_main_window_navigation_and_refresh(qapp, tmp_path, monkeypatch):
    window, _p, _st, _s, _c = _make_main_window(tmp_path, monkeypatch, with_data=True)
    window.show_page("insights")
    assert window._stack.currentIndex() == 1
    assert window.insights._words_value.text() != "0"   # Daten kamen an
    window.show_page("home")
    assert window._stack.currentIndex() == 0
    assert "Willkommen zurück" in window.home._welcome.text()
    # Verlauf enthaelt Eintraege (mehr Widgets als nur der Stretch)
    assert window.home._timeline.count() > 2
    window.show_page("profiles")
    assert window._stack.currentIndex() == 2
    window.show_page("apps")
    assert window._stack.currentIndex() == 3
    window.show_page("settings")
    assert window._stack.currentIndex() == 4


def test_main_window_empty_store_shows_hint(qapp, tmp_path, monkeypatch):
    window, _p, _st, _s, _c = _make_main_window(tmp_path, monkeypatch, with_data=False)
    window.show_page("home")     # darf ohne Daten nicht crashen
    window.show_page("insights")
    assert window.insights._words_value.text() == "0"


def _accent_fraction(pixmap, y: int, accent_hex: str, tol: int = 30) -> float:
    """Anteil (0..1) der Bildbreite bei Zeile y, der in Akzentfarbe gemalt ist —
    fuer Pixel-genaue Fuellstands-Checks statt Vermutungen ueber Widget-Geometrie."""
    from PySide6.QtGui import QColor

    img = pixmap.toImage()
    accent = QColor(accent_hex)

    def close(c):
        return (abs(c.red() - accent.red()) < tol and abs(c.green() - accent.green()) < tol
                and abs(c.blue() - accent.blue()) < tol)

    w = img.width()
    filled = 0
    for x in range(w):
        if close(img.pixelColor(x, y)):
            filled = x + 1
        elif filled and x - filled > 3:  # Rest ist TRACK-Farbe → Fuellkante gefunden
            break
    return filled / w


def test_usage_bar_fill_proportional_to_share(qapp):
    """Regression: der fruehere QFrame+qlineargradient-Hack loeste die Stop-Position
    manchmal VOR der finalen Layout-Breite auf und fror die Fuellung auf einen
    winzigen, share-unabhaengigen Streifen ein. UsageBar malt selbst bei jedem
    paintEvent anhand der AKTUELLEN Breite — muss fuer jeden Anteil proportional
    bleiben, auch bei sehr kleinen Prozentwerten (2 %, 1 %)."""
    from fleech.ui.main_window import ACCENT_DIM, UsageBar

    bar = UsageBar()
    bar.resize(200, bar.height())  # Hoehe ist fixiert (6px, Design-System)
    for share, lo, hi in ((0.73, 0.65, 0.80), (0.13, 0.08, 0.20), (0.02, 0.02, 0.12)):
        bar.set_share(share)
        frac = _accent_fraction(bar.grab(), bar.height() // 2, ACCENT_DIM)
        assert lo <= frac <= hi, f"share={share}: gefuellt={frac:.2f}"


def test_insights_usage_bars_stay_proportional_with_tiny_shares(qapp, tmp_path, monkeypatch):
    """Wie oben, aber End-to-End durch die echte InsightsPage.refresh()-Verdrahtung
    (Store → app_usage-Shares → UsageBar.set_share). Die Balkenbreite wird explizit
    gesetzt statt vom Stretch-Layout erwartet — unter der Offscreen-Testplattform
    loest QHBoxLayout-Stretch keine realistische Breite auf (bleibt bei wenigen px,
    unabhaengig vom Fix); das ist eine Plattform-Eigenheit, keine Regression.
    WICHTIG: setFixedWidth() statt resize() — ein reines resize() auf einem Kind
    eines LIVE Stretch-Layouts kann von grab() (loest intern einen Layout-Pass aus)
    wieder ueberschrieben werden; setFixedWidth aendert die Size Policy und bleibt
    ueber grab()-Aufrufe hinweg stabil (empirisch verifiziert)."""
    import time

    from fleech.history import DictationRecord
    from fleech.ui.main_window import ACCENT_DIM, UsageBar

    window, _p, store, _s, _c = _make_main_window(tmp_path, monkeypatch)
    now = time.time()
    for i, (app_name, words) in enumerate(
        [("Code.exe", 73), ("comet.exe", 13), ("Discord.exe", 11), ("javaw.exe", 3)]
    ):
        text = " ".join(["wort"] * words)
        store.add(DictationRecord(ts=now - i, raw=text, cleaned=text,
                                  audio_seconds=words / 2.0, app=app_name))
    window.show_page("insights")

    fractions = []
    for row in window.insights._usage_rows:
        bar = row.findChild(UsageBar)
        bar.setFixedWidth(200)
        frac = _accent_fraction(bar.grab(), bar.height() // 2, ACCENT_DIM)
        fractions.append(round(frac, 2))
    # Absteigend nach Anteil (Code 73 % > comet 13 % > Discord 11 % > javaw 3 %) —
    # der urspruengliche Bug zeigte hier ueberall fast denselben (falschen) Wert.
    assert fractions[0] > fractions[1] > fractions[2] > fractions[3]
    assert fractions[0] > 0.6   # Code: deutlich mehr als die Haelfte gefuellt
    assert fractions[3] < 0.25  # javaw (3 %): klar erkennbar als kleinster Balken


def test_home_delete_single_entry(qapp, tmp_path, monkeypatch):
    window, _p, store, _s, _c = _make_main_window(tmp_path, monkeypatch, with_data=True)
    window.show_page("home")
    before = store.recent(limit=50)
    assert len(before) == 3
    victim_id = before[0]["id"]

    window.home._delete_entry(victim_id)
    after = store.recent(limit=50)
    assert len(after) == 2
    assert victim_id not in [e["id"] for e in after]
    # Insights zog automatisch mit (kein Crash, Store konsistent)
    assert window.insights._words_value.text() != ""


def test_home_entry_rows_are_clickable_and_open_full_text(qapp, tmp_path, monkeypatch):
    from fleech.history import DictationRecord
    from fleech.ui.main_window import HistoryEntryRow

    window, _p, store, _s, _c = _make_main_window(tmp_path, monkeypatch)
    long_text = "Dies ist ein sehr langer Diktattext, " + "wort " * 80 + "Schluss."
    store.add(DictationRecord(ts=1_700_000_000.0, raw="roh", cleaned=long_text,
                              audio_seconds=20.0, app="Code.exe"))
    window.show_page("home")

    rows = window.home.findChildren(HistoryEntryRow)
    assert len(rows) == 1

    opened = []
    # Nicht-modal: _open_entry ruft .show() (nicht .exec()) — Referenz landet in
    # window.home._detail_dialog.
    monkeypatch.setattr("fleech.ui.main_window.TranscriptDetailDialog.show",
                        lambda self: opened.append(self))
    rows[0].clicked.emit()
    assert len(opened) == 1
    dlg = window.home._detail_dialog
    # Der Dialog haelt den VOLLEN (nicht abgeschnittenen) Text.
    assert dlg._text == long_text
    assert "…" not in dlg._edit.toPlainText()


def test_transcript_detail_dialog_copies_to_clipboard(qapp):
    from fleech.ui.main_window import TranscriptDetailDialog

    entry = {"id": 1, "ts": 1_700_000_000.0, "cleaned": "Der Report ist fertig.",
             "app": "Code.exe", "words": 4}
    dlg = TranscriptDetailDialog(entry)
    assert "Der Report ist fertig." in dlg._edit.toPlainText()
    dlg._copy()
    assert QApplication.clipboard().text() == "Der Report ist fertig."
    assert "Kopiert" in dlg._copy_btn.text()
    dlg.close()


def test_transcript_detail_dialog_closes_on_deactivate(qapp):
    from PySide6.QtCore import QEvent

    from fleech.ui.main_window import TranscriptDetailDialog

    entry = {"id": 1, "ts": 1_700_000_000.0, "cleaned": "Text.", "app": "", "words": 1}
    dlg = TranscriptDetailDialog(entry)
    closed = []
    dlg.close = lambda: closed.append(1)  # Spy: deterministisch, unabhaengig vom Offscreen-Fokus

    # Guard: Deactivate OHNE vorherige Aktivierung wird ignoriert (kein Sofort-Schliessen).
    dlg.event(QEvent(QEvent.WindowDeactivate))
    assert closed == []
    # Nach Aktivierung schliesst ein Klick daneben (WindowDeactivate) das Fenster.
    dlg.event(QEvent(QEvent.WindowActivate))
    dlg.event(QEvent(QEvent.WindowDeactivate))
    assert closed == [1]


def test_history_delete_and_recent_has_id(tmp_path):
    import time

    from fleech.history import DictationRecord, HistoryStore

    store = HistoryStore(tmp_path / "h.db")
    for i in range(3):
        store.add(DictationRecord(ts=time.time() - i, raw="a b c",
                                  cleaned=f"Eintrag {i}.", audio_seconds=2.0))
    rows = store.recent()
    assert all("id" in r for r in rows)
    store.delete(rows[0]["id"])
    assert len(store.recent()) == 2
    store.delete(999999)  # nicht vorhanden → kein Fehler
    assert len(store.recent()) == 2


def test_word_detail_dialog_shows_words_beyond_top_five(qapp, tmp_path):
    import time

    from PySide6.QtWidgets import QLabel

    from fleech.history import DictationRecord, HistoryStore
    from fleech.ui.main_window import WordDetailDialog

    store = HistoryStore(tmp_path / "h.db")
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta"]
    for i, w in enumerate(words):
        text = " ".join([w] * (len(words) - i))  # absteigende Haeufigkeit
        store.add(DictationRecord(ts=time.time() - i, raw=text, cleaned=text,
                                  audio_seconds=2.0))

    dlg = WordDetailDialog(store)
    labels = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    # "zeta"/"eta" haetten auf den Top 5 der Karte keinen Platz mehr — im Dialog schon.
    assert "zeta" in labels
    assert "eta" in labels
    dlg.close()


def test_word_detail_dialog_empty_store_shows_hint(qapp, tmp_path):
    from PySide6.QtWidgets import QLabel

    from fleech.history import HistoryStore
    from fleech.ui.main_window import WordDetailDialog

    dlg = WordDetailDialog(HistoryStore(tmp_path / "h.db"))
    labels = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    assert "Noch keine Daten." in labels
    dlg.close()


def test_insights_word_card_open_detail_is_wired(qapp, tmp_path, monkeypatch):
    window, _p, _st, _s, _c = _make_main_window(tmp_path, monkeypatch)
    from fleech.ui import main_window as mw

    opened = []
    monkeypatch.setattr(mw.WordDetailDialog, "exec", lambda self: opened.append(True))
    window.insights._open_word_detail()
    assert opened == [True]


def test_profiles_page_assign_tags_and_default(qapp, tmp_path, monkeypatch):
    window, _p, store, settings, _c = _make_main_window(tmp_path, monkeypatch, with_data=True)
    # Fensterliste im Test deterministisch halten (kein Win32-Enum).
    monkeypatch.setattr("fleech.ui.windowsfocus.list_visible_window_processes",
                        lambda: ["Code.exe", "Discord.exe"])
    page = window.profiles
    page.refresh()

    # Standardprofil ("Alle") + Presets vorhanden; Standard steht vorn.
    items = settings.profiles.items
    assert items[0].get("default") is True
    names = [page._profiles_list.item(i).text() for i in range(page._profiles_list.count())]
    assert names[0].startswith("Standard")
    assert any(n.startswith("Coding") for n in names)

    coding_row = next(i for i, n in enumerate(names) if n.startswith("Coding"))
    coding = items[coding_row]

    # Die App-Zuweisung ist mit v4.7.0 auf die eigene Seite „Apps" gewandert:
    # Ein Profil beantwortet „was wird aus dem Diktat", nicht „wo".
    assert not hasattr(page, "_apps_list")
    assert not hasattr(page, "_assigned_list")
    assert not hasattr(page, "_title_rule")

    # Der Stil-Tag-Editor ist mit v3.7.2 aus der Oberflaeche entfallen (in 900
    # Diktaten hat ihn niemand befuellt). Das Feld selbst bleibt bestehen, damit
    # alte settings.json unveraendert laden — die Seite darf daran nicht scheitern.
    assert not hasattr(page, "_tag_input")
    coding["tags"] = ["von Hand gepflegt"]
    page._refresh_detail()                 # darf nicht werfen
    assert coding["tags"] == ["von Hand gepflegt"]   # und nichts wegwerfen

    # Standardprofil: nicht loeschbar.
    page._profiles_list.setCurrentRow(0)
    before = len(items)
    page._delete_profile()
    assert len(items) == before

    # Globaler Toggle deaktiviert den kompletten Body (ausgegraut).
    page._global_cb.setChecked(False)
    assert settings.profiles.enabled is False
    assert page._body.isEnabled() is False
    page._global_cb.setChecked(True)
    assert page._body.isEnabled() is True

    # Der Mathe-Balken ist mit v3.7.4 entfallen: Er schaltete dasselbe Feld wie die
    # Formel-Erkennung in den Einstellungen — zwei Schalter fuer einen Wert. Auf der
    # Profilseite gehoerte er ohnehin nicht hin (galt global, nicht je Profil).
    assert not hasattr(page, "_math_cb")

    # Umbenennen ueber das Detail-Titelfeld.
    page._profiles_list.setCurrentRow(coding_row)
    page._detail_title.setText("Programmieren")
    page._on_rename_profile()
    assert items[coding_row]["name"] == "Programmieren"

    # Der Modus-Slot ist mit v3.7.2 aus der Oberflaeche entfallen: Er bot „Mathe"
    # (den Modus gibt es seit v3.0.0 nicht mehr) und „KI-Prompting" (1 von 900
    # Diktaten). Ein gesetztes `mode`-Feld muss die Seite trotzdem unbeschadet
    # ueberstehen — sonst braeche eine bestehende settings.json die Profilseite.
    assert not hasattr(page, "_profile_mode_combo")
    items[coding_row]["mode"] = "prompt"
    page._refresh_detail()                        # darf nicht werfen
    assert items[coding_row]["mode"] == "prompt"  # und nichts stillschweigend loeschen


def test_apps_page_assigns_profile_per_app(qapp, tmp_path, monkeypatch):
    """Die Apps-Seite dreht die Blickrichtung um: App waehlen → Profil bestimmen.

    Gespeichert wird weiter in `profil["apps"]` — alte settings.json bleiben ohne
    Migration gueltig."""
    window, _p, _store, settings, _c = _make_main_window(tmp_path, monkeypatch,
                                                        with_data=True)
    monkeypatch.setattr("fleech.ui.windowsfocus.list_visible_window_processes",
                        lambda: ["Code.exe", "Discord.exe"])
    from PySide6.QtCore import Qt

    page = window.apps
    page.refresh()

    apps = [str(page._apps.item(i).data(Qt.UserRole))
            for i in range(page._apps.count())]
    assert "Code.exe" in apps and "Discord.exe" in apps

    items = settings.profiles.items
    coding = next(p for p in items if str(p.get("name", "")).startswith("Coding"))
    page._apps.setCurrentRow(apps.index("Code.exe"))
    page._profil_combo.setCurrentIndex(page._profil_combo.findData(coding["name"]))
    assert coding["apps"] == ["Code.exe"]
    assert (tmp_path / "settings.json").is_file()          # persistiert

    # Umhaengen auf ein anderes Profil laesst die App NICHT an zweien haengen.
    anderes = next(p for p in items
                   if not p.get("default") and p is not coding)
    page._apps.setCurrentRow(apps.index("Code.exe"))
    page._profil_combo.setCurrentIndex(page._profil_combo.findData(anderes["name"]))
    assert coding["apps"] == []
    assert anderes["apps"] == ["Code.exe"]

    # Titel-Ausnahme anlegen und wieder entfernen.
    page._regel_titel.setText("Fleech")
    page._regel_profil.setCurrentIndex(page._regel_profil.findData(coding["name"]))
    page._regel_hinzufuegen()
    assert coding["apps"] == ["Code.exe :: Fleech"]
    zeile = next(page._regeln.item(i) for i in range(page._regeln.count()))
    page._regel_entfernen(zeile)
    assert coding["apps"] == []

    # Das Standardprofil („Alle") taucht als Ziel nicht auf — es IST der Fallback.
    ziele = [page._profil_combo.itemData(i)
             for i in range(page._profil_combo.count())]
    standard = next(p for p in items if p.get("default"))
    assert standard["name"] not in ziele
    assert "" in ziele                                     # „kein Profil"

    # Zuruecknehmen auf „kein Profil".
    page._apps.setCurrentRow(apps.index("Code.exe"))
    page._profil_combo.setCurrentIndex(0)
    assert all(p.get("apps", []) == [] for p in items)


def test_app_profile_resolution_with_default_fallback(qapp):
    import types

    from fleech.ui.desktop import DesktopApp

    profiles = types.SimpleNamespace(enabled=True, items=[
        {"name": "Standard", "default": True, "intervention": "",
         "tags": ["neutraler Ton"], "apps": []},
        {"name": "Coding", "intervention": "minimal",
         "tags": ["Fachbegriffe lassen"], "apps": ["Code.exe"]},
        # Legacy-Feld "math": True → Migration auf mode="math".
        {"name": "Mathe", "intervention": "standard", "tags": [],
         "apps": ["calc.exe"], "math": True},
        {"name": "Prompting", "intervention": "standard", "tags": [],
         "apps": ["claude.exe"], "mode": "prompt"},
    ])
    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=profiles),
        _record_app="Code.exe",
    )
    from fleech.usersettings import ProfileOverrides

    # Coding hat keinen Modus-Slot und keinen eigenen Safe-Word-Schalter.
    assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(
        intervention="minimal", style_hints=["Fachbegriffe lassen"])

    # Mathe-Profil (Legacy-Bool) erzwingt den Formel-Modus fuer seine Apps.
    fake._record_app = "calc.exe"
    assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(
        intervention="standard", mode_slot="math")

    # KI-Prompting-Profil erzwingt den Prompt-Modus.
    fake._record_app = "claude.exe"
    assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(
        intervention="standard", mode_slot="prompt")

    # Nicht zugewiesene App → Standardprofil: kein Intervention-Override (""),
    # aber dessen Tags gelten, kein Modus-Slot.
    fake._record_app = "Discord.exe"
    assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(
        style_hints=["neutraler Ton"])

    profiles.enabled = False                  # globaler Schalter aus
    fake._record_app = "Code.exe"
    assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides()


def test_profile_can_disable_spoken_safeword():
    """Im Meeting/Grossraum ist ein laut gesprochenes Safe-Word unpassend — und bei
    Textilthemen faellt „Kimono" sogar zufaellig. Pro Profil abschaltbar; der
    »-Knopf bleibt immer der leise Weg."""
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import ProfileOverrides

    profiles = types.SimpleNamespace(enabled=True, items=[
        {"name": "Standard", "default": True, "intervention": "", "tags": [], "apps": []},
        {"name": "Geschäftlich", "intervention": "strong", "tags": [],
         "apps": ["OUTLOOK.EXE"], "command": "off"},
        {"name": "Laut", "intervention": "", "tags": [], "apps": ["notepad.exe"],
         "command": "on"},
    ])
    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=profiles), _record_app="OUTLOOK.EXE",
    )
    prof = DesktopApp._app_profile_overrides(fake)
    assert prof.command == "off"
    assert prof.command_allowed(global_enabled=True) is False   # Profil gewinnt

    fake._record_app = "notepad.exe"
    prof = DesktopApp._app_profile_overrides(fake)
    assert prof.command_allowed(global_enabled=False) is True   # explizit an

    fake._record_app = "sonstwas.exe"                           # Standardprofil
    prof = DesktopApp._app_profile_overrides(fake)
    assert prof.command == ""
    assert prof.command_allowed(global_enabled=True) is True    # wie Einstellungen
    assert prof.command_allowed(global_enabled=False) is False


def test_suppressed_safeword_is_treated_as_dictation():
    """Bei unterdruecktem Safe-Word ist das Wort normaler Diktattext — es darf
    weder einen Befehl ausloesen noch aus dem Text verschwinden."""
    import numpy as np

    from tests.test_pipeline import FakeLLM, make_pipeline

    raw = "Sie trug ein Kimono zur Feier und das sah sehr gut aus."
    cleaned = "Sie trug ein Kimono zur Feier, und das sah sehr gut aus."
    p, _, injector = make_pipeline(raw, llm=FakeLLM(reply=cleaned),
                                   command_llm=FakeLLM(reply="{}"))
    audio = np.zeros(16000, dtype=np.float32)
    assert p.process(audio, 16000, suppress_command=True) == "ok"
    assert injector.injected == [cleaned]
    assert p.last_mode == "cleanup"          # kein Befehls-Routing


def test_overlay_tooltip_caption_centered_below(qapp):
    from PySide6.QtWidgets import QApplication

    from fleech.ui.overlay_qt import OverlayWindow

    geom = QApplication.primaryScreen().availableGeometry()
    s = UserSettings().overlay
    s.position = "custom"
    s.x, s.y = geom.center().x() - 130, geom.center().y()  # mittig → kein Rand-Clamp
    o = OverlayWindow(s)
    o.show()
    qapp.processEvents()
    o._tip_caption.show_above(o.frameGeometry(), "Kurzer Hinweistext",
                              sticky=True, force_below=True)
    qapp.processEvents()
    pill, tip = o.frameGeometry(), o._tip_caption.frameGeometry()
    assert abs(tip.center().x() - pill.center().x()) <= 3   # horizontal zentriert
    assert tip.top() >= pill.bottom()                       # unterhalb der Pille
    assert tip.top() - pill.bottom() <= 16                  # dicht darunter (~10 px)
    o.close()


def test_list_visible_window_processes_runs():
    from fleech.ui.windowsfocus import list_visible_window_processes

    apps = list_visible_window_processes()    # Best-Effort: darf nie raisen
    assert isinstance(apps, list)


def test_interface_toggles_hide_cards(qapp, tmp_path, monkeypatch):
    window, _p, _st, settings, _c = _make_main_window(tmp_path, monkeypatch, with_data=True)
    ui = settings.interface
    # Default: alles sichtbar (nicht explizit versteckt)
    assert not window.insights._streak_frame.isHidden()
    assert not window.home._stats_frame.isHidden()

    ui.insights_show_streak = False
    ui.insights_show_app_usage = False
    ui.insights_show_top_words = False
    ui.insights_show_patterns = False
    ui.home_show_stats = False
    ui.home_show_welcome = False
    window.apply_interface()
    assert window.insights._streak_frame.isHidden()
    assert window.insights._usage_frame.isHidden()
    assert window.insights._words_freq_frame.isHidden()
    assert window.insights._pattern_frame.isHidden()
    assert window.home._stats_frame.isHidden()
    assert window.home._welcome.isHidden()
    # Metrik-Karten blieben unangetastet
    assert not window.insights._wpm_frame.isHidden()

    ui.insights_show_streak = True
    window.apply_interface()
    assert not window.insights._streak_frame.isHidden()


def test_interface_settings_roundtrip(tmp_path):
    import fleech.usersettings as us

    path = tmp_path / "settings.json"
    settings = UserSettings()
    settings.interface.insights_show_streak = False
    settings.interface.home_show_stats = False
    settings.save(path)
    loaded = us.UserSettings.load(path)
    assert loaded.interface.insights_show_streak is False
    assert loaded.interface.home_show_stats is False
    assert loaded.interface.insights_show_wpm is True  # Default unangetastet


def test_insights_advice_offers_one_click_rule(qapp, tmp_path, monkeypatch):
    """Insights waren rein deskriptiv. Aus „kimano wurde 3x zu Kimono korrigiert"
    wird jetzt per Klick eine Woerterbuch-Regel — ohne Umweg ueber die Einstellungen."""
    import time

    from PySide6.QtWidgets import QPushButton

    from fleech.history import DictationRecord

    window, panel, store, settings, _changed = _make_main_window(tmp_path, monkeypatch)
    now = time.time()
    for i in range(3):
        store.add(DictationRecord(
            ts=now - i, raw="wir nutzen kimano dafuer",
            cleaned="wir nutzen Kimono dafuer", audio_seconds=5.0, app="Test.exe",
            mode="cleanup", tier="simple", status="ok", stt_ms=200, llm_ms=900,
        ))
    window.show_page("insights")
    qapp.processEvents()
    # isHidden() statt isVisible(): ohne gezeigtes Fenster ist Letzteres immer False.
    assert not window.insights._advice_frame.isHidden()

    buttons = [b for b in window.insights._advice_frame.findChildren(QPushButton)
               if b.text().startswith("Als Regel")]
    assert buttons, "kein Ein-Klick-Vorschlag erzeugt"
    buttons[0].click()
    qapp.processEvents()
    assert "kimano => Kimono" in settings.output.dictionary
    # Der Editor in den Einstellungen zieht mit (sonst erst nach Neustart sichtbar).
    assert "kimano => Kimono" in panel._dictionary_editor.toPlainText()
    # Zweiter Klick darf keine Dublette anlegen.
    window._add_dictionary_rule("kimano", "Kimono")
    assert settings.output.dictionary.count("kimano => Kimono") == 1


def test_karten_ausblenden_und_zurueckholen(qapp, tmp_path, monkeypatch):
    """Die Seite „Oberflaeche" mit zwoelf Checkboxen ist entfallen: Ausblenden
    passiert per Rechtsklick an der Karte, Zurueckholen sammelt ein Knopf."""
    from dataclasses import fields

    from fleech.usersettings import InterfaceSettings

    from fleech.ui.settings_window import SettingsPanel

    assert "Oberfläche" not in SettingsPanel.PAGES

    _w, panel, _st, settings, changed = _make_main_window(tmp_path, monkeypatch)
    # Wie ein Rechtsklick-Ausblenden: mehrere Karten aus.
    settings.interface.insights_show_wpm = False
    settings.interface.home_show_stats = False

    panel._restore_cards()

    # Nur die Sichtbarkeits-Felder: „profiles_advanced" ist ein Bedien-Schalter,
    # keine Karte — der Knopf darf ihn nicht mit umlegen.
    assert all(getattr(settings.interface, f.name) for f in fields(InterfaceSettings)
               if "_show_" in f.name)
    assert settings.interface.profiles_advanced is False
    assert "interface" in changed
    assert "2 Karte(n)" in panel._cards_hint.text()


def test_karte_ausblenden_schreibt_die_einstellung(qapp, tmp_path, monkeypatch):
    """Das Kontextmenue setzt das Feld, versteckt die Karte und meldet es."""
    _w, panel, _st, settings, changed = _make_main_window(tmp_path, monkeypatch)
    frame = _w.insights._wpm_frame
    assert frame.property("hide_attr") == "insights_show_wpm"

    # Menue-Ausfuehrung ist nicht testbar (blockierendes exec) — die Wirkung schon.
    setattr(settings.interface, frame.property("hide_attr"), False)
    settings.save()
    frame.hide()
    panel._on_changed("interface")

    assert settings.interface.insights_show_wpm is False
    assert frame.isHidden()
    assert "interface" in changed


def test_streak_calendar_and_gauge_render(qapp, tmp_path, monkeypatch):
    import datetime as dt

    window, _p, _st, _s, _c = _make_main_window(tmp_path, monkeypatch, with_data=True)
    window.insights.refresh()
    window.insights._calendar.set_data({dt.date.today().isoformat(): 5})
    assert not window.insights._calendar.grab().isNull()
    window.insights._gauge.set_wpm(97)
    assert not window.insights._gauge.grab().isNull()


def test_sound_synthesis_all_events_and_presets():
    from fleech.ui.sounds import _build_preset

    for preset in ("soft", "click"):
        samples = _build_preset(preset)
        assert set(samples) == {"start", "stop", "commit", "error"}
        for name, arr in samples.items():
            assert 0 < arr.size < 44100  # kurz (<1 s) und nicht leer
            assert abs(float(arr.max())) <= 1.3


def test_sound_player_respects_switches(monkeypatch):
    import sounddevice

    from fleech.ui.sounds import SoundPlayer

    played = []
    monkeypatch.setattr(sounddevice, "play", lambda *a, **k: played.append(a))

    s = UserSettings().sounds
    player = SoundPlayer(s)
    player.play("start")
    assert len(played) == 1  # aktiviert → gespielt

    s.commit = False
    player.play("commit")    # einzeln deaktiviert → still
    assert len(played) == 1

    s.enabled = False
    player.play("start")     # global aus → still
    assert len(played) == 1

    s.enabled = True
    s.volume = 0.0
    player.play("stop")      # Lautstaerke 0 → still
    assert len(played) == 1


def test_woerter_karte_zeigt_einen_buchvergleich():
    """Die Zeile unter „Wörter diktiert" trug bis v3.7.3 den Lokal-Anteil. Seit es
    gar keinen Cloud-Pfad mehr gibt (v3.6.0), konnte sie nichts anderes mehr sagen
    als „100 % lokal" — tote Fläche. Jetzt steht dort ein Größenvergleich."""
    from fleech.milestones import word_milestone

    assert "Fache von" in word_milestone(74_245)
    assert word_milestone(0) == ""


def test_profil_zuordnung_beachtet_fenstertitel(qapp):
    """Derselbe Prozess, zwei Kontexte: die Titel-Regel muss gewinnen — und zwar
    unabhaengig davon, in welcher Reihenfolge die Profile stehen."""
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import ProfileOverrides

    profiles = types.SimpleNamespace(enabled=True, items=[
        {"name": "Standard", "default": True, "intervention": "", "tags": [], "apps": []},
        # Der unqualifizierte Eintrag steht ABSICHTLICH vor dem spezifischen.
        {"name": "Coding", "intervention": "minimal", "tags": [], "apps": ["Code.exe"]},
        {"name": "Notizen", "intervention": "strong", "tags": [],
         "apps": ["Code.exe :: Tagebuch"]},
    ])
    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=profiles),
        _record_app="Code.exe", _record_title="pipeline.py — Fleech",
    )
    assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(intervention="minimal")

    fake._record_title = "2026-07-22 — Tagebuch"
    assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(intervention="strong")

    # Ohne ermittelbaren Titel bleibt nur die unqualifizierte Regel.
    fake._record_title = ""
    assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(intervention="minimal")


def test_profil_zuordnung_ohne_titel_attribut_bleibt_kompatibel(qapp):
    """Aeltere Aufrufer ohne _record_title duerfen nicht brechen."""
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import ProfileOverrides

    profiles = types.SimpleNamespace(enabled=True, items=[
        {"name": "Coding", "intervention": "minimal", "tags": [], "apps": ["Code.exe"]},
    ])
    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=profiles), _record_app="Code.exe")
    assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(intervention="minimal")


def _advice_page(tmp_path, settings, pairs):
    """InsightsPage mit vorbereiteter Historie voller Korrektur-Paare."""
    import time as _t

    from fleech.history import DictationRecord, HistoryStore
    from fleech.ui.main_window import InsightsPage

    store = HistoryStore(tmp_path / "advice.db")
    now = _t.time()
    for i, (wrong, right) in enumerate(pairs):
        for n in range(3):          # min_count=2 → mindestens zweimal noetig
            store.add(DictationRecord(
                ts=now - (i * 10 + n), raw=f"wir nutzen {wrong} heute",
                cleaned=f"Wir nutzen {right} heute.", audio_seconds=5.0,
                app="Code.exe", mode="cleanup", tier="simple", status="ok",
                stt_ms=200, llm_ms=800))
    taken: list = []
    page = InsightsPage(store, on_add_rule=lambda w, r: taken.append((w, r)),
                        settings=settings)
    page.refresh()
    return page, taken


def _advice_labels(page):
    from PySide6.QtWidgets import QLabel

    out = []
    for row in page._advice_rows:
        label = row if isinstance(row, QLabel) else row.findChild(QLabel)
        if label is not None:
            out.append(label.text())
    return out


def test_uebernommene_regel_verschwindet_dauerhaft(qapp, tmp_path):
    """Der Fehler, den der Nutzer gemeldet hat: Die Korrektur-Paare bleiben in der
    Historie, also kam der Vorschlag nach dem Übernehmen zurück."""
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    page, _taken = _advice_page(tmp_path, settings, [("playside", "PySide")])
    assert any("playside" in t for t in _advice_labels(page))

    # Regel wie beim Ein-Klick-Übernehmen eintragen …
    settings.output.dictionary.append("playside => PySide")
    page.refresh()
    assert not any("playside" in t for t in _advice_labels(page))

    # … und nach dem Löschen der Regel darf der Vorschlag zu Recht wiederkommen.
    settings.output.dictionary.clear()
    page.refresh()
    assert any("playside" in t for t in _advice_labels(page))


def test_ignorieren_wirkt_ueber_die_sichtbare_liste(qapp, tmp_path, monkeypatch):
    """Ignoriert = Eintrag in dictionary_ignores (sichtbar unter Woerterbuch).
    Zeile loeschen holt den Vorschlag zurueck — genau deshalb darf es dauerhaft sein."""
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    page, _taken = _advice_page(tmp_path, settings, [("kimano", "Kimono")])
    assert any("kimano" in t for t in _advice_labels(page))

    settings.output.dictionary_ignores = ["kimano => kimono"]
    page.refresh()
    assert not any("kimano" in t for t in _advice_labels(page))

    # Zeile im Editor geloescht → Vorschlag kommt zurueck.
    settings.output.dictionary_ignores = []
    page.refresh()
    assert any("kimano" in t for t in _advice_labels(page))


def test_ignorieren_knopf_schreibt_in_die_ignorier_liste(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    notified: list = []
    page, _taken = _advice_page(tmp_path, settings, [("kimano", "Kimono")])
    page._on_ignored = lambda: notified.append(True)

    buttons = page._advice_rows[0].findChildren(QPushButton)
    ignore = [b for b in buttons if b.text() == "Ignorieren"]
    assert ignore, "Ignorieren-Knopf fehlt"
    ignore[0].click()

    assert "kimano => kimono" in settings.output.dictionary_ignores
    assert notified                       # Woerterbuch-Editor wurde benachrichtigt
    assert not any("kimano" in t for t in _advice_labels(page))
    assert settings.output.dictionary_ignores.count("kimano => kimono") == 1


def test_migration_advice_dismissed_nach_dictionary_ignores(tmp_path):
    """Kurzlebiges v1.10.1-Feld advice_dismissed wandert in die sichtbare Liste."""
    import json

    from fleech.usersettings import UserSettings

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"output": {
        "dictionary_ignores": ["alt => bestand"],
        "advice_dismissed": {"kimano => kimono": 123.0, "ALT => BESTAND": 5.0},
    }}), encoding="utf-8")
    settings = UserSettings.load(path)
    assert "kimano => kimono" in settings.output.dictionary_ignores
    # Case-insensitives Duplikat wird nicht doppelt uebernommen.
    assert len([i for i in settings.output.dictionary_ignores
                if i.lower() == "alt => bestand"]) == 1


def test_weitere_vorschlaege_ruecken_nach(qapp, tmp_path):
    """Sind die vordersten Paare erledigt, darf die Karte nicht leer bleiben."""
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    # Echte Wortpaare: top_corrections ueberspringt reine Gross-/Kleinschreibung.
    pairs = [("playside", "PySide"), ("kimano", "Kimono"), ("gitthub", "GitHub"),
             ("pyton", "Python"), ("kosinus", "Cosinus")]
    page, _taken = _advice_page(tmp_path, settings, pairs)
    assert len(_advice_labels(page)) == 3

    for wrong, right in pairs[:3]:
        settings.output.dictionary.append(f"{wrong} => {right}")
    page.refresh()
    # Die drei erledigten sind weg, dahinterliegende ruecken nach.
    labels = _advice_labels(page)
    assert labels and not any("playside" in t for t in labels)


def test_session_punkt_und_tooltip(qapp):
    """Session-Punkt: Badge + Tooltip-Zeile, sauber rueckstellbar."""
    from fleech.ui.overlay_qt import OverlayWindow
    from fleech.usersettings import OverlaySettings

    o = OverlayWindow(OverlaySettings(), on_geometry_changed=lambda: None)
    base = o._math_dot.toolTip()

    o.set_session_info((3, 5))
    assert o._math_dot._session is True
    assert "3 Diktate" in o._math_dot.toolTip()
    assert "vor 5 min" in o._math_dot.toolTip()

    o.set_session_info((1, 0))
    assert "1 Diktat in" in o._math_dot.toolTip()
    assert "gerade eben" in o._math_dot.toolTip()

    o.set_session_info(None)
    assert o._math_dot._session is False
    assert o._math_dot.toolTip() == base
    o.deleteLater()


def _onboarding(settings=None, changed=None, mics=None):
    from fleech.ui.onboarding import OnboardingDialog
    from fleech.usersettings import UserSettings

    settings = settings or UserSettings()
    return OnboardingDialog(
        settings, lambda: mics if mics is not None else ["Mikrofon (USB)"],
        on_changed=(changed.append if changed is not None else None),
        audio=False,                       # kein echter Pegel-Stream in Tests
    ), settings


def test_onboarding_navigation_und_abschluss(qapp, monkeypatch):
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    dlg, settings = _onboarding()
    assert not settings.general.onboarding_done
    assert dlg._stack.count() == 5
    assert not dlg._back_btn.isEnabled()          # Seite 1: kein Zurueck

    for _ in range(4):
        dlg._go_next()
    assert dlg._stack.currentIndex() == 4
    assert dlg._next_btn.text() == "Los geht's"
    assert dlg._skip_btn.isHidden() or not dlg._skip_btn.isVisible()

    dlg._go_next()                                # letzter Klick = Abschluss
    assert settings.general.onboarding_done is True


def test_onboarding_x_und_ueberspringen_setzen_das_flag(qapp, monkeypatch):
    """Jeder Weg hinaus setzt das Flag — der Wizard darf nie zum Wiedergaenger werden."""
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    dlg, settings = _onboarding()
    dlg.reject()                                  # Esc/X
    assert settings.general.onboarding_done is True

    dlg2, settings2 = _onboarding()
    dlg2._skip_btn.click()                        # "Ueberspringen"
    assert settings2.general.onboarding_done is True


def test_onboarding_aenderungen_greifen_sofort(qapp, monkeypatch):
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    changed: list = []
    dlg, settings = _onboarding(changed=changed, mics=["Scarlett Solo", "Webcam"])

    dlg._mic_combo.setCurrentIndex(1)             # "Scarlett Solo"
    assert settings.recording.microphone == "Scarlett Solo"
    assert "microphone" in changed

    dlg._toggle_radio.setChecked(True)
    assert settings.recording.mode == "toggle"
    assert "recording" in changed


def test_onboarding_vorbelegung_aus_settings(qapp):
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    settings.recording.mode = "toggle"
    settings.recording.microphone = "Webcam"
    settings.output.trigger_word = "Redax"
    dlg, _ = _onboarding(settings=settings, mics=["Scarlett Solo", "Webcam"])
    assert dlg._toggle_radio.isChecked()
    assert dlg._mic_combo.currentData() == "Webcam"


# -- Autostart-Wunsch bewahren (v2.1.0) --------------------------------------------

def test_fehlgeschlagenes_schreiben_loescht_den_wunsch_nicht(qapp, monkeypatch):
    """Der reale Fehler: Scheiterte das Schreiben einmal, setzte Fleech den Wunsch
    auf False — und der naechste Start LOESCHTE den Eintrag dann aktiv."""
    from fleech.ui import autostart as autostart_mod
    from fleech.ui import settings_window
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    # Schreiben schlaegt fehl: set_autostart tut nichts, Abfrage bleibt False.
    monkeypatch.setattr(settings_window.autostart, "set_autostart", lambda e: False)
    monkeypatch.setattr(settings_window.autostart, "is_autostart_enabled", lambda: False)
    monkeypatch.setattr(settings_window.autostart, "blocked_by_system", lambda: False)

    settings = UserSettings()
    panel = settings_window.SettingsPanel(
        settings, on_changed=lambda s: None, list_microphones=lambda: ["M"])
    panel._apply_autostart(True)

    assert settings.general.autostart is True      # Wunsch bleibt erhalten!
    assert not panel._autostart_warn.isHidden()    # aber ehrlich gewarnt


def test_warnung_bei_deaktivierung_im_taskmanager(qapp, monkeypatch):
    from fleech.ui import settings_window
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    monkeypatch.setattr(settings_window.autostart, "set_autostart", lambda e: True)
    monkeypatch.setattr(settings_window.autostart, "is_autostart_enabled", lambda: True)
    monkeypatch.setattr(settings_window.autostart, "blocked_by_system", lambda: True)

    settings = UserSettings()
    panel = settings_window.SettingsPanel(
        settings, on_changed=lambda s: None, list_microphones=lambda: ["M"])
    panel._apply_autostart(True)

    assert settings.general.autostart is True
    assert not panel._autostart_warn.isHidden()
    assert "Task-Manager" in panel._autostart_warn.text()


# -- Formel-Warnung ist von der Transkript-Anzeige unabhaengig (v3.0.2) -----------

def _overlay_for_formula(show_transcript: bool):
    from fleech.ui.overlay_qt import OverlayWindow
    from fleech.usersettings import OverlaySettings

    s = OverlaySettings()
    s.show_transcript = show_transcript
    return OverlayWindow(s, on_geometry_changed=lambda: None)


def test_formel_warnung_erscheint_auch_ohne_transkript_anzeige(qapp):
    """Der gemeldete Fall: Transkript-Blase ausgeschaltet → die Warnung kam gar
    nicht mehr an. Eine Bestätigung darf man abschalten, eine Warnung nicht."""
    o = _overlay_for_formula(show_transcript=False)
    o.show_formula_preview([(r"\sqrt{x} + c", True)])
    qapp.processEvents()

    assert not o._caption.isHidden()                 # eigene Blase erschien
    text = o._caption._label.text()
    assert "geraten" in text
    # LESBAR statt LaTeX: In der Pille muss man die Formel pruefen koennen.
    assert "√x + c" in text and "sqrt" not in text
    assert "\n" not in text                          # kurz: eine Zeile
    o.deleteLater()


def test_sichere_formel_meldet_sich_nicht(qapp):
    """Eindeutig übersetzte Formeln sind kein Anlass für ein Signal."""
    o = _overlay_for_formula(show_transcript=False)
    o.show_formula_preview([(r"\sqrt{(x + c)}", False)])
    qapp.processEvents()

    assert o._caption.isHidden()
    o.deleteLater()


def test_bei_aktiver_transkript_anzeige_reist_der_hinweis_mit(qapp):
    """Zwei Blasen kurz hintereinander würden sich überschreiben — deshalb hängt
    der Hinweis dort an der Transkript-Blase."""
    o = _overlay_for_formula(show_transcript=True)
    o.show_formula_preview([(r"\sqrt{x} + c", True)])
    o.show_transcript("Also die Wurzel daraus.")
    qapp.processEvents()

    text = o._caption._label.text()
    assert "Also die Wurzel daraus." in text
    assert "geraten" in text
    o.deleteLater()


def test_formel_warnung_markiert_keinen_fallback(qapp):
    """Der amber Haken bedeutet hier „schau nach", NICHT „Rohtext-Fallback" —
    sonst würde die Blase fälschlich als Fallback gerahmt."""
    o = _overlay_for_formula(show_transcript=True)
    o.show_formula_preview([(r"\sqrt{x} + c", True)])
    assert o._fallback_active is False
    o.deleteLater()


# -- D5: Rueckgaengig-Weg (letzte Ausgabe → Roh-Transkript) ------------------------

def _undo_fake(injected="Bereinigte Fassung.", raw="also die rohe fassung halt",
               alter_s=0.0, scope="dictated", busy=False):
    """Stellvertreter mit genau den Attributen, die _undo_last_output anfasst."""
    import threading
    import time as _t
    import types

    lock = threading.Lock()
    if busy:
        lock.acquire()
    aufrufe = {"replace": [], "record": [], "status": [], "sound": []}
    return types.SimpleNamespace(
        _undo_candidate=(injected, raw, _t.monotonic() - alter_s),
        _process_lock=lock,
        _UNDO_MAX_AGE_S=120,
        pipeline=types.SimpleNamespace(
            injector=types.SimpleNamespace(
                replace_tail=lambda n, t: aufrufe["replace"].append((n, t))),
            tracker=types.SimpleNamespace(
                resolve_scope=lambda s: scope,
                record_replace=lambda n, t: aufrufe["record"].append((n, t))),
        ),
        notifier=types.SimpleNamespace(sound=lambda k: aufrufe["sound"].append(k)),
        _flash_status=lambda t: aufrufe["status"].append(t),
        _aufrufe=aufrufe,
    )


def test_undo_ersetzt_die_ausgabe_durch_den_rohtext(qapp):
    from fleech.ui.desktop import DesktopApp

    fake = _undo_fake()
    DesktopApp._undo_last_output(fake)

    assert fake._aufrufe["replace"] == [(len("Bereinigte Fassung."),
                                         "also die rohe fassung halt")]
    assert fake._aufrufe["record"] == fake._aufrufe["replace"]   # Tracker mitgezogen
    assert fake._undo_candidate is None                          # nur EIN Versuch


def test_undo_loescht_nichts_wenn_der_cursor_weg_ist(qapp):
    """Kernsicherung: Nach einem Fensterwechsel ist unbekannt, wo der Cursor steht.
    Blind Backspaces zu senden hat schon einmal 2701 Zeichen vernichtet."""
    from fleech.ui.desktop import DesktopApp

    fake = _undo_fake(scope=None)
    DesktopApp._undo_last_output(fake)

    assert fake._aufrufe["replace"] == []
    assert fake._undo_candidate is None          # verfaellt, statt es spaeter zu wagen


def test_undo_verfaellt_nach_zwei_minuten(qapp):
    from fleech.ui.desktop import DesktopApp

    fake = _undo_fake(alter_s=200)
    DesktopApp._undo_last_output(fake)
    assert fake._aufrufe["replace"] == []


def test_undo_ohne_kandidat_und_bei_gleichem_text(qapp):
    """Nichts zu tun ist kein Fehler — aber es darf auch nichts passieren."""
    from fleech.ui.desktop import DesktopApp

    leer = _undo_fake()
    leer._undo_candidate = None
    DesktopApp._undo_last_output(leer)
    assert leer._aufrufe["replace"] == []

    gleich = _undo_fake(injected="Gleicher Text.", raw="Gleicher Text.")
    DesktopApp._undo_last_output(gleich)
    assert gleich._aufrufe["replace"] == []


def test_undo_wartet_wenn_gerade_verarbeitet_wird(qapp):
    """Waehrend ein Diktat eingefuegt wird, verschiebt sich die Zielstelle."""
    from fleech.ui.desktop import DesktopApp

    fake = _undo_fake(busy=True)
    DesktopApp._undo_last_output(fake)

    assert fake._aufrufe["replace"] == []
    assert fake._undo_candidate is not None       # bleibt erhalten, nur verschoben


# -- Automatisch absenden je Profil (v3.10.0) --------------------------------------

def test_autosend_nur_bei_erlaubtem_profil_und_normalem_diktat(qapp):
    """Enter nach dem Einfügen ist bequem in KI-Chats und fatal in E-Mails.
    Deshalb: nur wo das Profil es erlaubt, und nur nach einem NORMALEN Diktat —
    nach einem Befehl oder einem Rohtext-Rückfall will man erst sehen, was ankam.
    """
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import ProfileOverrides

    def lauf(auto_send, result, mode):
        gesendet = []
        fake = types.SimpleNamespace(
            pipeline=types.SimpleNamespace(
                injector=types.SimpleNamespace(
                    send_enter=lambda: gesendet.append(True)),
                last_mode=mode),
            _flash_status=lambda t: None,
        )
        prof = ProfileOverrides(auto_send=auto_send)
        # Dieselbe Bedingung wie in _process_locked.
        if prof.auto_send and result == "ok" and fake.pipeline.last_mode == "cleanup":
            DesktopApp._auto_send(fake)
        return bool(gesendet)

    assert lauf(True, "ok", "cleanup") is True          # der gewollte Fall
    assert lauf(False, "ok", "cleanup") is False        # Profil erlaubt es nicht
    assert lauf(True, "fallback", "cleanup") is False   # Rohtext-Rückfall
    assert lauf(True, "ok", "command") is False         # war ein Befehl


def test_autosend_fehler_macht_das_diktat_nicht_kaputt(qapp):
    """Der Text steht bereits im Feld — scheitert nur das Enter, ist das Diktat
    trotzdem geglückt und darf nicht als Fehler enden."""
    import types

    from fleech.ui.desktop import DesktopApp

    meldungen = []
    fake = types.SimpleNamespace(
        pipeline=types.SimpleNamespace(
            injector=types.SimpleNamespace(
                send_enter=lambda: (_ for _ in ()).throw(RuntimeError("kein Zugriff"))),
            last_mode="cleanup"),
        _flash_status=meldungen.append,
    )
    DesktopApp._auto_send(fake)                 # darf NICHT werfen
    assert meldungen and "Absenden" in meldungen[0]


def test_autosend_standardmaessig_aus():
    """Ein neues Profil sendet nie von allein — die Einstellung ist bewusst opt-in."""
    from fleech.usersettings import ProfileOverrides

    assert ProfileOverrides().auto_send is False


# -- Kaltstart-Einrichtung (Seite in der Einfuehrung) --------------------------------


class _FakeEndpoint:
    model = "gemma3:4b"
    base_url = "http://127.0.0.1:11434"


def _fake_setup_lage(monkeypatch, lage="ready", modelle=("gemma3:4b",), whisper=True,
                     winget=True):
    import fleech.llm.client as client
    from fleech import ollama_setup, provisioning

    monkeypatch.setattr(ollama_setup, "status", lambda *a, **k: lage)
    monkeypatch.setattr(ollama_setup, "install_available", lambda: winget)
    monkeypatch.setattr(provisioning, "whisper_present", lambda _m: whisper)
    monkeypatch.setattr(client, "ollama_installed_models", lambda *a, **k: set(modelle))


def _setup_page(**kw):
    from fleech.ui.setuppage import SetupPage

    return SetupPage([_FakeEndpoint()], "large-v3-turbo", autostart=False, **kw)


def test_setup_page_zeigt_drei_zeilen_und_haken(qapp, monkeypatch):
    _fake_setup_lage(monkeypatch)
    page = _setup_page()
    assert list(page._rows) == ["ollama", "llm:gemma3:4b", "stt"]
    assert page.is_ready() is True
    assert not page._btn.isEnabled()               # nichts zu tun
    assert page._btn.text() == "Alles bereit"
    page.deleteLater()


def test_setup_page_frischer_rechner_bietet_einrichtung(qapp, monkeypatch):
    _fake_setup_lage(monkeypatch, lage="missing", modelle=(), whisper=False)
    page = _setup_page()
    assert page.is_ready() is False
    assert page._btn.isEnabled()
    assert "Hintergrund" in page._status.text()
    page.deleteLater()


def test_setup_page_ohne_winget_laedt_trotzdem_das_erkennungsmodell(qapp, monkeypatch):
    """Ein manueller Schritt sperrt nur sich selbst — Whisper kommt von HuggingFace."""
    _fake_setup_lage(monkeypatch, lage="missing", modelle=(), whisper=False, winget=False)
    page = _setup_page()
    assert page._btn.isEnabled()
    assert "Erneut prüfen" in page._status.text()
    page.deleteLater()


def test_setup_page_fortschritt_landet_in_der_zeile(qapp, monkeypatch):
    _fake_setup_lage(monkeypatch, lage="missing", modelle=(), whisper=False)
    page = _setup_page()
    page._on_state("llm:gemma3:4b", "running", "wird geladen")
    page._on_progress("llm:gemma3:4b", "Lade Sprachmodell gemma3:4b … 42 %", 42)
    row = page._rows["llm:gemma3:4b"]
    assert row._bar.value() == 42
    assert row._bar.maximum() == 100
    assert "42 %" in row._note.text()

    # Unbestimmt: Qt-Bordmittel ist Range 0..0 (laufender Balken)
    page._on_progress("stt", "Lade Erkennungsmodell … 412 MB", -1)
    assert page._rows["stt"]._bar.maximum() == 0
    page.deleteLater()


def test_setup_page_kein_autostart_wenn_ollama_fehlt(qapp, monkeypatch):
    """Fremde Software installiert Fleech nie als Nebenwirkung — nur auf Klick."""
    _fake_setup_lage(monkeypatch, lage="missing", modelle=(), whisper=False)
    from fleech.ui.setuppage import SetupPage

    gestartet = []
    monkeypatch.setattr(SetupPage, "start", lambda self: gestartet.append(True))
    SetupPage([_FakeEndpoint()], "large-v3-turbo", autostart=True)
    assert gestartet == []


def test_setup_page_autostart_wenn_nur_downloads_fehlen(qapp, monkeypatch):
    _fake_setup_lage(monkeypatch, lage="ready", modelle=(), whisper=False)
    from fleech.ui.setuppage import SetupPage

    gestartet = []
    monkeypatch.setattr(SetupPage, "start", lambda self: gestartet.append(True))
    SetupPage([_FakeEndpoint()], "large-v3-turbo", autostart=True)
    assert gestartet == [True]


def test_onboarding_zeigt_einrichtung_nur_wenn_noetig(qapp, monkeypatch):
    from fleech.ui.onboarding import OnboardingDialog
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)

    def bauen():
        return OnboardingDialog(
            UserSettings(), lambda: ["Mikrofon (USB)"], audio=False,
            endpoints=[_FakeEndpoint()], stt_model="large-v3-turbo",
        )

    _fake_setup_lage(monkeypatch, lage="missing", modelle=(), whisper=False)
    dlg = bauen()
    assert dlg._stack.count() == 6
    assert dlg._pages["setup"] == 1               # direkt nach dem Willkommen
    assert dlg._pages["microphone"] == 2
    dlg.reject()

    # Fertig eingerichtet: keine Seite mit drei Haken zum Durchklicken.
    _fake_setup_lage(monkeypatch)
    dlg2 = bauen()
    assert dlg2._stack.count() == 5
    assert "setup" not in dlg2._pages
    dlg2.reject()


def test_onboarding_pegel_haengt_am_namen_nicht_am_index(qapp, monkeypatch):
    """Die eingeschobene Einrichtungs-Seite darf den Mikrofon-Pegel nicht verschieben."""
    from fleech.ui.onboarding import OnboardingDialog
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    _fake_setup_lage(monkeypatch, lage="missing", modelle=(), whisper=False)
    gestartet = []
    monkeypatch.setattr(OnboardingDialog, "_start_level_stream",
                        lambda self: gestartet.append(self._stack.currentIndex()))
    dlg = OnboardingDialog(
        UserSettings(), lambda: ["Mikrofon (USB)"], audio=False,
        endpoints=[_FakeEndpoint()], stt_model="large-v3-turbo",
    )
    dlg._go_next()                                # → Einrichtung
    assert gestartet == []
    dlg._go_next()                                # → Mikrofon
    assert gestartet == [2]
    dlg.reject()


# -- Update-Dialog und Tray-Eintrag -------------------------------------------------

_UPDATE_INFO = {
    "status": "update_available", "current": "3.13.0", "latest": "3.14.0",
    "url": "https://github.com/x/y/releases/download/v3.14.0/FleechSetup-3.14.0.exe",
    "size": 900 * 1024 * 1024, "sha256": "ab" * 32,
    "notes": "Fleech 3.14.0\n\nSHA256: " + "ab" * 32,
}


def test_update_dialog_zeigt_version_und_groesse(qapp):
    from fleech.ui.updatedialog import UpdateDialog

    dlg = UpdateDialog(_UPDATE_INFO)
    assert dlg._btn.text() == "Herunterladen"
    assert "3.14.0" in dlg.windowTitle() or "3.14.0" in dlg._info["latest"]
    dlg.reject()


def test_update_dialog_mit_fertiger_datei_installiert_direkt(qapp, tmp_path):
    """Ist die Datei schon geladen, ist der naechste Schritt die Installation —
    und die steht immer hinter einem Klick."""
    from fleech.ui.updatedialog import UpdateDialog

    datei = tmp_path / "FleechSetup-3.14.0.exe"
    datei.write_bytes(b"x")
    dlg = UpdateDialog(_UPDATE_INFO, fertige_datei=datei)
    assert dlg._btn.text() == "Installieren und neu starten"
    assert dlg._btn.isEnabled()
    dlg.reject()


def test_update_dialog_meldet_fehlgeschlagenen_download(qapp):
    from fleech.ui.updatedialog import UpdateDialog

    dlg = UpdateDialog(_UPDATE_INFO)
    dlg._on_done("")                       # Download/Pruefung fehlgeschlagen
    assert dlg._btn.text() == "Erneut versuchen"
    assert "nichts wurde installiert" in dlg._status.text()
    dlg.reject()


def test_update_dialog_ohne_startbaren_installer_nennt_den_pfad(qapp, tmp_path, monkeypatch):
    from fleech.ui import updatedialog

    datei = tmp_path / "FleechSetup-3.14.0.exe"
    datei.write_bytes(b"x")
    monkeypatch.setattr(updatedialog, "install_update", lambda p: False)
    beendet = []
    dlg = updatedialog.UpdateDialog(_UPDATE_INFO, on_quit=lambda: beendet.append(True),
                                    fertige_datei=datei)
    dlg._installieren()
    assert "von Hand" in dlg._status.text()
    assert beendet == []                   # nicht beenden, wenn nichts startete
    dlg.reject()


def test_tray_update_eintrag_ist_erst_bei_bedarf_sichtbar(qapp):
    from fleech.ui.tray import TrayController

    geklickt = []
    tray = TrayController({
        "toggle_recording": lambda: None, "toggle_overlay": lambda: None,
        "open_settings": lambda: None, "reload": lambda: None, "quit": lambda: None,
        "open_update": lambda: geklickt.append(True),
    })
    assert not tray._update_action.isVisible()
    tray.show_update("3.14.0", bereit=False)
    assert tray._update_action.text() == "Update 3.14.0 laden …"
    tray.show_update("3.14.0", bereit=True)
    assert tray._update_action.text() == "Update 3.14.0 installieren …"
    tray._update_action.trigger()
    assert geklickt == [True]
    tray.tray.hide()


def test_update_pruefung_respektiert_den_schalter(monkeypatch):
    """Aus heisst aus — auch der Start-Check darf dann nicht laufen."""
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    settings.advanced.auto_update_check = False
    gestartet = []
    monkeypatch.setattr("threading.Thread",
                        lambda *a, **k: types.SimpleNamespace(
                            start=lambda: gestartet.append(True)))
    fake = types.SimpleNamespace(settings=settings, bus=None, _pending_update=None)
    DesktopApp._check_updates_async(fake)
    assert gestartet == []

    settings.advanced.auto_update_check = True
    DesktopApp._check_updates_async(fake)
    assert gestartet == [True]


def test_update_pruefung_sucht_nicht_zweimal(monkeypatch):
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import UserSettings

    gestartet = []
    monkeypatch.setattr("threading.Thread",
                        lambda *a, **k: types.SimpleNamespace(
                            start=lambda: gestartet.append(True)))
    fake = types.SimpleNamespace(settings=UserSettings(), bus=None,
                                 _pending_update={"latest": "3.14.0"})
    DesktopApp._check_updates_async(fake)
    assert gestartet == []


# -- Lizenz: Dialog und Aufnahme-Sperre ---------------------------------------------


def _echter_schluessel(name="Max Mustermann", expires=""):
    """Signiert mit einem Wegwerf-Paar und haengt dessen oeffentlichen Teil an
    licensing.PUBLIC_KEY_HEX — sonst muesste der Test den echten privaten
    Schluessel des Herausgebers kennen (den er nicht hat und nicht haben soll)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from fleech.licensing import sign_payload

    privat = Ed25519PrivateKey.generate()
    oeffentlich = privat.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw).hex()
    return sign_payload(privat, name, expires=expires), oeffentlich


def test_license_dialog_nimmt_gueltigen_schluessel_an(qapp, monkeypatch):
    from fleech.ui.licensedialog import LicenseDialog
    from fleech.usersettings import UserSettings

    key, oeffentlich = _echter_schluessel()
    monkeypatch.setattr("fleech.licensing.PUBLIC_KEY_HEX", oeffentlich)
    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    settings = UserSettings()
    gemeldet = []
    dlg = LicenseDialog(settings, on_changed=gemeldet.append)

    assert not dlg._ok.isEnabled()                 # leer = nichts freizuschalten
    dlg._feld.setPlainText(key)
    assert dlg._ok.isEnabled()
    assert "Max Mustermann" in dlg._status.text()
    dlg._uebernehmen()
    assert settings.general.license_key == key
    assert gemeldet == ["general"]


def test_license_dialog_lehnt_gefaelschten_schluessel_ab(qapp, monkeypatch):
    """Ein Schluessel aus einem fremden Schluesselpaar darf nicht freischalten."""
    from fleech.ui.licensedialog import LicenseDialog
    from fleech.usersettings import UserSettings

    fremd, _ = _echter_schluessel("Freifahrer")
    _, echt = _echter_schluessel()
    monkeypatch.setattr("fleech.licensing.PUBLIC_KEY_HEX", echt)
    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    settings = UserSettings()
    dlg = LicenseDialog(settings)
    dlg._feld.setPlainText(fremd)
    assert not dlg._ok.isEnabled()
    assert "ungültig" in dlg._status.text()
    dlg._uebernehmen()                             # darf nichts speichern
    assert settings.general.license_key == ""
    dlg.reject()


def test_license_dialog_meldet_ablauf(qapp, monkeypatch):
    from fleech.ui.licensedialog import LicenseDialog
    from fleech.usersettings import UserSettings

    key, oeffentlich = _echter_schluessel("Alt", expires="2020-01-01")
    monkeypatch.setattr("fleech.licensing.PUBLIC_KEY_HEX", oeffentlich)
    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    dlg = LicenseDialog(UserSettings())
    dlg._feld.setPlainText(key)
    assert not dlg._ok.isEnabled()
    assert "abgelaufen" in dlg._status.text()
    dlg.reject()


def test_ohne_lizenz_wird_nicht_aufgenommen(monkeypatch):
    """Die Sperre sitzt VOR dem Mikrofon: ohne Schluessel wird gar nicht erst
    aufgenommen, und der Dialog kommt sofort statt einer Fehlermeldung danach.

    Der Dialog wird ANGEFORDERT, nicht gebaut: `_on_record_start` laeuft im
    pynput-Listener-Thread. Dort ein QDialog zu konstruieren hat Fleech in 4.7.0
    reproduzierbar eingefroren (Qt-Widgets gehoeren dem GUI-Thread). Deshalb
    prueft dieser Test auf das Signal — wer hier wieder direkt aufruft, faellt auf.
    """
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import UserSettings

    angefordert, aufnahme = [], []
    fake = types.SimpleNamespace(
        settings=UserSettings(),                   # frisch = kein Schluessel
        _license_state=None,
        controller=types.SimpleNamespace(stop_if_active=lambda: None),
        bus=types.SimpleNamespace(license_needed=types.SimpleNamespace(
            emit=lambda: angefordert.append(True))),
        focus=types.SimpleNamespace(
            may_record=lambda math_mode=False: aufnahme.append(True) or (True, "")),
    )
    fake._license_ok = lambda: DesktopApp._license_ok(fake)
    DesktopApp._on_record_start(fake, "dictate")
    assert angefordert == [True]
    assert aufnahme == []                          # Mikrofon wurde nie angefasst


def test_hotkey_pfade_fassen_keine_widgets_an():
    """Alles, was der pynput-Thread ausloest, laeuft ueber den StateBus.

    Grund ist ein echter Aufhaenger: der Lizenz-Dialog wurde direkt im
    Listener-Thread gebaut und die App stand. Derselbe Fehler steckte leiser im
    Pause-Hotkey (`overlay.set_paused` direkt). Beide Wege sind jetzt Signale —
    dieser Test haelt das fest, indem er das Overlay ganz weglaesst."""
    import types

    from fleech.ui.desktop import DesktopApp

    geschaltet, toene = [], []
    fake = types.SimpleNamespace(
        recorder=types.SimpleNamespace(
            recording=True, paused=False,
            pause=lambda: setattr(fake.recorder, "paused", True),
            resume=lambda: setattr(fake.recorder, "paused", False)),
        bus=types.SimpleNamespace(paused_changed=types.SimpleNamespace(
            emit=lambda wert: geschaltet.append(wert))),
        notifier=types.SimpleNamespace(sound=lambda n: toene.append(n)),
        # KEIN `overlay` — greift die Methode es doch an, wirft sie hier.
    )
    DesktopApp.toggle_pause(fake)
    assert geschaltet == [True] and toene == ["stop"]
    DesktopApp.toggle_pause(fake)
    assert geschaltet == [True, False] and toene == ["stop", "start"]


def test_license_state_wird_gemerkt_und_nach_eingabe_neu_bewertet(monkeypatch):
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.usersettings import UserSettings

    aufrufe = []

    def zaehl(settings):
        aufrufe.append(True)
        from fleech.licensing import LicenseState

        return LicenseState(False, reason="nein")

    monkeypatch.setattr("fleech.licensing.check", zaehl)
    fake = types.SimpleNamespace(settings=UserSettings(), _license_state=None)
    assert DesktopApp._license_ok(fake) is False
    assert DesktopApp._license_ok(fake) is False
    assert len(aufrufe) == 1                       # gemerkt, nicht bei jedem Hotkey


# -- Pause: Verdrahtung Recorder ↔ Pille ---------------------------------------------

def _pause_fake(recording=True, paused=False):
    import types

    from fleech.ui.desktop import DesktopApp

    zustand = {"paused": paused}
    protokoll = []

    class FakeRecorder:
        """`paused` muss LIVE gelesen werden — toggle_pause fragt es zweimal ab
        (vor der Entscheidung und danach fuer die Anzeige)."""

        def __init__(self):
            self.recording = recording

        @property
        def paused(self):
            return zustand["paused"]

        def pause(self):
            zustand["paused"] = True
            protokoll.append("pause")

        def resume(self):
            zustand["paused"] = False
            protokoll.append("resume")

    recorder = FakeRecorder()
    fake = types.SimpleNamespace(
        recorder=recorder,
        # Ueber den Bus, nicht direkt ans Overlay: der Pause-Hotkey feuert im
        # pynput-Thread (siehe test_hotkey_pfade_fassen_keine_widgets_an).
        bus=types.SimpleNamespace(paused_changed=types.SimpleNamespace(
            emit=lambda p: protokoll.append(f"overlay:{p}"))),
        notifier=types.SimpleNamespace(sound=lambda n: protokoll.append(f"sound:{n}")),
    )
    return DesktopApp.toggle_pause, fake, protokoll


def test_toggle_pause_haelt_an_und_setzt_fort():
    toggle, fake, protokoll = _pause_fake()
    toggle(fake)
    assert protokoll == ["pause", "overlay:True", "sound:stop"]
    protokoll.clear()
    toggle(fake)
    assert protokoll == ["resume", "overlay:False", "sound:start"]


def test_toggle_pause_ohne_aufnahme_tut_nichts():
    """Ein „Pause" im Leerlauf haette keinen Zustand zum Fortsetzen."""
    toggle, fake, protokoll = _pause_fake(recording=False)
    toggle(fake)
    assert protokoll == []


def test_pause_hotkey_nur_waehrend_der_aufnahme(monkeypatch):
    import types

    from fleech.ui.desktop import DesktopApp

    gerufen = []
    fake = types.SimpleNamespace(
        controller=types.SimpleNamespace(active=True, press=lambda n: None),
        recorder=types.SimpleNamespace(recording=True),
        toggle_pause=lambda: gerufen.append(True),
    )
    DesktopApp._on_hotkey_activate(fake, "pause")
    assert gerufen == [True]

    fake.recorder = types.SimpleNamespace(recording=False)
    DesktopApp._on_hotkey_activate(fake, "pause")
    assert gerufen == [True]                     # ausserhalb bleibt die Taste frei


def test_pause_hotkey_ist_belegt_und_konfigurierbar():
    from fleech.usersettings import RecordingSettings

    s = RecordingSettings()
    assert s.pause_hotkey == "ctrl+alt+space"
    s.pause_hotkey = ""                          # loeschbar wie die anderen
    assert s.pause_hotkey == ""


# -- Pause in der Pille -------------------------------------------------------------

def test_pause_knopf_wechselt_zustand_und_beruhigt_die_waveform(qapp):
    """Pause muss auf einen Blick erkennbar sein: andere Glyphe, ruhende Anzeige."""
    from fleech.ui.overlay_qt import OverlayWindow
    from fleech.ui.state import AppState
    from fleech.usersettings import OverlaySettings

    o = OverlayWindow(OverlaySettings())
    o.set_app_state(AppState.LISTENING)

    o.set_paused(True)
    assert o._paused is True
    # Punktreihe statt Balken — flache Balken saehen aus wie „du bist nur leise".
    assert o._wave._state is AppState.IDLE

    o.set_paused(False)
    assert o._wave._state is AppState.LISTENING
    o.deleteLater()


def test_pille_blendet_unter_sich_nur_noch_eine_sache_ein(qapp):
    """Unter der Pille ist Platz fuer GENAU eine Einblendung.

    Dort erscheinen die Profil-Kapsel und die Erklaerungen zu ✓/✕ — die lagen
    frueher uebereinander mit zwei weiteren Blasen: dem Pause-Tooltip und der
    Modus-Zeile (die am ganzen Pillen-Widget hing und deshalb ueber JEDEM Knopf
    aufging). Beide sind weg; ✓/✕ behalten ihre Erklaerung, weil dort ein
    Fehlgriff teuer ist (verwerfen statt einfuegen).
    """
    from fleech.ui.overlay_qt import OverlayWindow
    from fleech.ui.state import AppState
    from fleech.usersettings import OverlaySettings

    o = OverlayWindow(OverlaySettings())
    o.set_app_state(AppState.LISTENING)
    assert o._pause_btn.toolTip() == ""
    o.set_paused(True)
    assert o._pause_btn.toolTip() == ""
    o.set_paused(False)

    o.set_mode_line("Hold | Fokus: soft_duck | Eingriff: Standard")
    assert o.toolTip() == ""                 # nicht mehr am Widget
    assert "soft_duck" in o._mode_line       # aber weiter abfragbar
    o.set_feedback("nichts erkannt")
    assert o.toolTip() == ""
    assert "nichts erkannt" in o._mode_line

    assert o._finish_btn.toolTip() and o._cancel_btn.toolTip()
    o.deleteLater()


def test_schnellwechsel_haelt_sich_an_die_app(qapp):
    """In Claude nur die zwei Profile durchtippen, die dort Sinn ergeben.

    Vorher lief der Profil-Hotkey durch ALLE global freigegebenen Profile — bei
    sechs Profilen tippt man sich zum gewuenschten durch statt es zu waehlen.
    """
    import types

    from fleech.ui.desktop import DesktopApp

    profile = types.SimpleNamespace(
        enabled=True, active="",
        items=[{"name": "Standard", "default": True},
               {"name": "E-Mail", "mode": "email"},
               {"name": "KI-Prompt", "mode": "prompt"},
               {"name": "Stichpunkte", "mode": "summary"},
               {"name": "Formeln", "mode": "math"}],
        app_quick={"claude.exe": ["KI-Prompt", "Stichpunkte"]},
    )
    fake = types.SimpleNamespace(settings=types.SimpleNamespace(profiles=profile))

    fake.current_app = lambda: "claude.exe"
    assert DesktopApp.profile_names(fake) == ["KI-Prompt", "Stichpunkte"]

    # Gross-/Kleinschreibung des Prozessnamens darf egal sein.
    fake.current_app = lambda: "Claude.exe"
    assert DesktopApp.profile_names(fake) == ["KI-Prompt", "Stichpunkte"]

    # Nicht konfigurierte App: unveraendert alle — sonst waere jede App, die man
    # nie angefasst hat, stillschweigend auf ein Profil beschraenkt.
    fake.current_app = lambda: "Code.exe"
    assert DesktopApp.profile_names(fake) == [
        "Standard", "E-Mail", "KI-Prompt", "Stichpunkte", "Formeln"]

    # Global ausgeblendete Profile holt eine App NICHT zurueck.
    profile.items[2]["quick"] = False
    fake.current_app = lambda: "claude.exe"
    assert DesktopApp.profile_names(fake) == ["Stichpunkte"]


def test_schnellwechsel_faellt_zurueck_statt_leer_zu_sein(qapp):
    """Ein Eintrag, der auf geloeschte/umbenannte Profile zeigt, darf den
    Schnellwechsel nicht totlegen — sonst tut der Hotkey scheinbar nichts und
    man kaeme nur noch ueber das Hauptfenster wieder heraus."""
    import types

    from fleech.ui.desktop import DesktopApp

    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=types.SimpleNamespace(
            enabled=True, active="",
            items=[{"name": "Standard", "default": True}, {"name": "E-Mail"}],
            app_quick={"claude.exe": ["Heisst laengst anders"]})),
        current_app=lambda: "claude.exe",
    )
    assert DesktopApp.profile_names(fake) == ["Standard", "E-Mail"]


def test_current_app_haelt_die_app_der_laufenden_aufnahme_fest(qapp):
    """Waehrend der Aufnahme zaehlt die App, in die eingefuegt wird — nicht die,
    auf der die Maus zufaellig gerade steht. Sonst stuende in der Auswahlliste
    etwas anderes als das, wofuer das Diktat gilt."""
    import types

    from fleech.ui.desktop import DesktopApp

    fake = types.SimpleNamespace(
        recorder=types.SimpleNamespace(recording=True),
        _record_app="claude.exe",
        notifier=types.SimpleNamespace(
            context=types.SimpleNamespace(foreground_process="explorer.exe")),
    )
    assert DesktopApp.current_app(fake) == "claude.exe"

    fake.recorder.recording = False
    assert DesktopApp.current_app(fake) == "explorer.exe"

    # Kein Fokus-Kontext (Linux/fruehe Startphase) → leer, nie ein Absturz.
    fake.notifier = types.SimpleNamespace()
    assert DesktopApp.current_app(fake) == ""


def test_apps_seite_pflegt_den_schnellwechsel(qapp, tmp_path, monkeypatch):
    """Haken setzen/entfernen auf der Apps-Seite landet in den Einstellungen."""
    from PySide6.QtCore import Qt

    window, _p, _store, settings, _c = _make_main_window(tmp_path, monkeypatch,
                                                         with_data=True)
    monkeypatch.setattr("fleech.ui.windowsfocus.list_visible_window_processes",
                        lambda: ["Code.exe"])
    page = window.apps
    page.refresh()
    page._apps.setCurrentRow(0)

    # Unkonfiguriert: alles angehakt (nicht leer — sonst saehe es aus, als sei
    # der Schnellwechsel hier abgeschaltet).
    zahl = page._schnell.count()
    assert zahl >= 2
    assert all(page._schnell.item(i).checkState() == Qt.Checked for i in range(zahl))
    assert settings.profiles.app_quick == {}

    erstes = page._schnell.item(0).text()
    page._schnell.item(1).setCheckState(Qt.Unchecked)
    gespeichert = settings.profiles.app_quick["code.exe"]
    assert page._schnell.item(1).text() not in gespeichert
    assert erstes in gespeichert

    # Wieder alle anhaken = kein Sonderfall mehr → Eintrag verschwindet, damit
    # spaeter angelegte Profile hier nicht stillschweigend fehlen.
    page._schnell.item(1).setCheckState(Qt.Checked)
    assert "code.exe" not in settings.profiles.app_quick

    # Alle Haken weg wuerde „gar kein Profil" bedeuten — wird nicht gespeichert.
    for i in range(zahl):
        page._schnell.item(i).setCheckState(Qt.Unchecked)
    assert "code.exe" not in settings.profiles.app_quick


# -- Suche + Diktierzeit (v4.9.2) ------------------------------------------------------


def test_dauer_waehlt_die_passende_einheit():
    """„0,05 h" sagt niemandem etwas, „906 min" auch nicht mehr."""
    from fleech.ui.main_window import _dauer

    assert _dauer(0) == "0 s"
    assert _dauer(46) == "46 s"          # Ø je Diktat — nicht auf „1 min" runden
    assert _dauer(59) == "59 s"
    assert _dauer(60) == "1 min"
    assert _dauer(3600) == "1 h"         # nicht „1 h 0 min"
    assert _dauer(3900) == "1 h 5 min"
    assert _dauer(54360) == "15,1 Stunden"
    assert _dauer(None) == "0 s" and _dauer(-5) == "0 s"


def test_diktierzeit_kommt_aus_der_echten_sprechzeit():
    """Nicht aus Woertern/WPM gerechnet — das waere ein Zirkelschluss (WPM stammt
    aus denselben zwei Zahlen) und wuerde Pausen und Verworfenes unterschlagen."""
    import types

    from fleech.ui.main_window import _diktierzeit_text

    text = _diktierzeit_text(types.SimpleNamespace(
        total_audio_seconds=54360, total_dictations=1174))
    assert "15,1 Stunden gesprochen" in text
    assert "Ø 46 s je Diktat" in text

    leer = _diktierzeit_text(types.SimpleNamespace(
        total_audio_seconds=0, total_dictations=0))
    assert "Noch keine" in leer


def test_passt_findet_ueber_wortteile():
    from fleech.ui.main_window import _passt

    assert _passt("Code.exe · läuft → Stichpunkte", "code")
    assert _passt("Code.exe · läuft → Stichpunkte", "CODE")       # Gross egal
    assert _passt("Code.exe · läuft → Stichpunkte", "stichpunkte")  # auch das Profil
    assert _passt("Code.exe · läuft → Stichpunkte", "code stich")   # beide Teile
    assert not _passt("Code.exe · läuft", "word")
    assert _passt("irgendwas", "") and _passt("irgendwas", "   ")   # leer = alles


def test_app_suche_filtert_die_liste(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt

    window, _p, _store, _settings, _c = _make_main_window(tmp_path, monkeypatch,
                                                          with_data=True)
    monkeypatch.setattr("fleech.ui.windowsfocus.list_visible_window_processes",
                        lambda: ["Code.exe", "Discord.exe", "chrome.exe"])
    page = window.apps
    page.refresh()
    assert page._apps.count() >= 3

    page._app_suche.setText("disc")
    sichtbar = [str(page._apps.item(i).data(Qt.UserRole))
                for i in range(page._apps.count())]
    assert sichtbar == ["Discord.exe"]

    page._app_suche.setText("gibtsnicht")
    assert page._apps.count() == 0
    assert page._aktuelle_app() == ""          # kein Zugriff ins Leere

    page._app_suche.clear()
    assert page._apps.count() >= 3


def test_profil_suche_bearbeitet_das_richtige_profil(qapp, tmp_path, monkeypatch):
    """Der Fallstrick der Filterung: Zeile 0 einer gefilterten Liste ist NICHT
    Profil 0. Wer die Zeilennummer als Index nimmt, benennt stillschweigend das
    falsche Profil um oder loescht es."""
    window, _p, _store, settings, _c = _make_main_window(tmp_path, monkeypatch,
                                                         with_data=True)
    page = window.profiles
    page.refresh()
    items = settings.profiles.items
    assert len(items) > 3
    ziel = items[3]["name"]

    page._profil_suche.setText(ziel.lower()[:4])
    assert page._profiles_list.count() >= 1
    page._profiles_list.setCurrentRow(0)
    assert page._current_profile() is items[3]      # nicht items[0]!

    page._detail_title.setText("Umbenannt")
    page._on_rename_profile()
    assert items[3]["name"] == "Umbenannt"
    assert items[0]["name"] != "Umbenannt"          # Standard blieb unangetastet


def test_neues_profil_bleibt_trotz_aktiver_suche_sichtbar(qapp, tmp_path, monkeypatch):
    """Sonst legt man bei aktivem Filter ein Profil an, das die Suche nicht trifft
    — es waere sofort unsichtbar und der Klick saehe fehlgeschlagen aus."""
    window, _p, _store, settings, _c = _make_main_window(tmp_path, monkeypatch,
                                                         with_data=True)
    page = window.profiles
    page.refresh()
    page._profil_suche.setText("zzz-trifft-nichts")
    assert page._profiles_list.count() == 0

    vorher = len(settings.profiles.items)
    page._add_profile()
    assert len(settings.profiles.items) == vorher + 1
    assert page._profil_suche.text() == ""
    assert page._profiles_list.count() == vorher + 1
    assert page._current_profile() is settings.profiles.items[-1]


# -- Profil-Liste: Klick daneben schliesst (v4.11.0) -----------------------------------


def _picker(qapp, monkeypatch, cursor=(400, 300)):
    from PySide6.QtCore import QPoint

    from fleech.ui.profilepicker import ProfilePicker

    monkeypatch.setattr("PySide6.QtGui.QCursor.pos",
                        staticmethod(lambda: QPoint(*cursor)))
    p = ProfilePicker()
    p.show_at_cursor(["Standard", "E-Mail"], aktiv="")
    return p


def test_liste_schliesst_bei_klick_in_eine_fremde_anwendung(qapp, monkeypatch):
    """Der gemeldete Fall: Die Liste nimmt nie den Fokus, ein Klick daneben geht
    also direkt an die andere Anwendung — Qt sieht davon nichts. Ohne eigene
    Wache blieb sie stehen, „bis was gedrueckt wird"."""
    from PySide6.QtCore import QPoint

    p = _picker(qapp, monkeypatch)
    assert not p.isHidden()

    # Maustaste gedrueckt, Zeiger WEIT weg von der Liste.
    monkeypatch.setattr(type(p), "_gedrueckt", staticmethod(lambda: True))
    weit = p.geometry().bottomRight() + QPoint(400, 400)
    monkeypatch.setattr("PySide6.QtGui.QCursor.pos", staticmethod(lambda: weit))
    p._pruefe_fremdklick()
    assert p.isHidden()


def test_klick_auf_die_liste_selbst_schliesst_nicht_vorschnell(qapp, monkeypatch):
    """Sonst waere die Liste weg, bevor der Knopf sein clicked() ausloest — man
    koennte kein Profil mehr auswaehlen."""
    p = _picker(qapp, monkeypatch)
    monkeypatch.setattr(type(p), "_gedrueckt", staticmethod(lambda: True))
    monkeypatch.setattr("PySide6.QtGui.QCursor.pos",
                        staticmethod(lambda: p.geometry().center()))
    p._pruefe_fremdklick()
    assert not p.isHidden()
    p.hide()


def test_ohne_klick_bleibt_die_liste_stehen(qapp, monkeypatch):
    from PySide6.QtCore import QPoint

    p = _picker(qapp, monkeypatch)
    monkeypatch.setattr(type(p), "_gedrueckt", staticmethod(lambda: False))
    monkeypatch.setattr("PySide6.QtGui.QCursor.pos",
                        staticmethod(lambda: QPoint(1500, 900)))
    for _ in range(5):
        p._pruefe_fremdklick()
    assert not p.isHidden()
    p.hide()


def test_wache_laeuft_nur_solange_die_liste_offen_ist(qapp, monkeypatch):
    """Ein Timer, der nach dem Schliessen weiterpollt, ist stille Dauerlast."""
    import sys

    p = _picker(qapp, monkeypatch)
    if sys.platform == "win32":
        assert p._wache is not None and p._wache.isActive()
    p.hide()
    assert p._wache is None or not p._wache.isActive()


def test_wache_ueberlebt_eine_kaputte_maus_abfrage(qapp, monkeypatch):
    """Faellt die Systemabfrage aus, darf die Liste nicht mitreissen — sie ist
    ueber Escape und Auswahl weiterhin bedienbar."""
    def kaputt():
        raise OSError("kein user32")

    p = _picker(qapp, monkeypatch)
    monkeypatch.setattr(type(p), "_gedrueckt", staticmethod(kaputt))
    p._pruefe_fremdklick()                 # darf nicht werfen
    assert not p.isHidden()
    p.hide()
