"""Profile sichern und zurueckholen (V-10/G-6) — ohne Qt.

Der Anlass ist Befund G-B10: Die einzige App-Konfiguration, die je angelegt
wurde, ist zweimal aus der settings.json verschwunden. Eine Sicherung, die beim
Zurueckholen selbst etwas wegnimmt, waere die naechste Verlustquelle — deshalb
pruefen diese Tests vor allem, was NICHT passiert.
"""

import json

import pytest

from fleech.profilexport import (
    FORMAT, export_daten, importiere, lies, namenskonflikte, schreibe,
)
from fleech.usersettings import UserSettings


def _settings(items=None, quick=None) -> UserSettings:
    s = UserSettings()
    if items is not None:
        s.profiles.items = items
    if quick is not None:
        s.profiles.app_quick = quick
    return s


def test_export_traegt_nur_profile_und_schnellwechsel(tmp_path):
    """Ein Gesamt-Backup schleppt Lizenz und Mikrofonpfad mit — genau das nicht."""
    s = _settings()
    s.general.license_key = "GEHEIM-1234"
    s.recording.microphone = "Mikrofon B"
    s.profiles.app_quick = {"claude.exe": ["KI-Prompt"]}

    daten = export_daten(s)
    assert set(daten) == {"format", "version", "items", "app_quick"}
    assert daten["format"] == FORMAT
    assert daten["app_quick"] == {"claude.exe": ["KI-Prompt"]}

    pfad = tmp_path / "p.json"
    schreibe(pfad, daten)
    text = pfad.read_text(encoding="utf-8")
    assert "GEHEIM-1234" not in text and "Mikrofon B" not in text
    assert json.loads(text)["items"], "Profile fehlen in der Datei"


def test_export_liefert_kopien():
    """Sonst haengt die geschriebene Datei an den Listen der laufenden App."""
    s = _settings()
    daten = export_daten(s)
    daten["items"][0]["name"] = "Verbogen"
    assert s.profiles.items[0]["name"] != "Verbogen"


def test_import_ergaenzt_und_loescht_nie():
    s = _settings(items=[{"name": "Standard", "default": True, "apps": []},
                         {"name": "Coding", "apps": ["Code.exe"]}])
    daten = {"format": FORMAT, "version": 1,
             "items": [{"name": "Obsidian-Notizen", "apps": ["Obsidian.exe"]}],
             "app_quick": {}}

    bericht = importiere(s, daten, ersetzen=False)
    namen = [i["name"] for i in s.profiles.items]
    assert "Coding" in namen and "Obsidian-Notizen" in namen
    assert bericht.ergaenzt == ["Obsidian-Notizen"]
    assert not bericht.ersetzt and not bericht.uebersprungen


def test_gleichnamiges_profil_bleibt_ohne_zustimmung_unangetastet():
    s = _settings(items=[{"name": "Standard", "default": True, "apps": []},
                         {"name": "Coding", "apps": ["Code.exe"]}])
    daten = {"format": FORMAT, "items": [{"name": "Coding", "apps": ["javaw.exe"]}]}

    bericht = importiere(s, daten, ersetzen=False)
    assert bericht.uebersprungen == ["Coding"]
    coding = next(i for i in s.profiles.items if i["name"] == "Coding")
    assert coding["apps"] == ["Code.exe"]

    bericht = importiere(s, daten, ersetzen=True)
    assert bericht.ersetzt == ["Coding"]
    coding = next(i for i in s.profiles.items if i["name"] == "Coding")
    assert coding["apps"] == ["javaw.exe"]
    assert [i["name"] for i in s.profiles.items].count("Coding") == 1


def test_das_standardprofil_bleibt_das_standardprofil():
    """Zwei Fallbacks oder keiner faellt erst beim naechsten Diktat auf."""
    s = _settings(items=[{"name": "Standard", "default": True, "apps": []}])
    daten = {"format": FORMAT,
             "items": [{"name": "Standard", "apps": ["Word.exe"]},
                       {"name": "Fremd", "default": True, "apps": []}]}

    importiere(s, daten, ersetzen=True)
    standard = [i for i in s.profiles.items if i.get("default")]
    assert len(standard) == 1 and standard[0]["name"] == "Standard"
    assert standard[0]["apps"] == ["Word.exe"]


def test_schnellwechsel_kommt_mit_und_ueberschreibt_nur_nach_zustimmung():
    s = _settings(quick={"claude.exe": ["KI-Prompt"]})
    daten = {"format": FORMAT, "items": [],
             "app_quick": {"claude.exe": ["Stichpunkte"], "comet.exe": ["Privat"]}}

    bericht = importiere(s, daten, ersetzen=False)
    assert s.profiles.app_quick["claude.exe"] == ["KI-Prompt"]
    assert s.profiles.app_quick["comet.exe"] == ["Privat"]
    assert bericht.schnellwechsel == 1

    importiere(s, daten, ersetzen=True)
    assert s.profiles.app_quick["claude.exe"] == ["Stichpunkte"]


def test_fremde_json_datei_wird_abgewiesen(tmp_path):
    pfad = tmp_path / "fremd.json"
    pfad.write_text('{"hallo": "welt"}', encoding="utf-8")
    with pytest.raises(ValueError):
        lies(pfad)
    pfad.write_text("kein json", encoding="utf-8")
    with pytest.raises(ValueError):
        lies(pfad)


def test_namenskonflikte_meldet_genau_die_doppelten():
    s = _settings(items=[{"name": "Standard", "default": True},
                         {"name": "Coding"}])
    daten = {"format": FORMAT, "items": [{"name": "coding"}, {"name": "Neu"}]}
    assert namenskonflikte(s, daten) == ["coding"]


def test_runde_datei_ergibt_denselben_stand(tmp_path):
    """Exportieren, woanders importieren, gleicher Stand — der eigentliche Zweck."""
    quelle = _settings()
    quelle.profiles.items[1]["apps"] = ["Word.exe", "Outlook.exe :: Entwurf"]
    quelle.profiles.app_quick = {"claude.exe": ["KI-Prompt", "Stichpunkte"]}
    pfad = tmp_path / "p.json"
    schreibe(pfad, export_daten(quelle))

    ziel = _settings(items=[{"name": "Standard", "default": True, "apps": []}])
    importiere(ziel, lies(pfad), ersetzen=True)
    quell_namen = [i["name"] for i in quelle.profiles.items]
    ziel_namen = [i["name"] for i in ziel.profiles.items]
    assert quell_namen == ziel_namen
    assert ziel.profiles.app_quick == quelle.profiles.app_quick
