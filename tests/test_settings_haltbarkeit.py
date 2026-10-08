"""Einstellungen duerfen nicht verloren gehen — auch nicht bei hartem Abbruch.

Realer Schaden, aus dem diese Tests entstanden sind: Beim Update wurde Fleech mit
einem harten Kill beendet. Traf das einen laufenden `save()`, blieb eine leere
settings.json zurueck; der naechste Start fiel still auf Vorgaben und der erste
`save()` zementierte sie. Weg waren Hotkeys, Profile und Woerterbuch.
"""

import json
import logging
import os
import threading
import time
from dataclasses import asdict

import pytest

from fleech.usersettings import UserSettings, _backup_path
from tresorhelfer import lies_text


@pytest.fixture
def pfad(tmp_path):
    return tmp_path / "settings.json"


def _mit_inhalt(pfad) -> UserSettings:
    s = UserSettings()
    s.general.display_name = "Name-echt"
    s.recording.hotkey = "f23"
    s.recording.prompt_toggle_hotkey = ""        # bewusst geloescht
    s.output.dictionary = ["Fleech"]
    s.profiles.active = "Stichpunkte"
    s.save(pfad)
    return s


def _schreibe(ziel, settings: UserSettings) -> None:
    """Datei direkt schreiben, ohne `save()` — die Tests zur Heilung brauchen eine
    bestimmte Kombination aus settings.json und .bak, und `save()` wuerde die
    Sicherung dabei selbst ueberschreiben."""
    ziel.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False),
                    encoding="utf-8")


def _temp_reste(pfad) -> list:
    """Nebendateien des Schreibpfads (heissen seit D-2 settings.json.<pid>.<tid>.tmp)."""
    return list(pfad.parent.glob(pfad.name + "*.tmp"))


def test_speichern_ist_atomar_und_hinterlaesst_keine_reste(pfad):
    _mit_inhalt(pfad)
    assert json.loads(lies_text(pfad))["general"]["display_name"]
    assert not _temp_reste(pfad)                            # kein Temp-Muell


def test_zweites_speichern_legt_eine_sicherung_an(pfad):
    s = _mit_inhalt(pfad)
    s.general.display_name = "Name-neuer"
    s.save(pfad)
    gesichert = json.loads(lies_text(_backup_path(pfad)))
    assert gesichert["general"]["display_name"] == "Name-echt"   # die VORIGE
    assert json.loads(lies_text(pfad))["general"]["display_name"] \
        == "Name-neuer"


@pytest.mark.parametrize("kaputt", [
    "",                                   # hartes Kill mitten im Schreiben
    "   \n",
    '{"general": {"display_name": "Ec',    # halb geschrieben
    "[]",                                 # gueltiges JSON, aber kein Objekt
    "\x00\x00\x00",                       # Nullen (Stromausfall ohne fsync)
])
def test_kaputte_datei_wird_aus_der_sicherung_geheilt(pfad, kaputt):
    """Der Kern: Nach dem Unfall stehen Name und Hotkeys wieder da."""
    s = _mit_inhalt(pfad)
    s.profiles.active = "E-Mail"
    s.save(pfad)                                   # legt die Sicherung an
    pfad.write_text(kaputt, encoding="utf-8")

    geladen = UserSettings.load(pfad)
    assert geladen.general.display_name == "Name-echt"
    assert geladen.recording.hotkey == "f23"
    assert geladen.recording.prompt_toggle_hotkey == ""   # Loeschung ueberlebt


def test_ohne_sicherung_wird_die_kaputte_datei_aufgehoben_nicht_ueberschrieben(pfad):
    """Ohne Sicherung bleibt nur der Neustart mit Vorgaben — aber die kaputte
    Fassung wird beiseitegelegt statt ueberschrieben. Sonst waere die einzige
    Spur des Verlorenen beim ersten `save()` endgueltig fort."""
    pfad.write_text('{"general": {"display_name', encoding="utf-8")
    geladen = UserSettings.load(pfad)
    assert geladen.general.display_name == ""            # Vorgaben
    assert pfad.with_name(pfad.name + ".kaputt").is_file()
    assert "display_name" in lies_text(pfad.with_name(pfad.name + ".kaputt"))


