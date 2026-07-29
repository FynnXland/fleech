"""Tests fuer Fokus-Modi, Fade-Verhalten, Device-Guard und Loopback-Blockade."""

import pytest

from fleech.audiofocus import (
    AudioFocusController, DeviceCheck, DeviceGuard, FocusMode, PlaybackDucker,
)


# -- Device-Guard -----------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "Stereo Mix (Realtek(R) Audio)",
    "Stereomix (Realtek High Definition Audio)",
    "Loopback (Steam Streaming Speakers)",
    "What U Hear (Sound Blaster)",
    "CABLE Output (VB-Audio Virtual Cable)",
    "Voicemeeter Out B1",
])
def test_guard_blocks_loopback_names(monkeypatch, name):
    monkeypatch.setattr(DeviceGuard, "resolve_input_name", staticmethod(lambda d: name))
    check = DeviceGuard.check(None)
    assert not check.ok
    assert "Loopback" in check.reason or "Mix" in check.reason


@pytest.mark.parametrize("name", [
    "Mikrofon (USB Audio Device)",
    "Mikrofonarray (Intel® Smart Sound)",
    "Headset Microphone (Jabra)",
])
def test_guard_allows_real_microphones(monkeypatch, name):
    monkeypatch.setattr(DeviceGuard, "resolve_input_name", staticmethod(lambda d: name))
    assert DeviceGuard.check(None).ok


def test_guard_handles_unqueryable_device(monkeypatch):
    def boom(d):
        raise RuntimeError("kein Geraet")

    monkeypatch.setattr(DeviceGuard, "resolve_input_name", staticmethod(boom))
    check = DeviceGuard.check(99)
    assert not check.ok
    assert "nicht abfragbar" in check.reason


# -- Ducker ------------------------------------------------------------------------------


class FakeVolume:
    def __init__(self, level):
        self.level = level
        self.history = []
        self.fail_after = None

    def GetMasterVolume(self):
        return self.level

    def SetMasterVolume(self, value, _ctx):
        if self.fail_after is not None and len(self.history) >= self.fail_after:
            raise OSError("Session weg")
        self.level = value
        self.history.append(value)


class FakeSessions:
    def __init__(self, volumes):
        self.volumes = volumes

    def iter_foreign_sessions(self):
        yield from self.volumes.items()


def make_ducker(volumes, **kwargs):
    kwargs.setdefault("fade_ms", 0)  # Tests brauchen keine Echtzeit-Rampen
    return PlaybackDucker(sessions=FakeSessions(volumes), **kwargs)


def test_duck_lowers_relative_and_restore_returns_exact():
    chrome, spotify = FakeVolume(0.8), FakeVolume(0.3)
    d = make_ducker({"chrome.exe": chrome, "spotify.exe": spotify}, duck_level=0.25)
    d.duck()
    assert chrome.level == pytest.approx(0.8 * 0.25)
    assert spotify.level == pytest.approx(0.3 * 0.25)  # leise Apps bleiben relativ leise
    assert d.ducked
    d.restore()
    assert chrome.level == pytest.approx(0.8)
    assert spotify.level == pytest.approx(0.3)
    assert not d.ducked


def test_fade_is_gradual_and_monotonic():
    vol = FakeVolume(1.0)
    d = make_ducker({"app.exe": vol}, duck_level=0.2)
    d.duck()
    assert len(vol.history) == PlaybackDucker.FADE_STEPS
    assert vol.history == sorted(vol.history, reverse=True)  # weich runter, kein Sprung
    assert vol.history[-1] == pytest.approx(0.2)


def test_hard_mute_only_when_configured():
    vol = FakeVolume(0.9)
    d = make_ducker({"app.exe": vol}, duck_level=0.25, hard_mute=True)
    d.duck()
    assert vol.level == 0.0
    d.restore()
    assert vol.level == pytest.approx(0.9)


def test_duck_is_idempotent_and_restore_without_duck_is_noop():
    vol = FakeVolume(0.5)
    d = make_ducker({"app.exe": vol}, duck_level=0.5)
    d.restore()  # kein Duck davor → no-op
    assert vol.history == []
    d.duck()
    first = list(vol.history)
    d.duck()  # zweites Duck aendert nichts (kein Doppel-Absenken)
    assert vol.history == first


def test_vanishing_session_does_not_break_fade():
    stable, dying = FakeVolume(1.0), FakeVolume(1.0)
    dying.fail_after = 2
    d = make_ducker({"ok.exe": stable, "weg.exe": dying}, duck_level=0.1)
    d.duck()  # darf nicht raisen
    assert stable.level == pytest.approx(0.1)


def test_ducker_errors_never_propagate():
    class BrokenSessions:
        def iter_foreign_sessions(self):
            raise RuntimeError("COM kaputt")

    d = PlaybackDucker(sessions=BrokenSessions(), fade_ms=0)
    d.duck()  # loggt, raist nicht
    d.restore()


# -- Controller / Moduswechsel -------------------------------------------------------------


def make_controller(mode, ok=True, ducker=None, mic=None):
    check = DeviceCheck(ok=ok, name="Testgeraet", reason="" if ok else "Loopback erkannt")
    return AudioFocusController(mode, ducker, check, mic)


def test_pure_mic_never_ducks():
    vol = FakeVolume(1.0)
    ducker = make_ducker({"app.exe": vol})
    c = make_controller(FocusMode.PURE_MIC, ducker=ducker)
    c.on_recording_start()
    assert vol.history == []


