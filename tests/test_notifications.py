"""Policy-Simulationen: DND an/aus, Gaming an/aus, Toast/Sound erlaubt vs. unterdrueckt."""

from fleech.ui.notifications import NotificationPolicy, Notifier, TOAST_KINDS
from fleech.ui.windowsfocus import FocusContext
from fleech.usersettings import FocusSettings


def ctx(dnd=False, fullscreen=False, d3d=False, proc=""):
    return FocusContext(dnd=dnd, fullscreen=fullscreen, d3d_fullscreen=d3d,
                        foreground_process=proc)


def policy(**overrides):
    s = FocusSettings()
    for k, v in overrides.items():
        setattr(s, k, v)
    return NotificationPolicy(s)


# -- Toasts -------------------------------------------------------------------------


def test_normal_conditions_allow_configured_toasts():
    p = policy()
    assert p.allow_toast("background_info", ctx())
    assert p.allow_toast("provider_quota", ctx())
    assert not p.allow_toast("long_processing", ctx())  # Default: aus


def test_dnd_suppresses_noncritical_toasts():
    p = policy()
    assert not p.allow_toast("background_info", ctx(dnd=True))
    assert not p.allow_toast("provider_quota", ctx(dnd=True))


def test_critical_toast_survives_dnd_and_gaming_and_global_off():
    p = policy(toasts_enabled=False)
    assert p.allow_toast("critical_error", ctx(dnd=True, d3d=True))
    p2 = policy(toast_critical_always=False)
    assert not p2.allow_toast("critical_error", ctx())


def test_respect_dnd_can_be_disabled():
    p = policy(respect_dnd=False)
    assert p.allow_toast("background_info", ctx(dnd=True))


def test_dnd_unknown_is_treated_as_no_dnd():
    p = policy()
    assert p.allow_toast("background_info", ctx(dnd=None))


def test_gaming_suppresses_noncritical_toasts():
    p = policy()
    assert not p.allow_toast("background_info", ctx(d3d=True))
    assert not p.allow_toast("background_info", ctx(fullscreen=True))


def test_gaming_detection_can_be_disabled():
    p = policy(gaming_detection=False)
    assert p.allow_toast("background_info", ctx(d3d=True))


def test_gaming_exception_list():
    p = policy(gaming_exceptions=["mpv.exe", " VLC.EXE "])
    assert p.allow_toast("background_info", ctx(fullscreen=True, proc="mpv.exe"))
    assert p.allow_toast("background_info", ctx(fullscreen=True, proc="vlc.exe"))
    assert not p.allow_toast("background_info", ctx(fullscreen=True, proc="game.exe"))


def test_global_toast_switch():
    p = policy(toasts_enabled=False)
    assert not p.allow_toast("background_info", ctx())


def test_unknown_toast_kind_is_suppressed():
    assert not policy().allow_toast("quatsch", ctx())


# -- Sounds -------------------------------------------------------------------------


def test_sounds_allowed_normally():
    d = policy().sound_decision(ctx())
    assert d.allowed and d.volume_factor == 1.0


def test_dnd_mutes_sounds_only_if_configured():
    assert policy().sound_decision(ctx(dnd=True)).allowed
    assert not policy(dnd_mute_sounds=True).sound_decision(ctx(dnd=True)).allowed


def test_gaming_reduces_sound_volume():
    d = policy(gaming_sound_factor=0.5).sound_decision(ctx(d3d=True))
    assert d.allowed and d.volume_factor == 0.5
    d0 = policy(gaming_sound_factor=0.0).sound_decision(ctx(d3d=True))
    assert not d0.allowed


# -- Overlay ------------------------------------------------------------------------


def test_overlay_override_matrix():
    p = policy()
    assert p.overlay_override(ctx()) is None
    assert p.overlay_override(ctx(d3d=True)) == "activity_only"
    assert p.overlay_override(ctx(dnd=True)) == "activity_only"
    assert policy(gaming_overlay="hidden").overlay_override(ctx(d3d=True)) == "hidden"
    assert policy(gaming_overlay="unchanged").overlay_override(ctx(d3d=True)) is None
    assert policy(gaming_exceptions=["mpv.exe"]).overlay_override(
        ctx(fullscreen=True, proc="mpv.exe")) is None


# -- Notifier (mit Fakes) --------------------------------------------------------------


class FakeTray:
    def __init__(self):
        self.toasts = []

    def notify(self, title, message):
        self.toasts.append((title, message))


class FakeSounds:
    def __init__(self):
        self.played = []

    def play(self, event, volume_factor=1.0):
        self.played.append((event, volume_factor))


class FakeProbe:
    def __init__(self, context):
        self.context = context

    def query(self):
        return self.context


def make_notifier(context, **settings):
    tray, sounds = FakeTray(), FakeSounds()
    n = Notifier(policy(**settings), tray, sounds, FakeProbe(context))
    n.refresh()
    return n, tray, sounds


def test_notifier_shows_and_suppresses_toasts():
    n, tray, _ = make_notifier(ctx())
    assert n.toast("background_info", "T", "m")
    assert tray.toasts == [("T", "m")]
    n2, tray2, _ = make_notifier(ctx(dnd=True))
    assert not n2.toast("background_info", "T", "m")
    assert tray2.toasts == []


def test_notifier_cooldown_prevents_toast_flood():
    n, tray, _ = make_notifier(ctx())
    assert n.toast("provider_quota", "T", "1")
    assert not n.toast("provider_quota", "T", "2")   # Cooldown
    assert n.toast("provider_quota", "T", "3", bypass_cooldown=True)
    assert len(tray.toasts) == 2


def test_notifier_sound_applies_gaming_factor():
    n, _, sounds = make_notifier(ctx(d3d=True), gaming_sound_factor=0.4)
    n.sound("start")
    assert sounds.played == [("start", 0.4)]
    n2, _, sounds2 = make_notifier(ctx(dnd=True), dnd_mute_sounds=True)
    n2.sound("start")
    assert sounds2.played == []


def test_notification_accent_sound_only_for_critical_and_optin():
    n, _, sounds = make_notifier(ctx(), notification_sounds=True)
    n.toast("critical_error", "T", "m")
    assert ("error", 1.0) in [(e, f) for e, f in sounds.played] or \
           any(e == "error" for e, _ in sounds.played)
    n2, _, sounds2 = make_notifier(ctx(), notification_sounds=False)
    n2.toast("critical_error", "T", "m")
    assert sounds2.played == []


def test_all_toast_kinds_have_settings_fields():
    s = FocusSettings()
    for field, _critical in TOAST_KINDS.values():
        assert hasattr(s, field), field
