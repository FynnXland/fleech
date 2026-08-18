"""Profile und App-Zuordnung: Seiten, Regeln, Schnellwechsel, Suche, Auswahlliste.

Teil der Qt-Smoke-Tests (offscreen, siehe conftest.py): Widgets bauen, Zustaende
schalten, Persistenz-Callbacks pruefen. Keine Optik-Pruefung.
"""

import pytest

pytest.importorskip("PySide6")

from uihelpers import make_main_window


def test_punkt_schaltet_reihum_durch_die_profile(qapp):
    """Der Punkt war erst ein Modus-Zyklus (Mathe/Prompting), dann funktionslos.
    Jetzt waehlt er das Profil — inklusive Station „automatisch" am Ende.

    Das Standardprofil ist seit Befund G-B1 keine Station mehr: Es sah aus wie
    „App-Standard", legte aber die App-Zuordnung still. Der Zyklus geht damit
    ueber die echten Profile und endet bei „automatisch"."""
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.profiles import APP_STANDARD

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
    # Seit Befund G-B4 loest `active_profile_name` bei leerer Wahl die Ziel-App
    # auf — im Test fest verdrahtet, damit kein echter Vordergrund hineinspielt.
    fake.ziel_app_und_titel = lambda: ("", "")
    fake._profile_aktiv = lambda: DesktopApp._profile_aktiv(fake)
    fake._set_profile = lambda n: DesktopApp._set_profile(fake, n)
    # Seit 5.5.0 faerbt _set_profile zusaetzlich den Ring an der Pille.
    fake._melde_profilfarbe = lambda: DesktopApp._melde_profilfarbe(fake)
    fake.overlay.set_profile_color = lambda farbe: None
    fake.settings.save = lambda: None
    DesktopApp.cycle_profile(fake)
    assert fake.settings.profiles.active == "E-Mail"
    DesktopApp.cycle_profile(fake)
    assert fake.settings.profiles.active == ""          # zurueck auf automatisch
    assert gezeigt[-1].startswith(APP_STANDARD)
    DesktopApp.cycle_profile(fake)                      # und wieder von vorn
    assert fake.settings.profiles.active == "E-Mail"

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
    fake.ziel_app_und_titel = lambda: ("", "")
    fake._profile_aktiv = lambda: DesktopApp._profile_aktiv(fake)
    fake._set_profile = lambda n: DesktopApp._set_profile(fake, n)
    # Seit 5.5.0 faerbt _set_profile zusaetzlich den Ring an der Pille.
    fake._melde_profilfarbe = lambda: DesktopApp._melde_profilfarbe(fake)
    fake.overlay.set_profile_color = lambda farbe: None
    fake.settings.save = lambda: None
    DesktopApp.cycle_profile(fake)
    assert fake.settings.profiles.active == "E-Mail"

def test_profiles_page_assign_tags_and_default(qapp, tmp_path, monkeypatch):
    window, _p, store, settings, _c = make_main_window(tmp_path, monkeypatch, with_data=True)
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

    # Das Standardprofil laeuft seit Befund G-B1 nicht mehr im Schnellwechsel mit
    # (es legte von Hand gewaehlt die App-Zuordnung still). Der Haken dazu darf
    # dort dann auch nicht bedienbar aussehen.
    page._profiles_list.setCurrentRow(0)
    page._refresh_detail()
    assert page._quick_cb.isEnabled() is False
    assert page._quick_cb.isChecked() is False
    page._profiles_list.setCurrentRow(coding_row)
    page._refresh_detail()
    assert page._quick_cb.isEnabled() is True

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

