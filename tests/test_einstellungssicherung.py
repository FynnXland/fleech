"""Datierte Sicherungen der Einstellungen.

Hintergrund in `fleech/einstellungssicherung.py`: Ein Testlauf hat am 2026-08-20
die echte `settings.json` mit Vorgabewerten ueberschrieben, und die eine
`settings.json.bak` half nicht — sie war beim zweiten Schreiben mitueberschrieben.
"""

import json
from datetime import datetime

import pytest

from fleech import einstellungssicherung as sicherung


def _schreibe(pfad, inhalt="a"):
    pfad.write_text(json.dumps({"general": {"display_name": inhalt}}), encoding="utf-8")
    return pfad


def test_sichert_und_benennt_nach_zeit_und_grund(tmp_path):
    datei = _schreibe(tmp_path / "settings.json")
    ziel = sicherung.sichere(datei, "update", jetzt=datetime(2026, 8, 20, 10, 15, 30))
    assert ziel is not None
    assert ziel.name == "settings-20260820-101530-update.json"
    assert ziel.parent.name == sicherung.ORDNERNAME
    assert json.loads(ziel.read_text(encoding="utf-8")) == json.loads(
        datei.read_text(encoding="utf-8"))


def test_unveraenderter_inhalt_erzeugt_keine_zweite_kopie(tmp_path):
    """Sonst verdraengen zwoelf gleiche Kopien jeden Stand, der noch etwas wusste."""
    datei = _schreibe(tmp_path / "settings.json")
    erste = sicherung.sichere(datei, "build", jetzt=datetime(2026, 8, 20, 10, 0, 0))
    zweite = sicherung.sichere(datei, "build", jetzt=datetime(2026, 8, 20, 11, 0, 0))
    assert erste is not None and zweite is None
    assert len(sicherung.vorhandene(sicherung.ordner_fuer(datei))) == 1

    _schreibe(datei, "b")
    dritte = sicherung.sichere(datei, "build", jetzt=datetime(2026, 8, 20, 12, 0, 0))
    assert dritte is not None
    assert len(sicherung.vorhandene(sicherung.ordner_fuer(datei))) == 2


def test_haelt_die_anzahl_und_wirft_die_aeltesten_weg(tmp_path):
    datei = tmp_path / "settings.json"
    for i in range(8):
        _schreibe(datei, f"stand-{i}")
        sicherung.sichere(datei, "build", jetzt=datetime(2026, 8, 20, 10, i, 0),
                          behalten=3)
    namen = [p.name for p in sicherung.vorhandene(sicherung.ordner_fuer(datei))]
    assert len(namen) == 3
    assert namen == sorted(namen)                    # aelteste zuerst
    # Behalten wurden die DREI juengsten (Minute 5, 6, 7), nicht die ersten.
    assert namen[-1] == "settings-20260820-100700-build.json"
    assert namen[0] == "settings-20260820-100500-build.json"


def test_fremde_dateien_bleiben_unangetastet(tmp_path):
    """`raeume_auf` darf nur loeschen, was es selbst angelegt hat."""
    datei = _schreibe(tmp_path / "settings.json")
    sicherung.sichere(datei, "build", jetzt=datetime(2026, 8, 20, 10, 0, 0))
    fremd = sicherung.ordner_fuer(datei) / "von-hand-abgelegt.json"
    fremd.write_text("{}", encoding="utf-8")
    for i in range(1, 6):
        _schreibe(datei, f"x{i}")
        sicherung.sichere(datei, "build", jetzt=datetime(2026, 8, 20, 10, i, 0),
                          behalten=2)
    assert fremd.is_file()


def test_ohne_einstellungsdatei_passiert_nichts(tmp_path):
    assert sicherung.sichere(tmp_path / "gibtsnicht.json", "update") is None
    assert not sicherung.ordner_fuer(tmp_path / "gibtsnicht.json").exists()


def test_schreibfehler_haelt_den_aufrufer_nicht_auf(tmp_path, monkeypatch):
    """Eine App, die nicht startet, weil eine Sicherung misslang, waere schlimmer
    als das Problem, gegen das die Sicherung schuetzt."""
    datei = _schreibe(tmp_path / "settings.json")
    monkeypatch.setattr(sicherung.Path, "write_bytes",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError("voll")))
    assert sicherung.sichere(datei, "build") is None


def test_wiederherstellen_sichert_den_aktuellen_stand_vorher(tmp_path):
    """Wer die falsche Sicherung erwischt, braucht einen Weg zurueck."""
    datei = _schreibe(tmp_path / "settings.json", "alt")
    quelle = sicherung.sichere(datei, "update", jetzt=datetime(2026, 8, 20, 9, 0, 0))
    _schreibe(datei, "neu")

    sicherung.stelle_wieder_her(datei, quelle)

    assert json.loads(datei.read_text(encoding="utf-8"))["general"]["display_name"] == "alt"
    gruende = [p.name for p in sicherung.vorhandene(sicherung.ordner_fuer(datei))]
    assert any("vorruecksicherung" in n for n in gruende)


# -- Der Auslöser beim Versionswechsel -------------------------------------------------


