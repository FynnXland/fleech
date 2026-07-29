from fleech.config import load_config
from fleech.usersettings import UserSettings


def test_defaults_match_product_decisions():
    s = UserSettings()
    assert s.recording.mode == "hold"          # Hold-to-talk initial
    assert s.overlay.visibility == "during_activity"  # kein permanentes Overlay
    assert s.audio_focus.mode == "soft_duck"
    assert s.sounds.enabled is True            # dezente Sounds an
    assert s.output.intervention == "standard"
    assert s.math.priority == "mixed"


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "settings.json"
    s = UserSettings()
    s.recording.mode = "toggle"
    s.overlay.x, s.overlay.y = 1500, 400
    s.overlay.visibility = "auto_hide"
    s.overlay.opacity = 0.7
    s.sounds.volume = 0.15
    s.sounds.commit = False
    s.recording.math_toggle_hotkey = "f8"
    s.window.x, s.window.y, s.window.width = 10, 20, 900
    s.window.tray_hint_shown = True
    s.save(p)

    loaded = UserSettings.load(p)
    assert loaded.recording.mode == "toggle"
    assert loaded.recording.math_toggle_hotkey == "f8"
    assert (loaded.overlay.x, loaded.overlay.y) == (1500, 400)
    assert loaded.overlay.visibility == "auto_hide"
    assert loaded.overlay.opacity == 0.7
    assert loaded.sounds.volume == 0.15
    assert loaded.sounds.commit is False
    assert loaded.window.tray_hint_shown is True
    assert loaded.window.width == 900


def test_focus_settings_roundtrip_and_defaults(tmp_path):
    s = UserSettings()
    # Defaults: ruhige Power-User-App
    assert s.focus.respect_dnd is True
    assert s.focus.toasts_enabled is True
    assert s.focus.toast_long_processing is False   # keine Toast-Flut
    assert s.focus.notification_sounds is False
    assert s.focus.gaming_detection is True
    assert s.focus.gaming_overlay == "activity_only"

    p = tmp_path / "settings.json"
    s.focus.dnd_mute_sounds = True
    s.focus.gaming_sound_factor = 0.2
    s.focus.gaming_exceptions = ["mpv.exe", "vlc.exe"]
    s.save(p)
    loaded = UserSettings.load(p)
    assert loaded.focus.dnd_mute_sounds is True
    assert loaded.focus.gaming_sound_factor == 0.2
    assert loaded.focus.gaming_exceptions == ["mpv.exe", "vlc.exe"]


def test_load_missing_and_corrupt_files(tmp_path):
    assert UserSettings.load(tmp_path / "fehlt.json").recording.mode == "hold"
    bad = tmp_path / "kaputt.json"
    bad.write_text("{nicht json", encoding="utf-8")
    assert UserSettings.load(bad).recording.mode == "hold"


