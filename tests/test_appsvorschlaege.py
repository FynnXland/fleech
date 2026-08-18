"""Zuordnungsvorschlaege aus dem Verlauf (V-13/G-4 + H-7) — ohne Qt.

Gegen eine echte Test-History, nicht gegen einen Nachbau: Die Regel haengt an
`dictations.app`, `.mode` und der seit 5.10.4 vorhandenen Spalte `.profile` —
und genau deren Altzeilen (leeres Profil, leerer Modus) sind der Fall, an dem
eine Auswertung stillschweigend falsch werden kann.
"""

import time

import pytest

from fleech.history import DictationRecord, HistoryStore
from fleech.ui.pages.appsvorschlaege import (
    MAX_VORSCHLAEGE, MIN_DIKTATE, vorschlaege, zugewiesene_apps,
)

PROFILE = [
    {"name": "Standard", "default": True, "apps": []},
    {"name": "Coding", "apps": []},
    {"name": "Privat", "apps": []},
    {"name": "KI-Prompt", "mode": "prompt", "apps": []},
    {"name": "Stichpunkte", "mode": "summary", "apps": []},
]


def _profile():
    import copy

    return copy.deepcopy(PROFILE)


@pytest.fixture
def store(tmp_path):
    return HistoryStore(tmp_path / "h.db")


def _fuelle(store, app, anzahl, mode="cleanup", profile=""):
    jetzt = time.time()
    for i in range(anzahl):
        store.add(DictationRecord(
            ts=jetzt - i * 60, raw="roh", cleaned="Fertig.", audio_seconds=3.0,
            app=app, mode=mode, profile=profile))


def test_viel_genutzte_app_ohne_zuordnung_wird_gefragt(store):
    _fuelle(store, "claude.exe", 30, mode="prompt")
    nutzung, gesamt = store.app_nutzung()
    treffer = vorschlaege(nutzung, gesamt, _profile())
    assert len(treffer) == 1
    assert treffer[0].app == "claude.exe"
    assert treffer[0].profil == "KI-Prompt"          # aus der Modus-Verteilung
    assert "30 Diktate" in treffer[0].satz()
    assert "100 %" in treffer[0].satz()


def test_wenig_genutzte_app_wird_nicht_gefragt(store):
    _fuelle(store, "VALORANT.exe", MIN_DIKTATE - 1)
    nutzung, gesamt = store.app_nutzung()
    assert vorschlaege(nutzung, gesamt, _profile()) == []


def test_zugewiesene_app_wird_nicht_mehr_gefragt(store):
    _fuelle(store, "claude.exe", 40, mode="prompt")
    items = _profile()
    items[3]["apps"] = ["claude.exe"]
    nutzung, gesamt = store.app_nutzung()
    assert vorschlaege(nutzung, gesamt, items) == []


def test_auch_eine_reine_titelregel_beendet_die_frage(store):
    """Wer sich dort schon Gedanken gemacht hat, braucht keine Karte."""
    _fuelle(store, "comet.exe", 40)
    items = _profile()
    items[1]["apps"] = ["comet.exe :: Fleech"]
    assert zugewiesene_apps(items) == {"comet.exe"}
    nutzung, gesamt = store.app_nutzung()
    assert vorschlaege(nutzung, gesamt, items) == []


def test_ignorierte_app_verschwindet_dauerhaft(store):
    _fuelle(store, "Discord.exe", 30)
    nutzung, gesamt = store.app_nutzung()
    assert vorschlaege(nutzung, gesamt, _profile(), ignoriert=["discord.exe"]) == []


def test_hoechstens_zwei_karten_gleichzeitig(store):
    for name in ("claude.exe", "comet.exe", "Obsidian.exe", "Discord.exe"):
        _fuelle(store, name, 30)
    nutzung, gesamt = store.app_nutzung()
    assert len(vorschlaege(nutzung, gesamt, _profile())) == MAX_VORSCHLAEGE


def test_haeufig_von_hand_gewaehltes_profil_wird_vorgeschlagen(store):
    """Das Muster aus H-7: „In Obsidian nimmst du 9 von 12 Mal Privat."""
    _fuelle(store, "Obsidian.exe", 9, profile="Privat")
    _fuelle(store, "Obsidian.exe", 3, profile="Coding")
    _fuelle(store, "Obsidian.exe", 18)          # Altzeilen ohne Profil
    nutzung, gesamt = store.app_nutzung()
    treffer = vorschlaege(nutzung, gesamt, _profile())
    assert treffer[0].profil == "Privat"
    assert "9 von 12" in treffer[0].grund


def test_zu_wenig_oder_zu_uneinheitlich_schlaegt_kein_handprofil_vor(store):
    """Eine Handvoll Ausreisser darf keine Regel fuer den Alltag vorschlagen."""
    _fuelle(store, "Obsidian.exe", 4, profile="Privat")
    _fuelle(store, "Obsidian.exe", 4, profile="Coding")
    _fuelle(store, "Obsidian.exe", 22)
    nutzung, gesamt = store.app_nutzung()
    treffer = vorschlaege(nutzung, gesamt, _profile())
    assert treffer[0].profil == "Standard"      # kein Muster → das Normale
    assert treffer[0].grund == ""


def test_ohne_jedes_signal_steht_das_standardprofil_vorn(store):
    _fuelle(store, "Discord.exe", 30)
    nutzung, gesamt = store.app_nutzung()
    treffer = vorschlaege(nutzung, gesamt, _profile())
    assert treffer[0].profil == "Standard"
    assert treffer[0].alternative == ""


def test_geloeschtes_profil_wird_nicht_vorgeschlagen(store):
    """Der Verlauf haelt den Namen fest, auch wenn es das Profil nicht mehr gibt."""
    _fuelle(store, "Obsidian.exe", 30, profile="Weg")
    nutzung, gesamt = store.app_nutzung()
    assert vorschlaege(nutzung, gesamt, _profile())[0].profil == "Standard"


def test_app_nutzung_fasst_schreibweisen_zusammen(store):
    """Die Regelaufloesung ist case-insensitiv — die Zaehlung muss es auch sein,
    sonst stuende dieselbe Anwendung zweimal mit geteilten Zahlen da."""
    _fuelle(store, "Obsidian.exe", 20)
    _fuelle(store, "obsidian.exe", 20)
    nutzung, gesamt = store.app_nutzung()
    assert len(nutzung) == 1
    assert nutzung[0].diktate == 40 and gesamt == 40