def test_gesunde_datei_wird_nie_beiseitegelegt(pfad):
    _mit_inhalt(pfad)
    UserSettings.load(pfad)
    assert not pfad.with_name(pfad.name + ".kaputt").exists()


def test_fehlende_datei_ist_kein_fehlerfall(pfad):
    """Erststart: keine Datei, keine Sicherung, kein Laerm."""
    geladen = UserSettings.load(pfad)
    assert geladen.general.display_name == ""
    assert not pfad.with_name(pfad.name + ".kaputt").exists()


def test_schreibfehler_laesst_die_alte_fassung_stehen(pfad, monkeypatch):
    """Ist das Ziel nicht beschreibbar, bleibt die bisherige Datei unangetastet —
    ein gescheiterter Speicherversuch darf nie schlimmer sein als keiner."""
    _mit_inhalt(pfad)
    vorher = lies_text(pfad)

    def kaputt(*_a, **_k):
        raise OSError("Datentraeger voll")

    monkeypatch.setattr("os.replace", kaputt)
    s = UserSettings.load(pfad)
    s.general.display_name = "Name-ginge-verloren"
    s.save(pfad)                                   # darf nicht werfen
    assert lies_text(pfad) == vorher


def test_unserialisierbares_feld_zerstoert_die_datei_nicht(pfad, monkeypatch):
    """Frueher truncierte write_text zuerst und serialisierte dann — ein Fehler
    dabei hinterliess eine leere Datei. Jetzt wird erst serialisiert."""
    _mit_inhalt(pfad)
    vorher = lies_text(pfad)
    s = UserSettings.load(pfad)
    s.profiles.items = [{"kaputt": object()}]      # nicht JSON-faehig
    s.save(pfad)
    assert lies_text(pfad) == vorher


# --- D-2: zwei Threads im Schreibpfad -----------------------------------------