def test_versionswechsel_sichert_vor_dem_ersten_speichern(tmp_path, monkeypatch):
    """Der ganze Zweck: Die Datei wird gesichert, WIE SIE IST — vor Migration und
    vor dem ersten `save()` der neuen Version."""
    from fleech.usersettings import UserSettings

    pfad = tmp_path / "settings.json"
    alt = UserSettings()
    alt.recording.hotkey = "f23"
    alt.output.dictionary = ["Fleech"]
    alt.general.last_version = "5.11.0"
    alt.save(pfad)

    monkeypatch.setattr("fleech.version.APP_VERSION", "5.99.0")
    geladen = UserSettings.load(pfad)

    kopien = sicherung.vorhandene(sicherung.ordner_fuer(pfad))
    assert len(kopien) == 1 and kopien[0].name.endswith("-update.json")
    inhalt = json.loads(kopien[0].read_text(encoding="utf-8"))
    assert inhalt["recording"]["hotkey"] == "f23"
    assert inhalt["output"]["dictionary"] == ["Fleech"]
    # Die geladene Fassung merkt sich ab jetzt die neue Version.
    assert geladen.general.last_version == "5.99.0"


def test_gleiche_version_sichert_nicht(tmp_path, monkeypatch):
    from fleech.usersettings import UserSettings

    pfad = tmp_path / "settings.json"
    s = UserSettings()
    s.general.last_version = "5.99.0"
    s.save(pfad)

    monkeypatch.setattr("fleech.version.APP_VERSION", "5.99.0")
    UserSettings.load(pfad)
    assert sicherung.vorhandene(sicherung.ordner_fuer(pfad)) == []


def test_bestandsdatei_ohne_versionsfeld_wird_gesichert(tmp_path, monkeypatch):
    """Dateien aus der Zeit vor 5.11.4 haben kein `last_version` — die sind der
    Grund, warum es die Sicherung ueberhaupt gibt, und muessen mitkommen."""
    from fleech.usersettings import UserSettings

    pfad = tmp_path / "settings.json"
    pfad.write_text(json.dumps({"recording": {"hotkey": "f23"}}), encoding="utf-8")

    monkeypatch.setattr("fleech.version.APP_VERSION", "5.99.0")
    UserSettings.load(pfad)
    assert len(sicherung.vorhandene(sicherung.ordner_fuer(pfad))) == 1


@pytest.mark.parametrize("grund, erwartet", [
    ("update", "update"), ("BUILD", "build"), ("mit-strich_9", "mitstrich"), ("", "unbekannt"),
])
def test_grund_wird_auf_saubere_dateinamen_reduziert(tmp_path, grund, erwartet):
    datei = _schreibe(tmp_path / "settings.json")
    ziel = sicherung.sichere(datei, grund, jetzt=datetime(2026, 8, 20, 10, 0, 0))
    assert ziel.name.endswith(f"-{erwartet}.json")


# -- Ein schrumpfender Schreibvorgang wird gemeldet ------------------------------------


def _umfang(**kw):
    basis = {"profile": 8, "zuordnungen": 4, "schnellwechsel": 2, "woerter": 4}
    basis.update(kw)
    return basis


def test_erster_schreibvorgang_meldet_nichts(tmp_path, caplog):
    """Ohne Vorher-Wert gibt es nichts zu vergleichen — und nichts zu melden."""
    sicherung._LETZTER_UMFANG.clear()
    with caplog.at_level("INFO"):
        sicherung.melde_schreibvorgang(tmp_path / "settings.json", _umfang())
    assert "geschrieben" not in caplog.text


def test_unveraenderter_umfang_bleibt_still(tmp_path, caplog):
    """`save()` laeuft bei jeder Fensterbewegung. Ein Protokoll, das dabei jedes
    Mal schreibt, liest niemand."""
    pfad = tmp_path / "settings.json"
    sicherung._LETZTER_UMFANG.clear()
    sicherung.melde_schreibvorgang(pfad, _umfang())
    with caplog.at_level("INFO"):
        sicherung.melde_schreibvorgang(pfad, _umfang())
    assert caplog.text == ""


def test_verlust_wird_als_warnung_gemeldet(tmp_path, caplog):
    """Der Fall, der zweimal unbemerkt blieb."""
    pfad = tmp_path / "settings.json"
    sicherung._LETZTER_UMFANG.clear()
    sicherung.melde_schreibvorgang(pfad, _umfang())
    with caplog.at_level("INFO"):
        sicherung.melde_schreibvorgang(pfad, _umfang(zuordnungen=0, woerter=1))
    assert "WENIGER" in caplog.text
    assert "zuordnungen 4->0" in caplog.text
    assert "woerter 4->1" in caplog.text
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_zuwachs_wird_nur_vermerkt(tmp_path, caplog):
    pfad = tmp_path / "settings.json"
    sicherung._LETZTER_UMFANG.clear()
    sicherung.melde_schreibvorgang(pfad, _umfang())
    with caplog.at_level("INFO"):
        sicherung.melde_schreibvorgang(pfad, _umfang(woerter=9))
    assert "WENIGER" not in caplog.text
    assert "9 Woerterbuchzeilen" in caplog.text


def test_meldung_reisst_den_schreibvorgang_nie_mit(tmp_path):
    """Die Einstellungen stehen zu diesem Zeitpunkt bereits auf der Platte."""
    sicherung._LETZTER_UMFANG.clear()
    sicherung.melde_schreibvorgang(tmp_path / "settings.json", None)  # kaputte Eingabe