def test_profilseite_stellt_die_diktiersprache_ein(qapp, tmp_path, monkeypatch):
    """Befund G-B6: Der Wirkungspfad (profile_sprache → ProfileOverrides.sprache →
    desktop._setze_sprache) stand seit 5.4.0 vollstaendig und war getestet —
    einstellen konnte man die Sprache nur von Hand in der settings.json."""
    from fleech.profiles import PROFILE_SPRACHEN, profile_sprache

    window, _p, _store, settings, _c = make_main_window(tmp_path, monkeypatch,
                                                        with_data=True)
    page = window.profiles
    page.refresh()
    items = settings.profiles.items
    zeile = next(i for i, p in enumerate(items) if not p.get("default"))
    page._profiles_list.setCurrentRow(zeile)
    page._refresh_detail()
    assert page._profile_sprache_combo.currentData() == ""       # wie Einstellungen

    page._profile_sprache_combo.setCurrentIndex(
        [v for v, _l in PROFILE_SPRACHEN].index("en"))
    assert profile_sprache(items[zeile]) == "en"

    # Und beim naechsten Blick steht sie auch wieder da.
    page._refresh_detail()
    assert page._profile_sprache_combo.currentData() == "en"


def test_profilseite_waehlt_das_aktive_profil(qapp, tmp_path, monkeypatch):
    """Befund E-4/G-B5: `profiles.active` liess sich nur ueber den Punkt an der
    Pille (nur waehrend einer Aufnahme) oder den ab Werk unbelegten Profil-Hotkey
    setzen — der Tooltip verwies dabei auf „die Profilseite", die es nicht konnte.

    Die Seite fasst die Pille NICHT selbst an: Sie meldet die Wahl ueber dasselbe
    Signal, das auch die Auswahlliste am Hotkey nimmt."""
    from fleech.profiles import APP_STANDARD

    window, _p, _store, settings, _c = make_main_window(tmp_path, monkeypatch,
                                                        with_data=True)
    page = window.profiles
    page.refresh()
    gemeldet = []
    page.profil_aktiv_gewaehlt.connect(gemeldet.append)

    # Erste Station ist „App-Standard" (= automatisch nach App), das Standardprofil
    # steht bewusst NICHT zur Wahl (Befund G-B1).
    assert page._aktiv_combo.itemText(0) == APP_STANDARD
    namen = [page._aktiv_combo.itemData(i) for i in range(page._aktiv_combo.count())]
    assert "Standard" not in namen

    ziel = next(p["name"] for p in settings.profiles.items if not p.get("default"))
    page._aktiv_combo.setCurrentIndex(page._aktiv_combo.findData(ziel))
    assert settings.profiles.active == ziel
    assert gemeldet == [ziel]

    page._aktiv_combo.setCurrentIndex(0)
    assert settings.profiles.active == ""
    assert gemeldet == [ziel, ""]

    # Profile global aus: die Zeile bleibt sichtbar, ist aber nicht mehr bedienbar
    # — ein Wechsel wuerde dort nichts bewirken (Befund G-B11).
    page._global_cb.setChecked(False)
    assert page._aktiv_combo.isEnabled() is False
    page._global_cb.setChecked(True)
    assert page._aktiv_combo.isEnabled() is True


def test_umbenanntes_profil_steht_auch_oben_richtig(qapp, tmp_path, monkeypatch):
    """Die Auswahlliste „Jetzt aktiv" darf keinen Namen zeigen, den es nicht mehr
    gibt — sonst zeigte sie eine Wahl an, die beim naechsten Diktat ins Leere
    liefe (`_app_profile_overrides` faellt dann auf automatisch zurueck)."""
    window, _p, _store, settings, _c = make_main_window(tmp_path, monkeypatch,
                                                        with_data=True)
    page = window.profiles
    page.refresh()
    zeile = next(i for i, p in enumerate(settings.profiles.items)
                 if not p.get("default"))
    page._profiles_list.setCurrentRow(zeile)
    page._detail_title.setText("Ganz neuer Name")
    page._on_rename_profile()
    namen = [page._aktiv_combo.itemData(i) for i in range(page._aktiv_combo.count())]
    assert "Ganz neuer Name" in namen


# -- „Wenn du jetzt diktierst" (Vorschlag G-2) ---------------------------------------


