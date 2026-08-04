"""Gemeinsame Helfer der Qt-Smoke-Tests.

Liegt neben den Testdateien, damit mehrere Gruppen dasselbe Hauptfenster
aufbauen koennen, ohne den Aufbau zu kopieren.
"""

from fleech.usersettings import UserSettings


def make_main_window(tmp_path, monkeypatch, with_data=False):
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
