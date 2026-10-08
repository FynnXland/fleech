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
    # Willkommen, KI, Mikrofon, Taste, Modi, Verlauf, Probediktat (ohne Modell-
    # Kontext keine Einrichtungsseite).
    assert list(dlg._pages) == ["welcome", "ki", "microphone", "controls", "modes",
                                "verlauf", "finish"]
    assert not dlg._back_btn.isEnabled()          # Seite 1: kein Zurueck

    for _ in range(6):
        dlg._go_next()
    assert dlg._stack.currentIndex() == dlg._pages["finish"]
    assert dlg._next_btn.text() == "Los geht's"
    assert dlg._skip_btn.isHidden() or not dlg._skip_btn.isVisible()

    dlg._go_next()                                # letzter Klick = Abschluss
    assert settings.general.onboarding_done is True

def test_ueberspringen_beendet_x_heisst_spaeter(qapp, monkeypatch):
    """6.2.0: „Überspringen" ist eine Entscheidung und setzt das Flag. Das X (Esc)
    heisst „spaeter" — wer mitten in der Einrichtung schliesst, bekommt sie beim
    naechsten Start wieder, statt mit einem halb eingerichteten Fleech allein
    zu bleiben."""
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    dlg, settings = _onboarding()
    dlg.reject()                                  # Esc/X
    assert settings.general.onboarding_done is False

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

def _mit_einrichtung(monkeypatch, settings=None, **kw):
    from fleech.ui.onboarding import OnboardingDialog
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    return OnboardingDialog(
        settings or UserSettings(), lambda: ["Mikrofon (USB)"], audio=False,
        endpoints=[_FakeEndpoint()], stt_model="large-v3-turbo", **kw,
    )


def test_einrichtung_kommt_nach_der_ki_wahl_und_startet_erst_dann(qapp, monkeypatch):
    """Was geladen wird, haengt an der KI-Wahl — vorher darf nichts laden."""
    from fleech.ui.setuppage import SetupPage

    _fake_setup_lage(monkeypatch, lage="ready", modelle=(), whisper=False)
    gestartet = []
    monkeypatch.setattr(SetupPage, "start", lambda self: gestartet.append(True))
    dlg = _mit_einrichtung(monkeypatch)
    assert dlg._pages["ki"] < dlg._pages["setup"] < dlg._pages["microphone"]
    assert gestartet == []                        # beim Oeffnen: nichts
    dlg._go_next()                                # → KI
    assert gestartet == []
    dlg._go_next()                                # KI gewaehlt → Downloads los
    assert gestartet == [True]
    assert dlg._stack.currentIndex() == dlg._pages["setup"]
    dlg.reject()


def test_einrichtung_wird_uebersprungen_wenn_alles_da_ist(qapp, monkeypatch):
    _fake_setup_lage(monkeypatch)                 # alles vorhanden
    dlg = _mit_einrichtung(monkeypatch)
    assert "setup" in dlg._pages
    dlg._go_next()                                # → KI
    dlg._go_next()                                # → direkt Mikrofon
    assert dlg._stack.currentIndex() == dlg._pages["microphone"]
    assert dlg._steps.text() == "Schritt 3 von 7"
    dlg._go_back()                                # zurueck ueberspringt sie auch
    assert dlg._stack.currentIndex() == dlg._pages["ki"]
    dlg.reject()


def test_einrichtung_fragt_den_plan_nach_der_ki_wahl(qapp, monkeypatch):
    """Cloud gewaehlt → der Plan kommt ohne Sprachmodell zurueck (nur Erkennung)."""
    _fake_setup_lage(monkeypatch, lage="ready", modelle=(), whisper=False)
    from fleech.llm import apikeys
    from fleech.ui.onboarding import OnboardingDialog
    from fleech.ui.setuppage import SetupPage
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    monkeypatch.setattr(SetupPage, "start", lambda self: None)
    settings = UserSettings()
    gefragt, gemeldet = [], []

    def plan():
        gefragt.append(settings.ki.anbieter)
        if settings.ki.anbieter == "ollama":
            return [_FakeEndpoint()], "large-v3-turbo", "http://127.0.0.1:11434"
        return [], "large-v3-turbo", ""

    dlg = OnboardingDialog(settings, lambda: [], audio=False, einrichtung=plan,
                           on_changed=gemeldet.append)
    dlg._go_next()                                # → KI
    apikeys.speichere("openai", "test-schluessel")
    dlg._ki_seite._cloud.setChecked(True)
    dlg._go_next()
    assert settings.ki.anbieter == "openai"
    assert "ki" in gemeldet
    assert gefragt[-1] == "openai"
    assert list(dlg._setup_page._rows) == ["stt"]
    dlg.reject()