def _settings_mit_zuordnung():
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    settings.profiles.enabled = True
    settings.profiles.active = ""
    settings.profiles.items = [
        {"name": "Standard", "default": True, "intervention": "", "apps": []},
        {"name": "KI-Prompt", "intervention": "standard", "mode": "prompt",
         "apps": ["claude.exe"], "sprache": "en", "auto_send": True},
        {"name": "Notizen", "intervention": "strong", "apps": ["obsidian.exe :: Tagebuch"]},
    ]
    return settings


def test_jetzt_zeile_nennt_regel_und_wirkung():
    """Vorschlag G-2: Die Zeile fuehrt die Zuordnung vor, statt sie zu behaupten —
    inklusive der Regel, ueber die das Profil kam. Ohne sie faellt ein Tippfehler
    in einer Titel-Bedingung nie auf: Die Regel greift stumm einfach nie."""
    from fleech.ui.pages.jetztzeile import beschreibe_jetzt

    settings = _settings_mit_zuordnung()
    text = beschreibe_jetzt(settings, "claude.exe", "Fleech — Claude")
    assert "claude.exe" in text and "Fleech — Claude" in text
    assert "Profil KI-Prompt" in text and "Regel: claude.exe" in text
    assert "Ausgabe: KI-Prompt" in text
    assert "Sprache: Englisch" in text
    assert "schickt direkt ab" in text          # der Haken, der Enter drueckt

    # Titelregel: derselbe Prozess, anderer Kontext.
    text = beschreibe_jetzt(settings, "obsidian.exe", "2026-08-18 — Tagebuch")
    assert "Profil Notizen" in text and "Regel: obsidian.exe :: Tagebuch" in text
    text = beschreibe_jetzt(settings, "obsidian.exe", "Projektplan")
    assert "Profil Standard (Standardprofil)" in text

    # Von Hand gewaehlt sticht die Zuordnung — und sagt das auch.
    settings.profiles.active = "Notizen"
    text = beschreibe_jetzt(settings, "claude.exe", "")
    assert "Profil Notizen (von Hand gewählt)" in text

    # Global aus: kein Profil-Theater, sondern die ehrliche Auskunft.
    settings.profiles.enabled = False
    assert "ausgeschaltet" in beschreibe_jetzt(settings, "claude.exe", "")


def test_jetzt_zeile_kommt_ohne_vordergrund_klar():
    from fleech.ui.pages.jetztzeile import beschreibe_jetzt, ist_fleech_selbst

    settings = _settings_mit_zuordnung()
    assert "keine Anwendung erkennbar" in beschreibe_jetzt(settings, "", "")
    assert ist_fleech_selbst("Fleech.exe") and not ist_fleech_selbst("claude.exe")
    assert not ist_fleech_selbst("")


def test_apps_seite_zeigt_was_jetzt_passieren_wuerde(qapp, tmp_path, monkeypatch):
    """Und sie zeigt NICHT sich selbst: Wer die Seite ansieht, hat Fleech im
    Vordergrund — interessant ist die Anwendung, aus der er gerade kam."""
    window, _p, _store, settings, _c = make_main_window(tmp_path, monkeypatch,
                                                        with_data=True)
    monkeypatch.setattr("fleech.ui.windowsfocus.list_visible_window_processes",
                        lambda: ["claude.exe"])
    monkeypatch.setattr("fleech.ui.windowsfocus.foreground_now",
                        lambda: ("claude.exe", "Fleech — Claude"))
    page = window.apps
    settings.profiles.items = _settings_mit_zuordnung().profiles.items
    page.refresh()
    page._jetzt_aktualisieren()
    assert "Profil KI-Prompt" in page._jetzt.text()

    monkeypatch.setattr("fleech.ui.windowsfocus.foreground_now",
                        lambda: ("Fleech.exe", "Fleech"))
    page._jetzt_aktualisieren()
    text = page._jetzt.text()
    assert "(Fleech selbst)" in text
    assert "zuletzt claude.exe" in text          # der gemerkte fremde Vordergrund
    assert "Profil KI-Prompt" in text

    # Der Takt laeuft nur, solange die Seite sichtbar ist.
    from PySide6.QtGui import QHideEvent, QShowEvent

    page.showEvent(QShowEvent())
    assert page._jetzt_timer.isActive() is True
    page.hideEvent(QHideEvent())
    assert page._jetzt_timer.isActive() is False


