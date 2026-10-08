"""Modellberater (6.2.0): Gibt es fuer die gewaehlte KI ein neueres Modell?

Kein Test spricht ein echtes Netz an: `urlopen` und die Registry-Abfrage werden
ersetzt, der Schluesselbund ist ein Dict (conftest.schluesselbund).
"""

import datetime
import io
import json
import urllib.error

import pytest

from fleech.llm import modellberater as berater


class _Antwort(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# -- Versionen lesen ---------------------------------------------------------------------


@pytest.mark.parametrize("name,familie,version", [
    ("claude-haiku-4-5-20251001", {"claude", "haiku"}, (4, 5)),
    ("claude-3-5-haiku-20241022", {"claude", "haiku"}, (3, 5)),
    ("gpt-4o-mini-2024-07-18", {"gpt", "mini"}, (4,)),
    ("gpt-4.1-mini", {"gpt", "mini"}, (4, 1)),
    ("gemini-2.5-flash-lite", {"gemini", "flash", "lite"}, (2, 5)),
    ("llama-3.3-70b-versatile", {"llama", "70b", "versatile"}, (3, 3)),
    ("gemini-3.0-flash", {"gemini", "flash"}, (3,)),
])
def test_zerlege(name, familie, version):
    f, v, vorschau = berater.zerlege(name)
    assert (set(f), v, vorschau) == (familie, version, False)


def test_neuester_verwandter_bleibt_in_der_klasse():
    """Neuer heisst: gleiche Familie und Preisstufe. „nano" ist nicht „mini", und
    ein Vorschau-Modell verschwindet oft wieder."""
    namen = ["gpt-4o-mini", "gpt-4o-mini-2024-07-18", "gpt-5-mini",
             "gpt-5-mini-2025-08-07", "gpt-5-nano", "gpt-6-mini-preview", "o4-mini"]
    assert berater.neuester_verwandter("gpt-4o-mini", namen) == "gpt-5-mini"
    assert berater.neuester_verwandter("gpt-5-mini", namen) == ""
    assert berater.neuester_verwandter("mistral-small-latest", ["mistral-small-2603"]) == ""
    assert berater.neuester_verwandter(
        "claude-haiku-4-5", ["claude-haiku-4-5-20251001", "claude-sonnet-5",
                             "claude-haiku-5-20260801"]) == "claude-haiku-5-20260801"


def test_ollama_generationen():
    assert berater.ollama_generation_groesser("gemma4:e4b", "gemma3:4b")
    assert not berater.ollama_generation_groesser("gemma3:12b", "gemma3:4b")
    assert not berater.ollama_generation_groesser("qwen4:4b", "gemma3:4b")


# -- Katalog -------------------------------------------------------------------------------


def test_mitgelieferter_katalog_hat_eine_gemessene_empfehlung():
    daten = berater.mitgelieferter_katalog()
    modelle = berater.ollama_modelle(daten)
    empfohlen = [m for m in modelle if m.empfohlen]
    assert len(empfohlen) == 1 and empfohlen[0].gemessen
    assert berater.empfohlenes_modell("ollama", daten) == empfohlen[0].modell
    assert berater.empfohlenes_modell("anthropic", daten)


def test_katalog_netz_zwischenspeicher_rueckfall(tmp_path, monkeypatch):
    neu = {"stand": "2099-01-01", "ollama": [{"modell": "x:1b", "empfohlen": True}]}
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda url, timeout=None: _Antwort(json.dumps(neu).encode()))
    assert berater.katalog(tmp_path, netz=True)["stand"] == "2099-01-01"

    def kein_netz(url, timeout=None):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", kein_netz)
    # Ohne Netz: der zuletzt geladene Stand, nicht die alte mitgelieferte Kopie.
    assert berater.katalog(tmp_path, netz=True)["stand"] == "2099-01-01"
    assert berater.katalog(tmp_path / "leer", netz=True) == berater.mitgelieferter_katalog()


def test_kaputter_katalog_vom_netz_wird_nicht_uebernommen(tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda url, timeout=None: _Antwort(b'{"ollama": "kaputt"}'))
    assert berater.katalog(tmp_path, netz=True) == berater.mitgelieferter_katalog()
    assert not (tmp_path / "modelle-katalog.json").exists()


# -- Pruefung -------------------------------------------------------------------------------


def test_ollama_katalog_empfehlung_schlaegt_registry(monkeypatch):
    daten = {"ollama": [{"modell": "gemma3:4b"},
                        {"modell": "qwen4:4b", "empfohlen": True, "groesse_gb": 2.9,
                         "ersetzt": ["gemma3:4b"]}]}
    monkeypatch.setattr(berater, "ollama_nachfolger", lambda *a, **k: pytest.fail("Netz"))
    befund = berater.pruefe("ollama", "gemma3:4b", daten=daten)
    assert befund.neuer == "qwen4:4b" and befund.gemessen
    assert "2,9 GB" in befund.grund


def test_ollama_gemessene_generation_nennt_den_messbefund(monkeypatch):
    """Steht die neue Generation gemessen im Katalog, nennt der Hinweis das
    konkrete Tag und das Messergebnis — nicht „noch nicht gemessen"."""
    daten = berater.mitgelieferter_katalog()
    monkeypatch.setattr(berater, "registry_groesse_gb",
                        lambda name, timeout=6.0: 6.6 if name == "gemma4:latest" else None)
    befund = berater.pruefe("ollama", "gemma3:4b", daten=daten)
    assert befund.neuer == "gemma4:e4b" and befund.gemessen
    assert "gemessen" in befund.grund