def test_onboarding_pegel_haengt_am_namen_nicht_am_index(qapp, monkeypatch):
    """Die eingeschobene Einrichtungs-Seite darf den Mikrofon-Pegel nicht verschieben."""
    from fleech.ui.onboarding import OnboardingDialog
    from fleech.ui.setuppage import SetupPage

    _fake_setup_lage(monkeypatch, lage="missing", modelle=(), whisper=False)
    monkeypatch.setattr(SetupPage, "start", lambda self: None)
    gestartet = []
    monkeypatch.setattr(OnboardingDialog, "_start_level_stream",
                        lambda self: gestartet.append(self._stack.currentIndex()))
    dlg = _mit_einrichtung(monkeypatch)
    dlg._go_next()                                # → KI
    dlg._go_next()                                # → Einrichtung (Ollama fehlt)
    assert dlg._stack.currentIndex() == dlg._pages["setup"]
    assert gestartet == []
    dlg._go_next()                                # → Mikrofon
    assert gestartet == [dlg._pages["microphone"]]
    dlg.reject()


def test_download_zeile_zeigt_den_stand_auf_den_folgeseiten(qapp, monkeypatch):
    from fleech.ui.setuppage import SetupPage

    _fake_setup_lage(monkeypatch, lage="ready", modelle=(), whisper=False)
    monkeypatch.setattr(SetupPage, "start", lambda self: None)
    dlg = _mit_einrichtung(monkeypatch)
    dlg._setup_page._on_progress("llm:gemma3:4b", "42 % · noch ca. 2 Min.", 42)
    assert "42 %" in dlg._download_zeile.text()
    assert "Sprachmodell gemma3:4b" in dlg._download_zeile.text()
    dlg._stack.setCurrentIndex(dlg._pages["microphone"])
    assert not dlg._download_zeile.isHidden()
    dlg._stack.setCurrentIndex(dlg._pages["setup"])
    assert dlg._download_zeile.isHidden()         # dort steht es ausfuehrlich
    dlg.reject()


def test_abschluss_bricht_laufende_downloads_nicht_ab(qapp, monkeypatch):
    """„Los geht's" waehrend des Downloads: Fleech laedt weiter und meldet sich
    danach (on_ready). Nur das X haelt nach dem laufenden Schritt an."""
    from fleech.ui.setuppage import SetupPage

    _fake_setup_lage(monkeypatch, lage="ready", modelle=(), whisper=False)
    gestoppt = []
    monkeypatch.setattr(SetupPage, "stop", lambda self: gestoppt.append(True))
    dlg = _mit_einrichtung(monkeypatch)
    dlg._finish()
    assert gestoppt == []
    dlg2 = _mit_einrichtung(monkeypatch)
    dlg2.reject()
    assert gestoppt == [True]


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


# -- 6.2.0: Sprache, KI-Schritt, Taste, Probediktat ------------------------------------


def test_sprache_steht_vorn_und_wirkt_sofort(qapp, monkeypatch):
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    gemeldet: list = []
    dlg, settings = _onboarding(changed=gemeldet)
    assert dlg._pages["welcome"] == 0
    dlg._sprache_box.setCurrentIndex(dlg._sprache_box.findData("en"))
    assert settings.general.language == "en"
    assert "general" in gemeldet
    from fleech.ui.onboardingseiten import probediktat

    probediktat.aktualisiere(dlg)
    assert "first dictation" in dlg._probe_beispiel.text()


def test_ki_schritt_vorbelegt_und_lokal_mit_katalog(qapp):
    dlg, _settings = _onboarding()
    seite = dlg._ki_seite
    assert seite._lokal.isChecked()               # Vorgabe: lokal
    assert seite._lokal_modell.currentData() == "gemma3:4b"
    assert "empfohlen" in seite._lokal_modell.currentText()
    assert "Diktaten" in seite._lokal_notiz.text()
    assert not seite._cloud_box.isVisibleTo(seite)