def test_apps_page_assigns_profile_per_app(qapp, tmp_path, monkeypatch):
    """Die Apps-Seite dreht die Blickrichtung um: App waehlen → Profil bestimmen.

    Gespeichert wird weiter in `profil["apps"]` — alte settings.json bleiben ohne
    Migration gueltig."""
    window, _p, _store, settings, _c = make_main_window(tmp_path, monkeypatch,
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

def test_apps_liste_sortiert_nach_nutzung_und_meldet_unbekanntes_zuerst(
        qapp, tmp_path, monkeypatch):
    """Befund G-B8: Die Liste begann mit ALLEN sichtbaren Fensterprozessen in
    EnumWindows-Reihenfolge — die Seite sah aus wie ein Taskmanager, die
    meistgenutzte App stand irgendwo dazwischen und trug nur „laeuft" (ihre
    Wortzahl fiel weg), und der Tippfehler-Melder „noch nie gesehen" stand ganz
    unten. Jetzt: Unbekanntes zuerst, dann nach diktierten Woertern."""
    from PySide6.QtCore import Qt

    from fleech.ui.theme import AMBER

    window, _p, _store, settings, _c = make_main_window(tmp_path, monkeypatch,
                                                        with_data=True)
    # Code.exe: 2 Diktate, comet.exe: 1 — plus ein laufendes Programm ohne Verlauf.
    monkeypatch.setattr("fleech.ui.windowsfocus.list_visible_window_processes",
                        lambda: ["Code.exe", "NVIDIA Overlay.exe"])
    coding = next(p for p in settings.profiles.items
                  if str(p.get("name", "")).startswith("Coding"))
    coding["apps"] = ["Tippfehler.exe"]          # zugewiesen, gibt es aber nicht

    page = window.apps
    page.refresh()
    apps = [str(page._apps.item(i).data(Qt.UserRole))
            for i in range(page._apps.count())]
    assert apps[0] == "Tippfehler.exe"           # der Hinweis ganz oben
    assert page._apps.item(0).foreground().color().name().lower() == AMBER.lower()
    assert "noch nie gesehen" in page._apps.item(0).text()
    assert apps.index("Code.exe") < apps.index("comet.exe")     # mehr diktiert
    assert apps.index("comet.exe") < apps.index("NVIDIA Overlay.exe")

    # Zusaetze werden zusammengefasst statt zu verdraengen: Code.exe laeuft UND
    # hat Verlauf.
    zeile = page._apps.item(apps.index("Code.exe")).text()
    assert "läuft" in zeile and "Wörter diktiert" in zeile

    # Ohne gemerkte Auswahl steht die meistgenutzte App vorn — nicht Zeile 0
    # (die ist jetzt der Hinweis, frueher irgendein Systemprozess).
    assert page._aktuelle_app() == "Code.exe"


def test_titelregel_faellt_auf_das_profil_der_app_zurueck(qapp, tmp_path, monkeypatch):
    """Befund G-B8, zweiter Teil: Das Profilfeld der Titel-Ausnahme stand per
    Vorgabe auf dem ersten Nicht-Standard-Profil — wer einen Titel tippte und auf
    „Hinzufügen" drueckte, legte ungewollt eine „Geschäftlich"-Regel an. Jetzt
    steht dort das Profil, das in dieser App ohnehin gilt, sonst das
    Standardprofil."""
    from PySide6.QtCore import Qt

    window, _p, _store, settings, _c = make_main_window(tmp_path, monkeypatch,
                                                        with_data=True)
    monkeypatch.setattr("fleech.ui.windowsfocus.list_visible_window_processes",
                        lambda: ["Code.exe", "Discord.exe"])
    items = settings.profiles.items
    standard = next(p for p in items if p.get("default"))
    coding = next(p for p in items if str(p.get("name", "")).startswith("Coding"))

    page = window.apps
    page.refresh()
    apps = [str(page._apps.item(i).data(Qt.UserRole))
            for i in range(page._apps.count())]
    page._apps.setCurrentRow(apps.index("Discord.exe"))     # ohne Zuordnung
    assert page._regel_profil.currentData() == standard["name"]

    page._apps.setCurrentRow(apps.index("Code.exe"))
    page._profil_combo.setCurrentIndex(page._profil_combo.findData(coding["name"]))
    page._apps.setCurrentRow(apps.index("Code.exe"))
    assert page._regel_profil.currentData() == coding["name"]


def test_titelausnahme_auf_das_standardprofil_greift_wirklich(qapp):
    """Sonst waere die neue Wahlmoeglichkeit eine tote Regel: Das Standardprofil war
    in der Aufloesung NUR Fallback und nie Kandidat — „in diesem einen Fenster gilt
    wieder das Normale" liess sich damit gar nicht ausdruecken."""
    from fleech.profiles import profil_fuer_app

    items = [
        {"name": "Standard", "default": True, "intervention": "",
         "apps": ["chrome.exe :: Gmail"]},
        {"name": "Coding", "intervention": "minimal", "apps": ["chrome.exe"]},
    ]
    treffer, regel = profil_fuer_app(items, "chrome.exe", "Gmail - Posteingang")
    assert (treffer["name"], regel) == ("Standard", "chrome.exe :: Gmail")
    # Ohne den Titel bleibt es bei der Zuordnung der App.
    assert profil_fuer_app(items, "chrome.exe", "Fleech")[0]["name"] == "Coding"


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
    from fleech.profiles import ProfileOverrides

    # Coding hat keinen Modus-Slot und keinen eigenen Safe-Word-Schalter.
    assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(
        intervention="minimal", style_hints=["Fachbegriffe lassen"])

    # Mathe-Profil: Der Kommentar hier behauptete bis 5.10.2, es „erzwinge den
    # Formel-Modus fuer seine Apps" — das war falsch (Befund E-14). Einen
    # Formel-Modus gibt es seit v3.0.0 nicht, kein Codepfad hat mode_slot="math"
    # je ausgewertet. Das Profil setzt nur noch seinen Eingriffsgrad.
    fake._record_app = "calc.exe"
    assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(
        intervention="standard")

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
    from fleech.profiles import ProfileOverrides

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

def test_list_visible_window_processes_runs():
    from fleech.ui.windowsfocus import list_visible_window_processes

    apps = list_visible_window_processes()    # Best-Effort: darf nie raisen
    assert isinstance(apps, list)

def test_profil_zuordnung_beachtet_fenstertitel(qapp):
    """Derselbe Prozess, zwei Kontexte: die Titel-Regel muss gewinnen — und zwar
    unabhaengig davon, in welcher Reihenfolge die Profile stehen."""
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.profiles import ProfileOverrides

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

def test_bei_zwei_titelregeln_gewinnt_die_genauere(qapp):
    """Befund G-B7: Passen zwei Titel-Regeln, entschied bisher die Reihenfolge der
    Profile — „chrome.exe :: Gmail" fing „chrome.exe :: Gmail - Entwurf" ab, wenn
    es weiter oben stand. Genau im gedachten Anwendungsfall (ein Browser, viele
    Kontexte) griff die feine Regel damit nie, und nichts protokollierte es.
    Jetzt schlaegt die laengere Bedingung die kuerzere, in beiden Reihenfolgen."""
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.profiles import ProfileOverrides

    grob = {"name": "Mail", "intervention": "standard", "tags": [],
            "apps": ["chrome.exe :: Gmail"]}
    fein = {"name": "Entwurf", "intervention": "strong", "tags": [],
            "apps": ["chrome.exe :: Gmail - Entwurf"]}

    for reihenfolge in ([grob, fein], [fein, grob]):
        profiles = types.SimpleNamespace(enabled=True, items=list(reihenfolge))
        fake = types.SimpleNamespace(
            settings=types.SimpleNamespace(profiles=profiles),
            _record_app="chrome.exe", _record_title="Gmail - Entwurf",
        )
        assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(
            intervention="strong"), [p["name"] for p in reihenfolge]

        # Der grobe Fall bleibt der grobe Fall.
        fake._record_title = "Gmail - Posteingang"
        assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(
            intervention="standard"), [p["name"] for p in reihenfolge]


def test_profil_zuordnung_ohne_titel_attribut_bleibt_kompatibel(qapp):
    """Aeltere Aufrufer ohne _record_title duerfen nicht brechen."""
    import types

    from fleech.ui.desktop import DesktopApp
    from fleech.profiles import ProfileOverrides

    profiles = types.SimpleNamespace(enabled=True, items=[
        {"name": "Coding", "intervention": "minimal", "tags": [], "apps": ["Code.exe"]},
    ])
    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=profiles), _record_app="Code.exe")
    assert DesktopApp._app_profile_overrides(fake) == ProfileOverrides(intervention="minimal")