def test_soft_duck_and_hard_focus_duck():
    for mode in (FocusMode.SOFT_DUCK, FocusMode.HARD_FOCUS):
        vol = FakeVolume(1.0)
        c = make_controller(mode, ducker=make_ducker({"app.exe": vol}, duck_level=0.3))
        c.on_recording_start()
        assert vol.level == pytest.approx(0.3)
        c.on_recording_stop()
        assert vol.level == pytest.approx(1.0)


def test_clean_device_records_silently():
    c = make_controller(FocusMode.SOFT_DUCK)
    assert c.may_record(math_mode=True) == (True, "")


def test_status_line_reports_mode_and_mic():
    c = make_controller(FocusMode.HARD_FOCUS)
    line = c.status_line()
    assert "Testgeraet" in line
    assert "hard_focus" in line
    assert "nur Mikrofon" in line


# -- Sperrliste + strukturelle Monitor-Erkennung (W3-18) --------------------------

def test_blocklist_schlaegt_zu(monkeypatch):
    monkeypatch.setattr(DeviceGuard, "resolve_input_name",
                        staticmethod(lambda d: "Mikrofon (Scarlett Solo USB)"))
    check = DeviceGuard.check(None, ["Scarlett"])
    assert not check.ok
    assert check.source == "blocklist"
    assert "Scarlett" in check.reason


def test_blocklist_ignoriert_leeres_und_kommentare(monkeypatch):
    monkeypatch.setattr(DeviceGuard, "resolve_input_name",
                        staticmethod(lambda d: "Mikrofon (Scarlett Solo USB)"))
    assert DeviceGuard.check(None, ["", "   ", "# Scarlett"]).ok


def test_blocklist_hat_vorrang_vor_allem(monkeypatch):
    """Nutzerwille zuerst: der Eintrag muss auch dann als Grund erscheinen, wenn
    die Wortliste ohnehin angeschlagen haette."""
    monkeypatch.setattr(DeviceGuard, "resolve_input_name",
                        staticmethod(lambda d: "Stereo Mix (Realtek)"))
    check = DeviceGuard.check(None, ["Realtek"])
    assert not check.ok and check.source == "blocklist"


def test_monitor_quelle_wird_strukturell_erkannt(monkeypatch):
    """Eine Monitor-Source, die NICHT nach Loopback klingt — nur der strukturelle
    Check kann die fangen."""
    import fleech.audiofocus as af

    monkeypatch.setattr(DeviceGuard, "resolve_input_name",
                        staticmethod(lambda d: "Interner Ton"))
    monkeypatch.setattr(af, "is_monitor_source", lambda name: True)
    check = DeviceGuard.check(None)
    assert not check.ok
    assert check.source == "monitor"


def test_unbekannter_monitor_status_blockiert_nicht(monkeypatch):
    """None = nicht entscheidbar (Windows). Darf kein Mikrofon aussperren."""
    import fleech.audiofocus as af

    monkeypatch.setattr(DeviceGuard, "resolve_input_name",
                        staticmethod(lambda d: "Mikrofon (USB)"))
    monkeypatch.setattr(af, "is_monitor_source", lambda name: None)
    assert DeviceGuard.check(None).ok


def test_is_monitor_source_auf_windows_ist_ehrlich_unbekannt(monkeypatch):
    """Windows kann Stereomix nicht strukturell von einem Mikrofon unterscheiden —
    das muss None liefern statt eine Sicherheit vorzutaeuschen."""
    import fleech.audiofocus as af

    monkeypatch.setattr(af.sys, "platform", "win32")
    assert af.is_monitor_source("Stereo Mix") is None


def test_nicht_abfragbares_geraet_markiert_error(monkeypatch):
    def boom(d):
        raise RuntimeError("weg")

    monkeypatch.setattr(DeviceGuard, "resolve_input_name", staticmethod(boom))
    check = DeviceGuard.check(None)
    assert not check.ok and check.source == "error"


def test_geraetename_ueberlebt_eine_fehlgeschlagene_abfrage(monkeypatch):
    """Real im Log: Beim App-Start ist das Audio-Subsystem manchmal noch nicht
    bereit, `query_devices` wirft — und Fleech meldete faelschlich „Geraet nicht
    abfragbar" fuer ein voellig normales Mikrofon (das Scarlett existiert unter
    vier Host-APIs). Fuer die Loopback-Pruefung genuegt der NAME."""
    import fleech.audiofocus as a

    def boom(**kwargs):
        raise ValueError("Multiple input devices found for 'Mikrofon (Scarlett)'")

    monkeypatch.setattr("sounddevice.query_devices", boom, raising=False)
    assert DeviceGuard.resolve_input_name("Mikrofon (Scarlett Solo USB)") == \
        "Mikrofon (Scarlett Solo USB)"
    # … und der Check stuft es dann als normales Mikrofon ein, nicht als Fehler.
    monkeypatch.setattr(a, "is_monitor_source", lambda name: None)
    check = DeviceGuard.check("Mikrofon (Scarlett Solo USB)")
    assert check.ok and check.source == ""


def test_ohne_geraetenamen_bleibt_der_fehler_sichtbar(monkeypatch):
    """Ist gar kein Name bekannt (Systemstandard, Index), darf der Fehler NICHT
    verschluckt werden — sonst prueften wir stillschweigend nichts."""
    def boom(**kwargs):
        raise ValueError("kaputt")

    monkeypatch.setattr("sounddevice.query_devices", boom, raising=False)
    check = DeviceGuard.check(None)
    assert not check.ok and check.source == "error"