def test_ki_schritt_cloud_ohne_schluessel_haelt_an(qapp, monkeypatch):
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    dlg, settings = _onboarding()
    dlg._go_next()                                # → KI
    dlg._ki_seite._cloud.setChecked(True)
    dlg._go_next()
    assert dlg._stack.currentIndex() == dlg._pages["ki"]     # bleibt stehen
    assert "Schlüssel" in dlg._ki_seite._fehler.text()
    assert settings.ki.anbieter == "ollama"                  # nichts geschrieben
    dlg._ki_seite._lokal.setChecked(True)
    dlg._go_next()
    assert dlg._stack.currentIndex() == dlg._pages["microphone"]


def test_ki_schritt_ohne_ki(qapp, monkeypatch):
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    gemeldet: list = []
    dlg, settings = _onboarding(changed=gemeldet)
    dlg._go_next()
    dlg._ki_seite._aus.setChecked(True)
    dlg._go_next()
    assert settings.ki.anbieter == "aus"
    assert gemeldet.count("ki") == 1


def test_ki_schritt_empfehlung_wird_nicht_festgeschrieben(qapp, monkeypatch):
    """Leer heisst „was Fleech empfiehlt" — so greift ein neuer Katalog ohne Zutun.
    Ein ausdruecklich anderes Modell wird gespeichert."""
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    dlg, settings = _onboarding()
    seite = dlg._ki_seite
    assert seite.commit() is False and settings.ki.modell == ""
    seite._lokal_modell.setCurrentIndex(seite._lokal_modell.findData("gemma3:12b"))
    assert seite.commit() is True and settings.ki.modell == "gemma3:12b"


def test_ki_schritt_cloud_liste_markiert_neueres(qapp):
    from fleech.llm import apikeys

    apikeys.speichere("openai", "test-schluessel")
    dlg, settings = _onboarding()
    seite = dlg._ki_seite
    seite._cloud.setChecked(True)
    seite._cloud_liste_da("openai", ["gpt-4o-mini", "gpt-5-mini", "gpt-5-nano"], "")
    eintraege = [seite._cloud_modell.itemData(i)
                 for i in range(seite._cloud_modell.count())]
    assert eintraege[:2] == ["gpt-4o-mini", "gpt-5-mini"]
    assert seite._cloud_modell.currentData() == "gpt-4o-mini"   # Wahl bleibt beim Nutzer
    assert "gpt-5-mini" in seite._cloud_status.text()
    seite._cloud_modell.setCurrentIndex(1)
    seite.commit()
    assert (settings.ki.anbieter, settings.ki.modell) == ("openai", "gpt-5-mini")


def test_taste_frei_waehlbar(qapp, monkeypatch):
    from fleech.hotkey import HotkeySpec
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    gemeldet: list = []
    dlg, settings = _onboarding(changed=gemeldet)
    dlg._on_taste_gewaehlt(HotkeySpec.parse("ctrl+alt+d"))
    assert settings.recording.hotkey == "ctrl+alt+d"
    assert "hotkeys" in gemeldet
    assert "F9" not in dlg._hold_radio.text()
    # Loeschen gibt es hier nicht: ohne Diktat-Taste ginge gar nichts.
    dlg._on_taste_gewaehlt(None)
    assert settings.recording.hotkey == "ctrl+alt+d"
    assert dlg._taste_feld.spec() is not None


def test_probediktat_im_dialog(qapp, monkeypatch):
    from fleech.usersettings import UserSettings

    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    dlg, _settings = _onboarding()
    dlg._stack.setCurrentIndex(dlg._pages["finish"])
    assert "F9" in dlg._probe_anleitung.text()
    dlg._probe_feld.setPlainText("Das ist mein erstes Diktat.")
    assert "Angekommen" in dlg._probe_status.text()


def test_setup_page_plant_neu_und_meldet_den_stand(qapp, monkeypatch):
    _fake_setup_lage(monkeypatch, lage="ready", modelle=(), whisper=False)
    page = _setup_page()
    assert list(page._rows) == ["ollama", "llm:gemma3:4b", "stt"]
    page.neu_planen([], "large-v3-turbo", "")          # Cloud: nur Erkennung
    assert list(page._rows) == ["stt"]
    staende = []
    page.stand.connect(staende.append)
    page._on_progress("stt", "800 MB von etwa 1,6 GB · noch ca. 1 Min.", 50)
    assert staende == ["Erkennungsmodell large-v3-turbo: 800 MB von etwa 1,6 GB · "
                       "noch ca. 1 Min."]
    page.deleteLater()