# -- Der Ring an der Pille folgt der App (Befund G-B4) --------------------------------


def _fake_app(items, app="", titel="", active=""):
    """Schlanke DesktopApp-Attrappe fuer die Profil-Anzeige.

    Nur die Methoden, die die Anzeige braucht — Vordergrund fest verdrahtet,
    damit kein echtes Fenster ins Ergebnis spielt."""
    import types

    from fleech.ui.desktop import DesktopApp

    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(
            profiles=types.SimpleNamespace(enabled=True, active=active, items=items),
            save=lambda: None,
        ),
        gezeigt=[], farben=[],
    )
    fake.overlay = types.SimpleNamespace(
        show_profile=fake.gezeigt.append, set_profile_color=fake.farben.append)
    fake.ziel_app_und_titel = lambda: (app, titel)
    fake.active_profile_name = lambda: DesktopApp.active_profile_name(fake)
    fake._melde_profilfarbe = lambda: DesktopApp._melde_profilfarbe(fake)
    fake._profile_aktiv = lambda: DesktopApp._profile_aktiv(fake)
    return fake


_ANZEIGE_PROFILE = [
    {"name": "Standard", "default": True, "intervention": "", "tags": [], "apps": []},
    {"name": "Coding", "intervention": "minimal", "tags": [], "apps": ["Code.exe"],
     "color": "#6E86C8"},
    {"name": "Mail", "intervention": "strong", "tags": [], "apps": ["olk.exe"],
     "color": "#E8A13C"},
]


