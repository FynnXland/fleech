"""Sprache der Oberfläche (6.6.0): Katalog vollständig, Umschaltung wirkt."""

import json

import pytest

import fleech.i18n as i18n
from fleech.i18n import pruefung


def test_jeder_text_hat_eine_englische_fassung():
    """Jeder Text in tr()/N_() steht im englischen Katalog, mit denselben
    Platzhaltern; kein tr() auf Modulebene, kein tr(f"…")."""
    meldungen = pruefung.fehler()
    assert not meldungen, "\n".join(meldungen[:40])


def test_katalogdateien_sind_sauber():
    """Gültiges JSON, nur Text → Text, und dieselbe Quelle nicht in zwei
    Bereichsdateien verschieden übersetzt."""
    gesehen: dict[str, tuple[str, str]] = {}
    for datei in sorted(i18n.katalog_dir("en").glob("*.json")):
        daten = json.loads(datei.read_text(encoding="utf-8"))
        assert isinstance(daten, dict), datei.name
        for k, v in daten.items():
            assert isinstance(k, str) and isinstance(v, str) and v.strip(), (datei.name, k)
            if k in gesehen and gesehen[k][1] != v:
                pytest.fail(f"{k!r}: {gesehen[k][0]} sagt {gesehen[k][1]!r}, "
                            f"{datei.name} sagt {v!r}")
            gesehen[k] = (datei.name, v)


def test_kein_eintrag_ohne_verwendung():
    """Verwaiste Einträge (Text im Code geändert, Katalog nicht) fallen auf."""
    benutzt = set(pruefung.texte())
    verwaist = sorted(set(i18n.lade_katalog("en")) - benutzt)
    assert not verwaist, "\n".join(verwaist[:40])


def test_umschalten_und_platzhalter(monkeypatch):
    monkeypatch.setattr(i18n, "lade_katalog", lambda s: {"Noch {n} Minuten": "{n} minutes left"})
    assert i18n.tr("Noch {n} Minuten", n=3) == "Noch 3 Minuten"
    assert i18n.dezimal(1.25, 1) == "1,2"
    assert i18n.setze("en") == "en"
    assert i18n.tr("Noch {n} Minuten", n=3) == "3 minutes left"
    assert i18n.tr("Unbekannt") == "Unbekannt"   # fehlt → deutsch statt leer
    assert i18n.dezimal(1.5, 1) == "1.5"


def test_auto_folgt_dem_system(monkeypatch):
    monkeypatch.setattr(i18n, "systemsprache", lambda: "en")
    assert i18n.aufloesen("auto") == "en"
    assert i18n.aufloesen("de") == "de"
    assert i18n.aufloesen("quatsch") == "en"


def test_systemsprache_liefert_unterstuetzte():
    assert i18n.systemsprache() in i18n.SPRACHEN


def test_vorgabe_ist_systemsprache():
    from fleech.usersettings import UserSettings

    assert UserSettings().general.ui_language == "auto"
