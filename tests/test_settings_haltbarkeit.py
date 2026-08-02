"""Einstellungen duerfen nicht verloren gehen — auch nicht bei hartem Abbruch.

Realer Schaden, aus dem diese Tests entstanden sind: Beim Update wurde Fleech mit
einem harten Kill beendet. Traf das einen laufenden `save()`, blieb eine leere
settings.json zurueck; der naechste Start fiel still auf Vorgaben und der erste
`save()` zementierte sie. Weg waren Hotkeys, Profile — und der Lizenzschluessel,
ohne den nicht einmal mehr diktiert werden kann.
"""

import json

import pytest

from fleech.usersettings import UserSettings, _backup_path


@pytest.fixture
def pfad(tmp_path):
    return tmp_path / "settings.json"


def _mit_inhalt(pfad) -> UserSettings:
    s = UserSettings()
    s.general.license_key = "FLEECH-1.echt"
    s.recording.hotkey = "f23"
    s.recording.prompt_toggle_hotkey = ""        # bewusst geloescht
    s.profiles.active = "Stichpunkte"
    s.save(pfad)
    return s


def test_speichern_ist_atomar_und_hinterlaesst_keine_reste(pfad):
    _mit_inhalt(pfad)
    assert json.loads(pfad.read_text(encoding="utf-8"))["general"]["license_key"]
    assert not pfad.with_name(pfad.name + ".tmp").exists()   # kein Temp-Muell


def test_zweites_speichern_legt_eine_sicherung_an(pfad):
    s = _mit_inhalt(pfad)
    s.general.license_key = "FLEECH-1.neuer"
    s.save(pfad)
    gesichert = json.loads(_backup_path(pfad).read_text(encoding="utf-8"))
    assert gesichert["general"]["license_key"] == "FLEECH-1.echt"   # die VORIGE
    assert json.loads(pfad.read_text(encoding="utf-8"))["general"]["license_key"] \
        == "FLEECH-1.neuer"


@pytest.mark.parametrize("kaputt", [
    "",                                   # hartes Kill mitten im Schreiben
    "   \n",
    '{"general": {"license_key": "FL',    # halb geschrieben
    "[]",                                 # gueltiges JSON, aber kein Objekt
    "\x00\x00\x00",                       # Nullen (Stromausfall ohne fsync)
])
def test_kaputte_datei_wird_aus_der_sicherung_geheilt(pfad, kaputt):
    """Der Kern: Nach dem Unfall stehen Schluessel und Hotkeys wieder da."""
    s = _mit_inhalt(pfad)
    s.profiles.active = "E-Mail"
    s.save(pfad)                                   # legt die Sicherung an
    pfad.write_text(kaputt, encoding="utf-8")

    geladen = UserSettings.load(pfad)
    assert geladen.general.license_key == "FLEECH-1.echt"
    assert geladen.recording.hotkey == "f23"
    assert geladen.recording.prompt_toggle_hotkey == ""   # Loeschung ueberlebt


def test_ohne_sicherung_wird_die_kaputte_datei_aufgehoben_nicht_ueberschrieben(pfad):
    """Ohne Sicherung bleibt nur der Neustart mit Vorgaben — aber die kaputte
    Fassung wird beiseitegelegt statt ueberschrieben. Sonst waere die einzige
    Spur des Verlorenen beim ersten `save()` endgueltig fort."""
    pfad.write_text('{"general": {"license_key', encoding="utf-8")
    geladen = UserSettings.load(pfad)
    assert geladen.general.license_key == ""            # Vorgaben
    assert pfad.with_name(pfad.name + ".kaputt").is_file()
    assert "license_key" in pfad.with_name(pfad.name + ".kaputt").read_text(
        encoding="utf-8")


def test_gesunde_datei_wird_nie_beiseitegelegt(pfad):
    _mit_inhalt(pfad)
    UserSettings.load(pfad)
    assert not pfad.with_name(pfad.name + ".kaputt").exists()


def test_fehlende_datei_ist_kein_fehlerfall(pfad):
    """Erststart: keine Datei, keine Sicherung, kein Laerm."""
    geladen = UserSettings.load(pfad)
    assert geladen.general.license_key == ""
    assert not pfad.with_name(pfad.name + ".kaputt").exists()


def test_schreibfehler_laesst_die_alte_fassung_stehen(pfad, monkeypatch):
    """Ist das Ziel nicht beschreibbar, bleibt die bisherige Datei unangetastet —
    ein gescheiterter Speicherversuch darf nie schlimmer sein als keiner."""
    _mit_inhalt(pfad)
    vorher = pfad.read_text(encoding="utf-8")

    def kaputt(*_a, **_k):
        raise OSError("Datentraeger voll")

    monkeypatch.setattr("os.replace", kaputt)
    s = UserSettings.load(pfad)
    s.general.license_key = "FLEECH-1.ginge-verloren"
    s.save(pfad)                                   # darf nicht werfen
    assert pfad.read_text(encoding="utf-8") == vorher


def test_unserialisierbares_feld_zerstoert_die_datei_nicht(pfad, monkeypatch):
    """Frueher truncierte write_text zuerst und serialisierte dann — ein Fehler
    dabei hinterliess eine leere Datei. Jetzt wird erst serialisiert."""
    _mit_inhalt(pfad)
    vorher = pfad.read_text(encoding="utf-8")
    s = UserSettings.load(pfad)
    s.profiles.items = [{"kaputt": object()}]      # nicht JSON-faehig
    s.save(pfad)
    assert pfad.read_text(encoding="utf-8") == vorher