def test_der_ring_folgt_der_app_und_nicht_nur_der_wahl_von_hand(qapp):
    """Befund G-B4: `active_profile_name` nannte ohne Wahl von Hand IMMER das
    Standardprofil — der Ring an der Pille zeigte in Outlook dieselbe Farbe wie im
    Editor, obwohl die Zuordnung ein anderes Profil vorsah. Jetzt loest er die
    Ziel-App auf, genau wie die Verarbeitung es spaeter tut."""
    from fleech.ui.desktop import DesktopApp

    fake = _fake_app(_ANZEIGE_PROFILE, app="Code.exe")
    assert DesktopApp.active_profile_name(fake) == "Coding"
    DesktopApp._melde_profilfarbe(fake)
    assert fake.farben[-1] == "#6E86C8"

    fake.ziel_app_und_titel = lambda: ("olk.exe", "Posteingang")
    assert DesktopApp.active_profile_name(fake) == "Mail"
    DesktopApp._melde_profilfarbe(fake)
    assert fake.farben[-1] == "#E8A13C"

    # Nicht zugewiesene App → weiterhin das Standardprofil.
    fake.ziel_app_und_titel = lambda: ("Discord.exe", "")
    assert DesktopApp.active_profile_name(fake) == "Standard"

    # Von Hand gewaehlt sticht die Zuordnung — unveraendert.
    fake.settings.profiles.active = "Mail"
    fake.ziel_app_und_titel = lambda: ("Code.exe", "")
    assert DesktopApp.active_profile_name(fake) == "Mail"


