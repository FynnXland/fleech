"""Erststart: Onboarding-Assistent und Einrichtungsseite (Ollama/Modelle).

Teil der Qt-Smoke-Tests (offscreen, siehe conftest.py): Widgets bauen, Zustaende
schalten, Persistenz-Callbacks pruefen. Keine Optik-Pruefung.
"""

import pytest

pytest.importorskip("PySide6")


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
    assert dlg._stack.count() == 6   # + Verlauf-Seite (5.10.1)
    assert not dlg._back_btn.isEnabled()          # Seite 1: kein Zurueck

    for _ in range(5):        # eine Seite mehr seit der Verlauf-Frage (5.10.1)
        dlg._go_next()
    assert dlg._stack.currentIndex() == 5
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


# -- Bedienmodus "Anstupsen" (E-7/A-10) ---------------------------------------------

def test_bedienung_seite_bietet_anstupsen_als_dritte_option(qapp, monkeypatch):
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    dlg, _ = _onboarding()
    assert hasattr(dlg, "_nudge_radio")
    assert not dlg._nudge_radio.isChecked()   # Vorgabe ist "hold"


def test_anstupsen_wird_korrekt_vorausgewaehlt(qapp):
    """E-7: Wer 'Anstupsen' eingestellt hat und die Einfuehrung erneut oeffnet, sah
    vorher faelschlich 'Halten' vorausgewaehlt."""
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    settings.recording.mode = "nudge"
    dlg, _ = _onboarding(settings=settings)
    assert dlg._nudge_radio.isChecked()
    assert not dlg._hold_radio.isChecked()
    assert not dlg._toggle_radio.isChecked()


def test_anstupsen_waehlen_schreibt_nudge(qapp, monkeypatch):
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    changed: list = []
    dlg, settings = _onboarding(changed=changed)
    dlg._nudge_radio.setChecked(True)
    assert settings.recording.mode == "nudge"
    assert "recording" in changed


# -- Formeln: kein toter Hotkey, keine gesprochenen Delimiter (E-6/A-10) ------------

def test_formeln_seite_nennt_keinen_toten_hotkey(qapp):
    from PySide6.QtWidgets import QLabel

    dlg, _ = _onboarding()
    modes_page = dlg._stack.widget(dlg._pages["modes"])
    labels_text = " ".join(l.text() for l in modes_page.findChildren(QLabel))
    assert "Strg+Alt+M" not in labels_text
    assert "Formel Ende" not in labels_text
    assert "automatisch" in labels_text.lower()


# -- Willkommenstext ohne falsche Schrittzahl (E-18) --------------------------------

def test_willkommenstext_nennt_keine_schrittzahl(qapp):
    from PySide6.QtWidgets import QLabel

    dlg, _ = _onboarding()
    welcome_page = dlg._stack.widget(dlg._pages["welcome"])
    labels_text = " ".join(l.text() for l in welcome_page.findChildren(QLabel))
    assert "vier " not in labels_text
    assert "vier kurzen Schritten" not in labels_text


# -- Autostart-Wunsch bewahren (v2.1.0) --------------------------------------------

def test_fehlgeschlagenes_schreiben_loescht_den_wunsch_nicht(qapp, monkeypatch):
    """Der reale Fehler: Scheiterte das Schreiben einmal, setzte Fleech den Wunsch
    auf False — und der naechste Start LOESCHTE den Eintrag dann aktiv."""
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
    assert all(s.state == "done" for s in page._steps)
    assert not page._btn.isEnabled()               # nichts zu tun
    assert page._btn.text() == "Alles bereit"
    page.deleteLater()

def test_setup_page_frischer_rechner_bietet_einrichtung(qapp, monkeypatch):
    _fake_setup_lage(monkeypatch, lage="missing", modelle=(), whisper=False)
    page = _setup_page()
    assert not all(s.state == "done" for s in page._steps)
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
    assert dlg._stack.count() == 7   # 6 + Einrichtungsseite
    assert dlg._pages["setup"] == 1               # direkt nach dem Willkommen
    assert dlg._pages["microphone"] == 2
    dlg.reject()

    # Fertig eingerichtet: keine Seite mit drei Haken zum Durchklicken.
    _fake_setup_lage(monkeypatch)
    dlg2 = bauen()
    assert dlg2._stack.count() == 6
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


# -- Verlauf-Frage (5.10.1) --------------------------------------------------------------


def test_onboarding_fragt_nach_dem_verlauf(qapp, monkeypatch):
    """Aus dem externen Gutachten: Der volle Wortlaut jedes Diktats landet
    unverschlüsselt in einer SQLite-Datei, standardmäßig an, und der Schalter lag
    nur unter Einstellungen → Allgemein.

    Der Standardwert bleibt AN — Home und Insights leben davon. Was fehlte, war
    die bewusste Entscheidung: ein Opt-out, das niemand sieht, ist keins.
    """
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    dlg, settings = _onboarding()

    assert "verlauf" in dlg._pages, "Keine Seite zum Verlauf im Onboarding"
    assert settings.general.save_history is True          # Vorgabe unverändert
    assert dlg._verlauf_cb.isChecked() is True

    dlg._verlauf_cb.setChecked(False)
    assert settings.general.save_history is False, "Abwahl wirkt nicht"
    dlg._verlauf_cb.setChecked(True)
    assert settings.general.save_history is True


def test_die_verlauf_seite_kommt_vor_dem_probediktat(qapp, monkeypatch):
    """Wer gleich etwas diktiert, soll vorher entschieden haben, ob es
    aufgehoben wird."""
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    dlg, _ = _onboarding()
    assert dlg._pages["verlauf"] < dlg._pages["finish"]


def test_verlauf_abwahl_meldet_sich_beim_aufrufer(qapp, monkeypatch):
    """Ohne die Meldung bliebe der HistoryStore weiterschreiben, bis Fleech neu
    startet."""
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    gemeldet: list = []
    dlg, _ = _onboarding(changed=gemeldet)
    dlg._verlauf_cb.setChecked(False)
    assert "general" in gemeldet
