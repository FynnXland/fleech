"""Linux-Portierung: Pfade, Autostart (XDG), SingleInstance (flock), Clipboard,
Pulse-Ducking, Maus-Hotkeys (on_click) und Fokus-Restore-Dispatch.

Alle Tests laufen ohne echte X11-/Pulse-Verbindung (Fakes via sys.modules bzw.
monkeypatch) und sind unter Windows uebersprungen, wo sie Linux-Systempfade
(fcntl, XDG) brauchen.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux-spezifischer Pfad"
)


# -- Pfade -------------------------------------------------------------------------------


@linux_only
def test_user_data_dir_nutzt_xdg_config_home(monkeypatch, tmp_path):
    from fleech.platformpaths import user_data_dir

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert user_data_dir() == tmp_path / "cfg" / "Fleech"


@linux_only
def test_user_data_dir_default_ist_dot_config(monkeypatch):
    from fleech.platformpaths import user_data_dir

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert user_data_dir() == Path.home() / ".config" / "Fleech"


# -- Autostart (XDG-Desktop-Datei) --------------------------------------------------------


@linux_only
def test_autostart_roundtrip_xdg(monkeypatch, tmp_path):
    from fleech.ui import autostart

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert not autostart.is_autostart_enabled()

    assert autostart.set_autostart(True)
    desktop = tmp_path / "autostart" / "fleech.desktop"
    assert desktop.is_file()
    content = desktop.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "--gui" in content
    assert autostart.current_autostart_command() == autostart._command()
    assert autostart.is_autostart_enabled()

    assert autostart.set_autostart(False)
    assert not desktop.exists()
    assert not autostart.is_autostart_enabled()


@linux_only
def test_autostart_reconcile_stellt_eintrag_her_und_entfernt(monkeypatch, tmp_path):
    from fleech.ui import autostart

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    autostart.reconcile_autostart(True)
    assert autostart.is_autostart_enabled()

    # Veralteter Pfad wird beim Reconcile korrigiert.
    desktop = tmp_path / "autostart" / "fleech.desktop"
    desktop.write_text("[Desktop Entry]\nExec=/alter/pfad --gui\n", encoding="utf-8")
    autostart.reconcile_autostart(True)
    assert autostart.current_autostart_command() == autostart._command()

    autostart.reconcile_autostart(False)
    assert not autostart.is_autostart_enabled()


# -- SingleInstance (flock) ---------------------------------------------------------------


@linux_only
def test_singleinstance_flock_blockiert_zweite_instanz(monkeypatch, tmp_path):
    from fleech.singleinstance import SingleInstanceLock

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    first = SingleInstanceLock("Fleech.Test")
    second = SingleInstanceLock("Fleech.Test")
    try:
        assert first.acquire(retries=0)
        assert first._handle is not None
        assert not second.acquire(retries=0)
        first.release()
        assert first._handle is None
        assert second.acquire(retries=0)
    finally:
        first.release()
        second.release()


# -- Clipboard ---------------------------------------------------------------------------


@linux_only
def test_clipboard_nutzt_copykitten(monkeypatch):
    from fleech import clipboard

    calls = {}
    fake = types.SimpleNamespace(
        copy=lambda text: calls.setdefault("copied", text),
        paste=lambda: "aus-copykitten",
    )
    monkeypatch.setitem(sys.modules, "copykitten", fake)
    clipboard.copy_text("hallo")
    assert calls["copied"] == "hallo"
    assert clipboard.paste_text() == "aus-copykitten"


@linux_only
def test_clipboard_faellt_auf_pyperclip_zurueck(monkeypatch):
    from fleech import clipboard

    def boom(*_a):
        raise RuntimeError("kein Backend")

    fake_ck = types.SimpleNamespace(copy=boom, paste=boom)
    store = {}
    fake_pc = types.SimpleNamespace(
        copy=lambda text: store.setdefault("v", text),
        paste=lambda: store.get("v"),
    )
    monkeypatch.setitem(sys.modules, "copykitten", fake_ck)
    monkeypatch.setitem(sys.modules, "pyperclip", fake_pc)
    clipboard.copy_text("fallback")
    assert clipboard.paste_text() == "fallback"


# -- Pulse-Ducking ------------------------------------------------------------------------


class _FakeSinkInput:
    def __init__(self, index, pid, name, volume):
        self.index = index
        self.proplist = {
            "application.process.id": str(pid),
            "application.name": name,
        }
        self.volume_value = volume


class _FakePulse:
    """Nachbau der genutzten pulsectl-Oberflaeche."""

    instances: list["_FakePulse"] = []

    def __init__(self, _name=None, threading_lock=False):
        self.sink_inputs = list(self.__class__.preset)
        self.__class__.instances.append(self)

    preset: list = []

    def sink_input_list(self):
        return self.sink_inputs

    def volume_get_all_chans(self, si):
        return si.volume_value

    def volume_set_all_chans(self, si, value):
        si.volume_value = value

    def close(self):
        pass


@linux_only
def test_pulse_sessions_filtert_eigenen_prozess(monkeypatch):
    import os

    from fleech import audiofocus

    fremd = _FakeSinkInput(1, 4711, "Firefox", 0.8)
    eigen = _FakeSinkInput(2, os.getpid(), "Fleech", 1.0)
    _FakePulse.preset = [fremd, eigen]
    monkeypatch.setitem(
        sys.modules, "pulsectl", types.SimpleNamespace(Pulse=_FakePulse)
    )

    sessions = audiofocus._PulseSessions()
    found = list(sessions.iter_foreign_sessions())
    assert [name for name, _ in found] == ["Firefox"]

    # Volume-Adapter: gleiche Schnittstelle wie pycaw → Ducker-Fade funktioniert.
    _name, volume = found[0]
    assert volume.GetMasterVolume() == pytest.approx(0.8)
    volume.SetMasterVolume(0.2, None)
    assert fremd.volume_value == pytest.approx(0.2)


@linux_only
def test_ducker_mit_pulse_backend_duckt_und_restauriert(monkeypatch):
    from fleech import audiofocus

    fremd = _FakeSinkInput(1, 4711, "Spotify", 1.0)
    _FakePulse.preset = [fremd]
    monkeypatch.setitem(
        sys.modules, "pulsectl", types.SimpleNamespace(Pulse=_FakePulse)
    )

    ducker = audiofocus.PlaybackDucker(
        duck_level=0.25, fade_ms=0, sessions=audiofocus._PulseSessions()
    )
    ducker.duck()
    assert fremd.volume_value == pytest.approx(0.25)
    ducker.restore()
    assert fremd.volume_value == pytest.approx(1.0)


# -- Maus-Hotkeys (Linux: on_click statt win32_event_filter) ------------------------------


def test_pynput_mouse_token_kennt_x11_buttons():
    from fleech.hotkey import pynput_mouse_token

    assert pynput_mouse_token(types.SimpleNamespace(name="button8")) == "mouse4"
    assert pynput_mouse_token(types.SimpleNamespace(name="button9")) == "mouse5"
    assert pynput_mouse_token(types.SimpleNamespace(name="middle")) == "mouse_middle"
    assert pynput_mouse_token(types.SimpleNamespace(name="left")) is None


def test_hotkeymanager_on_click_aktiviert_und_deaktiviert():
    from fleech.hotkey import HotkeyManager, HotkeySpec

    events = []
    mgr = HotkeyManager(
        on_activate=lambda name: events.append(("on", name)),
        on_deactivate=lambda name: events.append(("off", name)),
    )
    mgr.set_bindings({"dictate": HotkeySpec.parse("mouse5")})

    button = types.SimpleNamespace(name="button9")
    mgr._on_click(0, 0, button, True)
    mgr._on_click(0, 0, button, False)
    assert events == [("on", "dictate"), ("off", "dictate")]

    # Ungebundene/unbekannte Tasten: keine Reaktion.
    mgr._on_click(0, 0, types.SimpleNamespace(name="left"), True)
    assert len(events) == 2


# -- Fokus-Restore-Dispatch ---------------------------------------------------------------


@linux_only
def test_focusrestore_dispatcht_nach_x11(monkeypatch):
    from fleech.ui import focusrestore, x11tools

    monkeypatch.setattr(x11tools, "active_window_id", lambda: 42)
    activated = []
    monkeypatch.setattr(
        x11tools, "activate_window", lambda wid: activated.append(wid) or True
    )

    target = focusrestore.capture_focus_target()
    assert target is not None and target.hwnd == 42
    assert focusrestore.restore_focus_target(target)
    assert activated == [42]


@linux_only
def test_focusrestore_ohne_fenster_ist_none(monkeypatch):
    from fleech.ui import focusrestore, x11tools

    monkeypatch.setattr(x11tools, "active_window_id", lambda: None)
    assert focusrestore.capture_focus_target() is None
    assert focusrestore.restore_focus_target(None) is False


# -- Recorder: Samplerate-Fallback + Rueck-Resampling -------------------------------------


class _FakeStream:
    def __init__(self, samplerate):
        self.samplerate = samplerate
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        pass


def _fake_sounddevice(supported_rate):
    class FakePortAudioError(Exception):
        pass

    def input_stream(samplerate, channels, dtype, device, callback):
        if samplerate != supported_rate:
            raise FakePortAudioError(f"Invalid sample rate {samplerate}")
        return _FakeStream(samplerate)

    return types.SimpleNamespace(
        PortAudioError=FakePortAudioError,
        InputStream=input_stream,
        query_devices=lambda device=None, kind=None: {"default_samplerate": float(supported_rate)},
    )


def test_recorder_faellt_auf_geraeterate_zurueck(monkeypatch):
    import numpy as np

    from fleech.audio import Recorder

    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sounddevice(48000))
    r = Recorder(16000, device=3)  # int-Device: keine Pulse-/ALSA-Aufloesung noetig
    r.start()
    assert r._capture_rate == 48000
    assert r.recording

    # 1 s bei 48 kHz einspeisen → stop() liefert ~1 s bei 16 kHz.
    block = np.ones((48000, 1), dtype=np.float32) * 0.5
    r._callback(block, len(block), None, None)
    assert r.position == pytest.approx(1.0)
    audio = r.stop()
    assert audio.size == pytest.approx(16000, abs=2)
    assert float(audio.max()) == pytest.approx(0.5, abs=1e-3)


def test_recorder_wunschrate_bleibt_ohne_fallback(monkeypatch):
    import numpy as np

    from fleech.audio import Recorder

    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sounddevice(16000))
    r = Recorder(16000, device=3)
    r.start()
    assert r._capture_rate == 16000
    r._callback(np.zeros((1600, 1), dtype=np.float32), 1600, None, None)
    assert r.stop().size == 1600


def test_session_kind_detection(monkeypatch):
    """Wayland soll benannt werden koennen, statt Funktionen still ausfallen zu lassen."""
    import fleech.platformpaths as pp

    monkeypatch.setattr(pp.sys, "platform", "linux")
    monkeypatch.setattr(pp.os, "environ", {"WAYLAND_DISPLAY": "wayland-0"})
    assert pp.session_kind() == "wayland"
    monkeypatch.setattr(pp.os, "environ", {"XDG_SESSION_TYPE": "Wayland"})
    assert pp.session_kind() == "wayland"
    monkeypatch.setattr(pp.os, "environ", {"DISPLAY": ":0"})
    assert pp.session_kind() == "x11"
    monkeypatch.setattr(pp.os, "environ", {})
    assert pp.session_kind() == "unknown"
    monkeypatch.setattr(pp.sys, "platform", "win32")
    assert pp.session_kind() == "windows"


# -- Aufblaeh-Erkennung (added_ratio, v2.1.0) --------------------------------------