def test_die_namens_kapsel_erscheint_nur_beim_wechsel(qapp):
    """Der Ring wird bei jedem Aufnahmestart nachgezogen, die Kapsel nicht: Sie
    bei jedem Diktat zu zeigen waere nach drei Tagen Tapete. Interessant ist der
    Moment, in dem eine andere App ein anderes Profil mitbringt."""
    from fleech.ui.desktop import DesktopApp

    fake = _fake_app(_ANZEIGE_PROFILE, app="Code.exe")
    DesktopApp._on_profil_pruefen(fake)
    assert fake.gezeigt == ["Coding"]
    DesktopApp._on_profil_pruefen(fake)          # zweites Diktat, gleiche App
    assert fake.gezeigt == ["Coding"]
    assert fake.farben == ["#6E86C8", "#6E86C8"]  # der Ring wird trotzdem gesetzt

    fake.ziel_app_und_titel = lambda: ("olk.exe", "")
    DesktopApp._on_profil_pruefen(fake)
    assert fake.gezeigt == ["Coding", "Mail"]


def test_ziel_app_faellt_waehrend_der_aufnahme_auf_die_gemerkte_app(qapp):
    """Waehrend einer Aufnahme gilt die beim Start festgehaltene App — dort landet
    der Text. Der frische Vordergrund waere waehrend des Sprechens die falsche
    Antwort (man kann zwischendurch klicken)."""
    import types

    from fleech.ui.desktop import DesktopApp

    fake = types.SimpleNamespace(
        recorder=types.SimpleNamespace(recording=True),
        _record_app="Code.exe", _record_title="pipeline.py — Fleech",
    )
    assert DesktopApp.ziel_app_und_titel(fake) == ("Code.exe", "pipeline.py — Fleech")


def test_profile_global_aus_nimmt_keinen_profilwechsel_an(qapp):
    """Befund G-B11: Punkt und Auswahlliste wechselten weiter munter das Profil und
    die Kapsel nannte einen Namen — gewirkt hat nichts, weil `_app_profile_overrides`
    bei `enabled=False` sofort leere Overrides liefert."""
    from fleech.ui.desktop import DesktopApp

    fake = _fake_app(_ANZEIGE_PROFILE, app="Code.exe")
    fake.settings.profiles.enabled = False
    fake.profile_names = lambda: DesktopApp.profile_names(fake)
    fake._set_profile = lambda n: DesktopApp._set_profile(fake, n)

    DesktopApp._set_profile(fake, "Mail")
    assert fake.settings.profiles.active == ""       # nichts geschrieben
    assert fake.gezeigt == ["Profile sind ausgeschaltet"]

    DesktopApp.cycle_profile(fake)
    assert fake.settings.profiles.active == ""
    assert fake.gezeigt == ["Profile sind ausgeschaltet"] * 2

    fake.settings.profiles.enabled = True            # wieder an: es geht wieder
    DesktopApp._set_profile(fake, "Mail")
    assert fake.settings.profiles.active == "Mail"


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
    # (Ohne das Standardprofil — es ist seit Befund G-B1 keine Station mehr.)
    fake.current_app = lambda: "Code.exe"
    assert DesktopApp.profile_names(fake) == [
        "E-Mail", "KI-Prompt", "Stichpunkte", "Formeln"]

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
    # Ohne das Standardprofil (G-B1) — der Rueckfall ist die globale Auswahl.
    assert DesktopApp.profile_names(fake) == ["E-Mail"]