def test_unknown_keys_are_ignored(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(
        '{"recording": {"mode": "toggle", "zukunftsfeld": 1}, "unbekannt": {}}',
        encoding="utf-8",
    )
    s = UserSettings.load(p)
    assert s.recording.mode == "toggle"


def test_apply_to_config(tmp_path):
    cfg = load_config(tmp_path / "leer.yaml")
    s = UserSettings()
    s.recording.hotkey = "f8"
    s.recording.microphone = "Scarlett Solo USB"
    s.audio_focus.mode = "hard_focus"
    s.audio_focus.duck_level = 0.4
    s.apply_to(cfg)
    assert cfg.hotkey.dictate == "f8"
    assert cfg.audio.device == "Scarlett Solo USB"
    assert cfg.audio_focus.mode == "hard_focus"
    # Regelbare Restlautstaerke greift fuer Soft- UND Hard-Duck.
    assert cfg.audio_focus.duck_level == 0.4
    assert cfg.audio_focus.hard_duck_level == 0.4


def test_prefer_gpu_default_and_apply_to(tmp_path):
    cfg = load_config(tmp_path / "leer.yaml")
    s = UserSettings()
    assert s.advanced.prefer_gpu is True   # Default: GPU nutzen (mit Auto-Fallback)
    s.apply_to(cfg)
    assert cfg.stt.device == "auto"

    s.advanced.prefer_gpu = False
    s.apply_to(cfg)
    assert cfg.stt.device == "cpu"


def test_trigger_word_empty_keeps_config_value(tmp_path):
    cfg = load_config(tmp_path / "leer.yaml")
    base = cfg.command.trigger_word
    s = UserSettings()
    assert s.output.trigger_word == ""  # Default: config.yaml gilt
    s.apply_to(cfg)
    assert cfg.command.trigger_word == base


def test_trigger_word_override_and_roundtrip(tmp_path):
    cfg = load_config(tmp_path / "leer.yaml")
    s = UserSettings()
    s.output.trigger_word = "  Kimono "
    s.apply_to(cfg)
    assert cfg.command.trigger_word == "Kimono"  # getrimmt

    p = tmp_path / "settings.json"
    s.save(p)
    assert UserSettings.load(p).output.trigger_word == "  Kimono "


def test_prefer_gpu_persists_across_restart(tmp_path):
    p = tmp_path / "settings.json"
    s = UserSettings()
    s.advanced.prefer_gpu = False
    s.save(p)
    loaded = UserSettings.load(p)
    assert loaded.advanced.prefer_gpu is False  # ueberlebt "Neustart" (Reload von Disk)


# -- App-Regeln mit Fenstertitel (W3-16) ------------------------------------------

def test_app_rule_parsen_und_formatieren():
    from fleech.usersettings import format_app_rule, parse_app_rule

    assert parse_app_rule("Code.exe") == ("Code.exe", "")
    assert parse_app_rule("Code.exe :: Fleech") == ("Code.exe", "Fleech")
    assert parse_app_rule("  Code.exe::Fleech  ") == ("Code.exe", "Fleech")
    assert parse_app_rule("") == ("", "")
    assert format_app_rule("Code.exe") == "Code.exe"
    assert format_app_rule("Code.exe", "Fleech") == "Code.exe :: Fleech"
    assert format_app_rule("Code.exe", "  ") == "Code.exe"


def test_alte_eintraege_verhalten_sich_unveraendert():
    """Bestehende settings.json ohne '::' duerfen sich nicht anders verhalten."""
    from fleech.usersettings import app_rule_matches

    assert app_rule_matches("Code.exe", "code.exe", "irgendein Titel")
    assert app_rule_matches("Code.exe", "Code.exe", "")
    assert not app_rule_matches("Code.exe", "Discord.exe", "")


def test_titel_bedingung_greift_als_teilstring():
    from fleech.usersettings import app_rule_matches

    rule = "Code.exe :: Fleech"
    assert app_rule_matches(rule, "Code.exe", "pipeline.py — Fleech — Visual Studio Code")
    assert app_rule_matches(rule, "Code.exe", "FLEECH gross geschrieben")  # case-insensitiv
    assert not app_rule_matches(rule, "Code.exe", "andere-app — Visual Studio Code")
    assert not app_rule_matches(rule, "Code.exe", "")   # kein Titel ermittelbar


# -- Mathe-Stufe (v3.0.0: nur noch an/aus, kein Cloud-Umschaltweg) -----------------

def test_math_level_ableitung():
    from fleech.usersettings import MathSettings, math_level

    m = MathSettings()
    assert math_level(m) == "auto"
    m.enabled = False
    assert math_level(m) == "off"


def test_apply_math_level_setzt_alle_felder():
    """„auto" schaltet Automatik UND Haertung — es gibt keinen anderen Weg mehr."""
    from fleech.usersettings import MathSettings, apply_math_level

    m = MathSettings()
    apply_math_level(m, "auto")

    apply_math_level(m, "off")
    assert m.enabled is False


def test_math_level_ist_rundreise_stabil():
    from fleech.usersettings import (MATH_LEVELS, MathSettings, apply_math_level,
                                     math_level)

    assert MATH_LEVELS == ("off", "auto")      # Umschalt-Stufen sind entfallen
    for level in MATH_LEVELS:
        m = MathSettings()
        apply_math_level(m, level)
        assert math_level(m) == level, level


# -- D3: EIN Regler statt vieler Einzelfelder (Pillen-Rand, Windows-Banner) --------

def test_overlay_compactness_hin_und_zurueck():
    """Jede Stufe muss sich aus den vier Randwerten wieder ableiten lassen."""
    from fleech.usersettings import (OVERLAY_COMPACTNESS, OverlaySettings,
                                     apply_overlay_compactness, overlay_compactness)

    for level, _label in OVERLAY_COMPACTNESS:
        o = OverlaySettings()
        apply_overlay_compactness(o, level)
        assert overlay_compactness(o) == level, level
    # Der Auslieferungszustand ist "normal" — die Stufe darf nichts verstellen.
    o = OverlaySettings()
    before = (o.edge_left, o.edge_right, o.edge_top, o.edge_bottom)
    apply_overlay_compactness(o, "normal")
    assert (o.edge_left, o.edge_right, o.edge_top, o.edge_bottom) == before


def test_overlay_compactness_findet_naechste_stufe_bei_handwerten():
    """Von Hand gesetzte Werte (alte settings.json) duerfen den Regler nie leer lassen."""
    from fleech.usersettings import OverlaySettings, overlay_compactness

    o = OverlaySettings()
    o.edge_left = o.edge_right = 11
    o.edge_top = o.edge_bottom = 5
    assert overlay_compactness(o) == "roomy"
    o.edge_left = o.edge_right = o.edge_top = o.edge_bottom = 0
    assert overlay_compactness(o) == "tight"


def test_toast_level_hin_und_zurueck():
    from fleech.usersettings import (TOAST_LEVELS, FocusSettings, apply_toast_level,
                                     toast_level)

    for level, _label in TOAST_LEVELS:
        f = FocusSettings()
        apply_toast_level(f, level)
        assert toast_level(f) == level, level


def test_toast_level_none_schaltet_auch_kritische_ab():
    """„Nichts" muss wirklich still sein — sonst waere die Stufe eine Luege."""
    from fleech.usersettings import FocusSettings, apply_toast_level

    f = FocusSettings()
    apply_toast_level(f, "none")
    assert not f.toasts_enabled and not f.toast_critical_always
    assert not any((f.toast_background_info, f.toast_provider_quota,
                    f.toast_long_processing))


def test_toast_level_wichtiges_meldet_probleme_aber_keinen_status():
    """Die Trennlinie: Probleme ja, Statusmeldungen nein."""
    from fleech.usersettings import FocusSettings, apply_toast_level

    f = FocusSettings()
    apply_toast_level(f, "important")
    assert f.toast_critical_always and f.toast_provider_quota   # Probleme
    assert not f.toast_background_info and not f.toast_long_processing  # Status


def test_toast_level_zeigt_alles_solange_ein_statusbanner_an_ist():
    """Der Regler darf nie weniger behaupten, als tatsaechlich passiert.

    Der Auslieferungszustand hat `toast_background_info` an — also ist die ehrliche
    Anzeige "Alles", nicht "Wichtiges".
    """
    from fleech.usersettings import FocusSettings, toast_level

    assert toast_level(FocusSettings()) == "all"
    f = FocusSettings()
    f.toast_background_info = False
    f.toast_long_processing = True
    assert toast_level(f) == "all"