def test_gleichzeitiges_speichern_zerstoert_die_datei_nicht(pfad):
    """Befund D-2: `save()` laeuft auch aus dem Pipeline-Worker (Woerterbuch-
    Zaehlung am Diktatende), waehrend die Oberflaeche speichert. Ohne Schloss und
    mit festem Temp-Namen schrieben beide in dieselbe Nebendatei — nachgestellt
    hinterliess das in 6 % der Kollisionen eine unlesbare settings.json."""
    kaputt = []

    def schreiber(schluessel: str):
        s = UserSettings()
        s.general.display_name = schluessel
        for _ in range(200):
            s.save(pfad)

    def leser(stop: threading.Event):
        while not stop.is_set():
            try:
                roh = lies_text(pfad)
            except OSError:
                continue                     # Datei gerade ersetzt — kein Fehler
            except Exception as fehler:      # Umschlag unlesbar = halb geschrieben
                kaputt.append(f"{fehler}")
                continue
            if not roh.strip():
                continue
            try:
                json.loads(roh)
            except ValueError as fehler:
                kaputt.append(f"{fehler} — {len(roh)} Zeichen")

    stop = threading.Event()
    beobachter = threading.Thread(target=leser, args=(stop,), daemon=True)
    beobachter.start()
    threads = [threading.Thread(target=schreiber, args=(f"Name-{i}",))
               for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()
    beobachter.join(timeout=5)

    assert kaputt == []
    assert json.loads(lies_text(pfad))["general"]["display_name"] \
        in {"Name-0", "Name-1"}
    assert not _temp_reste(pfad)


def test_zwei_schreiber_kommen_sich_nie_ins_gehege(pfad, monkeypatch):
    """Der Kern von D-2, deterministisch statt auf Glueck: Waehrend ein Thread
    schreibt, darf kein zweiter im Schreibblock stehen — und die Nebendatei, in
    die er schreibt, gehoert ihm allein. Frueher hiess sie fuer alle gleich
    `settings.json.tmp`; zwei Threads schrieben ineinander und `os.replace` schob
    das Gemisch an die Stelle der Einstellungen.
    """
    hoechststand = []
    im_block = 0
    zaehler = threading.Lock()
    echtes_fsync = os.fsync
    nebendateien = set()
    echtes_replace = os.replace

    def langsames_fsync(fd):
        nonlocal im_block
        with zaehler:
            im_block += 1
            hoechststand.append(im_block)
        time.sleep(0.002)                    # Fenster fuer den zweiten Thread
        with zaehler:
            im_block -= 1
        return echtes_fsync(fd)

    def merkendes_replace(quelle, ziel):
        nebendateien.add(str(quelle))
        return echtes_replace(quelle, ziel)

    monkeypatch.setattr(os, "fsync", langsames_fsync)
    monkeypatch.setattr(os, "replace", merkendes_replace)

    def schreiber(schluessel: str):
        s = UserSettings()
        s.general.display_name = schluessel
        for _ in range(10):
            s.save(pfad)

    threads = [threading.Thread(target=schreiber, args=(f"Name-{i}",))
               for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max(hoechststand) == 1, "zwei Threads gleichzeitig im Schreibblock"
    assert len(nebendateien) == 2, "beide Threads benutzten dieselbe Nebendatei"
    assert not any(n.endswith("settings.json.tmp") for n in nebendateien)


def test_kaputte_quelle_wird_nicht_zur_sicherung(pfad):
    """Befund D-2: Frueher kopierte `save()` die vorhandene Datei ungeprueft in die
    .bak. War die settings.json einmal kaputt, machte der naechste Speichervorgang
    die kaputte Fassung zur „letzten guten" — und die Rettung war mit weg."""
    s = _mit_inhalt(pfad)
    s.profiles.active = "E-Mail"
    s.save(pfad)                                   # gute Sicherung
    vorher = lies_text(_backup_path(pfad))

    pfad.write_text('{"general": {"display_name": "Ec', encoding="utf-8")
    UserSettings().save(pfad)                      # naechster Speichervorgang

    assert lies_text(_backup_path(pfad)) == vorher
    assert json.loads(vorher)["general"]["display_name"] == "Name-echt"
    # Damit ist die Rettung noch da — und A-5 holt sie beim naechsten Start:
    assert UserSettings.load(pfad).general.display_name == "Name-echt"


# --- A-5: gueltige, aber zurueckgesetzte Datei --------------------------------

def _sicherung_mit_allem() -> UserSettings:
    s = UserSettings()
    s.general.display_name = "Name-echt"
    s.general.onboarding_done = True
    s.recording.hotkey = "f23"
    s.output.dictionary = ["Fleech", "Kimono"]
    s.profiles.app_quick = {"claude.exe": ["KI-Prompt", "Stichpunkte"]}
    return s


def test_heilung_b_alles_auf_werk_waehrend_die_sicherung_mehr_hat(pfad):
    """Befund A-5: Die Datei steht auf ALLEN wertvollen Feldern auf Auslieferungszustand und die
    Sicherung weicht in mindestens zwei davon ab."""
    sicherung = _sicherung_mit_allem()
    _schreibe(pfad, UserSettings())
    _schreibe(_backup_path(pfad), sicherung)

    geladen = UserSettings.load(pfad)
    assert geladen.recording.hotkey == "f23"
    assert geladen.profiles.app_quick == {"claude.exe": ["KI-Prompt", "Stichpunkte"]}
    assert pfad.with_name(pfad.name + ".zurueckgesetzt").is_file()
    # Die zurueckgesetzte Fassung wird beiseitegelegt, nicht ueberschrieben.
    assert json.loads(lies_text(pfad.with_name(pfad.name + ".zurueckgesetzt")))["recording"]["hotkey"] == "f9"


def test_keine_heilung_bei_einer_einzelnen_abweichung(pfad):
    """Wer sein Woerterbuch leert, will es geleert haben. Eine einzelne Aenderung
    ist Bedienung, kein Verlust — sonst kaeme die App jedem Aufraeumen in die
    Quere."""
    sicherung = _sicherung_mit_allem()
    datei = _sicherung_mit_allem()
    datei.output.dictionary = []            # bewusst geleert
    _schreibe(pfad, datei)
    _schreibe(_backup_path(pfad), sicherung)

    geladen = UserSettings.load(pfad)
    assert geladen.output.dictionary == []
    assert not pfad.with_name(pfad.name + ".zurueckgesetzt").exists()


def test_keine_heilung_wenn_nur_ein_wertvolles_feld_in_der_sicherung_steht(pfad):
    """Die Erkennung verlangt ZWEI Abweichungen. Bei einer einzigen koennte es
    genauso gut ein bewusster Griff gewesen sein."""
    sicherung = UserSettings()
    sicherung.recording.hotkey = "f23"      # genau eine Abweichung
    _schreibe(pfad, UserSettings())
    _schreibe(_backup_path(pfad), sicherung)

    assert UserSettings.load(pfad).recording.hotkey == "f9"
    assert not pfad.with_name(pfad.name + ".zurueckgesetzt").exists()


@pytest.mark.parametrize("kaputte_sicherung", ["", "   \n", '{"general": {"dis'])
def test_keine_heilung_aus_einer_kaputten_sicherung(pfad, kaputte_sicherung):
    """Eine unlesbare .bak ist kein Rettungsanker — dann bleibt es bei dem, was
    in der Datei steht."""
    _schreibe(pfad, UserSettings())
    _backup_path(pfad).write_text(kaputte_sicherung, encoding="utf-8")

    assert UserSettings.load(pfad).general.display_name == ""
    assert not pfad.with_name(pfad.name + ".zurueckgesetzt").exists()
    assert pfad.is_file()


def test_keine_heilung_wenn_datei_und_sicherung_gleich_sind(pfad):
    """Der Normalfall nach jedem zweiten Speichervorgang: beide Fassungen sind
    gleich. Hier darf nie etwas beiseitegelegt werden."""
    s = _mit_inhalt(pfad)
    s.save(pfad)                            # jetzt sind Datei und .bak identisch
    geladen = UserSettings.load(pfad)
    assert geladen.general.display_name == "Name-echt"
    assert not pfad.with_name(pfad.name + ".zurueckgesetzt").exists()


def test_werksfrischer_start_mit_werksfrischer_sicherung_bleibt_unberuehrt(pfad):
    """Erststart nach einem Speichervorgang: beides Vorgaben, nichts zu heilen."""
    UserSettings().save(pfad)
    UserSettings().save(pfad)
    UserSettings.load(pfad)
    assert not pfad.with_name(pfad.name + ".zurueckgesetzt").exists()


# --- B10: sichtbar machen, was geladen wurde ----------------------------------

def test_die_geheilte_fassung_ueberlebt_auch_den_naechsten_start(pfad):
    """Die Heilung legt die zurueckgesetzte Datei beiseite — danach gibt es kurz
    gar keine settings.json, nur die Sicherung. Kommt die App vor dem naechsten
    Speichern nicht mehr dazu (Absturz, Kill), darf die Rettung nicht still
    verfallen: Auch eine FEHLENDE Datei zieht die Sicherung."""
    _schreibe(pfad, UserSettings())
    _schreibe(_backup_path(pfad), _sicherung_mit_allem())

    assert UserSettings.load(pfad).general.display_name == "Name-echt"
    assert not pfad.exists()                       # beiseitegelegt
    zweiter_start = UserSettings.load(pfad)        # ohne dass etwas gespeichert wurde
    assert zweiter_start.general.display_name == "Name-echt"


def test_ladezeile_nennt_profile_und_zuordnungen(pfad, caplog):
    """Befund B10: Die einzige je angelegte Schnellwechsel-Zuordnung war zweimal
    weg, ohne dass es irgendwo auffiel. Diese Zeile macht den Verlust im Log
    sichtbar."""
    s = UserSettings()
    s.general.display_name = "Name-echt"
    s.output.dictionary = ["Fleech", "Kimono", "Wispr"]
    s.profiles.items[1]["apps"] = ["winword.exe", "outlook.exe"]
    s.profiles.app_quick = {"claude.exe": ["KI-Prompt", "Stichpunkte"]}
    _schreibe(pfad, s)

    with caplog.at_level(logging.INFO):
        UserSettings.load(pfad)
    zeile = [r.getMessage() for r in caplog.records if "Einstellungen geladen" in r.getMessage()]
    assert len(zeile) == 1
    assert "8 Profile" in zeile[0]
    assert "2 App-Zuordnungen" in zeile[0]
    assert "1 Schnellwechsel-Apps (2 Eintraege)" in zeile[0]
    assert "3 Woerterbuchzeilen" in zeile[0]