def test_current_app_haelt_die_app_der_laufenden_aufnahme_fest(qapp, monkeypatch):
    """Waehrend der Aufnahme zaehlt die App, in die eingefuegt wird — nicht die,
    auf der der Fokus zufaellig gerade steht. Sonst stuende in der Auswahlliste
    etwas anderes als das, wofuer das Diktat gilt."""
    import types

    from fleech.ui.desktop import DesktopApp

    monkeypatch.setattr("fleech.ui.windowsfocus.foreground_now",
                        lambda: ("explorer.exe", "Irgendein Fenster"))
    fake = types.SimpleNamespace(
        recorder=types.SimpleNamespace(recording=True),
        _record_app="claude.exe",
        notifier=types.SimpleNamespace(
            context=types.SimpleNamespace(foreground_process="chrome.exe")),
    )
    assert DesktopApp.current_app(fake) == "claude.exe"

    # Ohne Aufnahme zaehlt der FRISCHE Vordergrund, nicht der 3-s-Poll: Wer in
    # eine App tabbt und sofort den Hotkey haelt, will deren Profile sehen.
    fake.recorder.recording = False
    assert DesktopApp.current_app(fake) == "explorer.exe"

    # Faellt die Sofortabfrage aus, traegt der Poll weiter.
    monkeypatch.setattr("fleech.ui.windowsfocus.foreground_now", lambda: ("", ""))
    assert DesktopApp.current_app(fake) == "chrome.exe"

    # Auch ohne Fokus-Kontext (Linux/fruehe Startphase): leer, nie ein Absturz.
    fake.notifier = types.SimpleNamespace()
    assert DesktopApp.current_app(fake) == ""

def test_aufnahmestart_haelt_den_frischen_vordergrund_fest(qapp, monkeypatch):
    """Der Kern der Meldung: Tabben und sofort diktieren.

    Der 3-s-Poll haette bis zu drei Sekunden lang die VORIGE App geliefert — der
    Text landet dann im richtigen Fenster, aber im falschen Format.
    """
    import types

    from fleech.ui.desktop import DesktopApp

    monkeypatch.setattr("fleech.ui.windowsfocus.foreground_now",
                        lambda: ("claude.exe", "Claude — neuer Chat"))
    fake = types.SimpleNamespace(
        _license_state=types.SimpleNamespace(ok=True),
        controller=types.SimpleNamespace(stop_if_active=lambda: None),
        focus=types.SimpleNamespace(
            may_record=lambda math_mode=False: (True, ""),
            on_recording_start=lambda: None),
        notifier=types.SimpleNamespace(context=types.SimpleNamespace(
            foreground_process="chrome.exe", foreground_title="Alt")),
        settings=types.SimpleNamespace(
            output=types.SimpleNamespace(restore_focus=False)),
        pipeline=types.SimpleNamespace(
            injector=types.SimpleNamespace(set_focus_target=lambda t: None)),
        recorder=types.SimpleNamespace(start=lambda: None),
        bus=types.SimpleNamespace(set_state=lambda *a: None),
        sounds=types.SimpleNamespace(play=lambda n: None),
    )
    fake._license_ok = lambda: True
    try:
        DesktopApp._on_record_start(fake, "dictate")
    except Exception:
        pass                       # spaetere Schritte brauchen echte Bausteine
    assert fake._record_app == "claude.exe"      # nicht chrome.exe aus dem Poll
    assert fake._record_title == "Claude — neuer Chat"

def test_apps_seite_pflegt_den_schnellwechsel(qapp, tmp_path, monkeypatch):
    """Haken setzen/entfernen auf der Apps-Seite landet in den Einstellungen."""
    from PySide6.QtCore import Qt

    window, _p, _store, settings, _c = make_main_window(tmp_path, monkeypatch,
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

    window, _p, _store, _settings, _c = make_main_window(tmp_path, monkeypatch,
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
    window, _p, _store, settings, _c = make_main_window(tmp_path, monkeypatch,
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
    window, _p, _store, settings, _c = make_main_window(tmp_path, monkeypatch,
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