def test_ollama_neue_generation_aus_der_registry(monkeypatch):
    daten = {"ollama": [{"modell": "gemma3:4b", "empfohlen": True, "groesse_gb": 3.3}]}
    monkeypatch.setattr(berater, "registry_groesse_gb",
                        lambda name, timeout=6.0: 6.6 if name == "gemma4:latest" else None)
    befund = berater.pruefe("ollama", "gemma3:4b", daten=daten)
    assert befund.neuer == "gemma4"
    assert not befund.gemessen
    assert "6,6 GB statt 3,3 GB" in befund.grund


def test_ollama_riesige_nachfolger_werden_nicht_vorgeschlagen(monkeypatch):
    """Live gefunden: llama3.2:3b (2 GB) → llama4 hat 67 GB. Das ist keine
    Alternative, sondern ein anderer Rechner."""
    groessen = {"llama3.2:3b": 2.0, "llama4:latest": 67.4}
    monkeypatch.setattr(berater, "registry_groesse_gb",
                        lambda name, timeout=6.0: groessen.get(name))
    assert berater.pruefe("ollama", "llama3.2:3b", daten={"ollama": []}) is None


def test_ollama_nichts_neues(monkeypatch):
    monkeypatch.setattr(berater, "registry_groesse_gb", lambda name, timeout=6.0: None)
    assert berater.pruefe("ollama", "gemma3:4b",
                          daten=berater.mitgelieferter_katalog()) is None


def test_cloud_neueres_und_abgeschaltetes_modell(monkeypatch):
    liste = {"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-5-mini"}, {"id": "gpt-5-nano"}]}
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=None: _Antwort(json.dumps(liste).encode()))
    befund = berater.pruefe("openai", "gpt-4o-mini", schluessel="k", daten={})
    assert befund.neuer == "gpt-5-mini"

    # Das eigene Modell gibt es nicht mehr: Vorschlag aus der Liste.
    befund = berater.pruefe("openai", "gpt-3.5-turbo", schluessel="k", daten={})
    assert befund is not None and "nicht mehr" in befund.grund


def test_cloud_ohne_schluessel_oder_netz_kein_befund(monkeypatch):
    assert berater.pruefe("openai", "gpt-4o-mini", schluessel="") is None

    def kaputt(req, timeout=None):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", kaputt)
    assert berater.pruefe("openai", "gpt-4o-mini", schluessel="k") is None
    assert berater.pruefe("aus", "") is None
    assert berater.pruefe("custom", "irgendwas") is None


# -- Auswahllisten ---------------------------------------------------------------------------


def test_lokale_auswahl_ohne_doppelte():
    daten = berater.mitgelieferter_katalog()
    liste = berater.lokale_auswahl(daten, {"gemma3:4b", "llama3.2:3b", "nomic-embed-text"},
                                   ("gemma4", 6.6))
    namen = [w.modell for w in liste]
    assert namen[0] == "gemma3:4b" and "installiert" in liste[0].label
    assert "llama3.2:3b" in namen
    assert "nomic-embed-text" not in namen          # kann keinen Text bereinigen
    assert "gemma4" not in namen                    # steht als gemma4:e4b schon drin
    leer = berater.lokale_auswahl({"ollama": []}, (), ("gemma4", 6.6))
    assert [w.modell for w in leer] == ["gemma4"]


def test_cloud_auswahl_empfehlung_oben_neueres_darunter():
    eintraege, empfohlen, neuer = berater.cloud_auswahl(
        "openai", ["gpt-5-nano", "gpt-4o-mini", "gpt-5-mini"],
        berater.mitgelieferter_katalog())
    assert (empfohlen, neuer) == ("gpt-4o-mini", "gpt-5-mini")
    assert [w.modell for w in eintraege] == ["gpt-4o-mini", "gpt-5-mini", "gpt-5-nano"]


# -- Wochentakt in der App -------------------------------------------------------------------


def test_faellig():
    from fleech.ui.desktopapp.modellpruefung import faellig

    heute = datetime.date(2026, 10, 6)
    assert faellig("", heute)
    assert faellig("Unsinn", heute)
    assert not faellig("2026-10-01", heute)
    assert faellig("2026-09-29", heute)


class _App:
    """Gerade genug DesktopApp fuer den Mixin."""

    def __init__(self):
        from fleech.ui.desktopapp.modellpruefung import ModellpruefungMixin
        from fleech.usersettings import UserSettings

        self.settings = UserSettings()
        self.settings.save = lambda path=None: None
        self.gemeldet = []
        app = self

        class Tray:
            def notify(self, titel, text):
                app.gemeldet.append(text)

        self.tray = Tray()
        self._on = ModellpruefungMixin._on_modell_hinweis.__get__(self)


def test_befund_wird_vermerkt_und_einmal_gemeldet():
    app = _App()
    befund = berater.Befund("openai", "gpt-4o-mini", "gpt-5-mini", "Neuer: gpt-5-mini.")
    app._on(befund)
    assert app.settings.ki.hinweis_modell == "gpt-5-mini"
    assert app.settings.ki.geprueft_am == datetime.date.today().isoformat()
    assert len(app.gemeldet) == 1
    app._on(befund)                                 # derselbe Vorschlag: still
    assert len(app.gemeldet) == 1
    app._on(None)                                   # erledigt: Hinweis weg
    assert app.settings.ki.hinweis_modell == ""


def test_ignorierter_vorschlag_bleibt_still():
    app = _App()
    app.settings.ki.ignoriert = ["gpt-5-mini"]
    app._on(berater.Befund("openai", "gpt-4o-mini", "gpt-5-mini", "x"))
    assert app.gemeldet == [] and app.settings.ki.hinweis_modell == ""
