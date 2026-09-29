"""Overlay-Pille: Sichtbarkeit, Groesse, Waveform, Transkript, Live-Vorschau.

Teil der Qt-Smoke-Tests (offscreen, siehe conftest.py): Widgets bauen, Zustaende
schalten, Persistenz-Callbacks pruefen. Keine Optik-Pruefung.
"""

import pytest

pytest.importorskip("PySide6")

from fleech.ui.state import AppState, StateBus
from fleech.usersettings import UserSettings


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
        config=types.SimpleNamespace(audio=types.SimpleNamespace(samplerate=16000),
                                     overlay=types.SimpleNamespace(
                                         interval_ms=1000, window_seconds=12.0)),
        _preview=None, _preview_gen=0,
        _ensure_preview_model=lambda: types.SimpleNamespace(transcribe_segments=lambda a: []),
        # Seit 5.5.0 zieht die Vorschau ihr Audio ueber `_laufendes_audio` —
        # damit sie auch beim Freihand-Diktat etwas sieht, wo der Recorder
        # gar nicht laeuft.
        _laufendes_audio=lambda: None,
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


def test_profil_punkt_wechselt_nur_waehrend_der_aufnahme(qapp):
    """Klick auf den Profil-Punkt wirkt nur bei laufender Aufnahme.

    Grund: Die Pille liegt am Bildschirmrand und wird beilaeufig getroffen.
    Ausserhalb der Aufnahme haette ein Klick keine sichtbare Folge ausser der
    kurzen Namens-Kapsel — man wuerde erst beim naechsten Diktat merken, dass
    ein anderes Profil gilt.
    """
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from fleech.ui.overlay_qt import OverlayWindow

    s = UserSettings().overlay
    s.visibility = "always"
    o = OverlayWindow(s)
    gerufen = []
    o.profile_cycle_requested.connect(lambda: gerufen.append(True))

    def klick():
        punkt = QPointF(o._math_dot.rect().center())
        ereignis = QMouseEvent(QEvent.MouseButtonPress, punkt, punkt,
                               Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        o._math_dot.mousePressEvent(ereignis)
        qapp.processEvents()

    # Frisch gebaut: noch keine Aufnahme → Klick laeuft ins Leere.
    klick()
    assert gerufen == []

    o.set_app_state(AppState.LISTENING)
    klick()
    assert gerufen == [True]

    # Verarbeitung ist keine Aufnahme mehr — das Profil steht bereits fest.
    o.set_app_state(AppState.PROCESSING)
    klick()
    o.set_app_state(AppState.IDLE)
    klick()
    assert gerufen == [True]
    o.close()


def test_profil_punkt_bleibt_ausserhalb_der_aufnahme_sichtbar(qapp):
    """Nicht klickbar heisst nicht ausgegraut: der Ring zeigt weiter das Profil."""
    from fleech.ui.overlay_qt import OverlayWindow

    s = UserSettings().overlay
    s.visibility = "always"
    o = OverlayWindow(s)
    o.set_profile_color("#7FD1A6")
    o.set_app_state(AppState.IDLE)
    assert o._math_dot.isEnabled()          # kein setEnabled(False)
    assert o._math_dot._profil_farbe == "#7FD1A6"
    assert not o._math_dot._klickbar
    o.close()
