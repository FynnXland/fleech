"""Zeitgrenze, Ueberspringen und Cloud-Ausweiche der KI-Bereinigung (`llm/frist.py`).

Anlass: Bei belegter Grafikkarte wartete ein Diktat bis zu 60 s auf die lokale KI
(Protokoll 2026-10-18: zweimal „timed out", eines kam 86 s nach Aufnahmeende an).
"""

import json
import threading
import time
from types import SimpleNamespace

import pytest

from fleech import gruende
from fleech.config import LLMEndpointConfig
from fleech.llm import frist as frist_mod
from fleech.llm.client import ChatClient
from fleech.llm.frist import (
    FristAbgelaufen, KiFrist, Uebersprungen, ausweich_endpunkt, ausweich_modell, frist_s,
)
from fleech.llm.providers import anbieter
from pipelinehelpers import AUDIO, CLEAN_NONTRIVIAL, RAW_NONTRIVIAL, FakeLLM, make_pipeline


class LangsamesLLM:
    """Antwortet erst nach `dauer` Sekunden — wie Ollama neben einem Spiel."""

    def __init__(self, reply="Langsam.", dauer=5.0):
        self.reply, self.dauer, self.calls = reply, dauer, []

    def complete(self, system_prompt, user_text):
        self.calls.append(user_text)
        time.sleep(self.dauer)
        return self.reply


# -- Die Grenze selbst -----------------------------------------------------------------

def test_grenze_waechst_mit_der_laenge_und_beim_laden():
    kurz, lang = frist_s(20), frist_s(400)
    assert 6 <= kurz < 7                 # ueber dem p95 kurzer Diktate (1,9 s)
    assert lang > 14                     # gemessen: 400+ Woerter bis 13,9 s
    assert frist_s(20, laden=True) - kurz == pytest.approx(frist_mod.LADEN_S)
    assert frist_s(100_000) == frist_mod.HOECHSTENS_S


def test_ohne_start_gilt_keine_grenze():
    """Nachbearbeitung aus dem Verlauf: dort wartet kein Cursor."""
    f = KiFrist()
    assert f.rest() is None
    assert f.frage(FakeLLM(reply="ok"), "S", "u") == "ok"


def test_langsame_ki_reisst_die_grenze():
    f = KiFrist()
    f._ende = time.monotonic() + 0.1
    t0 = time.monotonic()
    with pytest.raises(FristAbgelaufen):
        f.frage(LangsamesLLM(dauer=5), "S", "u")
    assert time.monotonic() - t0 < 1.5


def test_abgelaufene_grenze_fragt_gar_nicht_erst():
    f = KiFrist()
    f._ende = time.monotonic() - 1
    llm = FakeLLM(reply="x")
    with pytest.raises(FristAbgelaufen):
        f.frage(llm, "S", "u")
    assert llm.calls == []


def test_haken_bricht_das_warten_sofort_ab():
    f = KiFrist()
    f.starte(50)
    threading.Timer(0.1, f.ueberspringen).start()
    t0 = time.monotonic()
    with pytest.raises(Uebersprungen):
        f.frage(LangsamesLLM(dauer=5), "S", "u")
    assert time.monotonic() - t0 < 1.0


def test_neues_diktat_nimmt_den_haken_zurueck():
    f = KiFrist()
    f.ueberspringen()
    f.neues_diktat(laden=True)
    assert not f.uebersprungen and f.laden and f.rest() is None


def test_fehler_der_ki_kommen_unveraendert_durch():
    f = KiFrist()
    f.starte(10)
    with pytest.raises(ConnectionError):
        f.frage(FakeLLM(error=ConnectionError("weg")), "S", "u")


# -- Ausweichen ------------------------------------------------------------------------

def test_zu_langsam_weicht_auf_die_cloud_aus_und_bleibt_dort():
    f = KiFrist()
    f.ausweich_llm, f.ausweich_name = FakeLLM(reply="Aus der Cloud."), "Google Gemini"
    f._ende = time.monotonic() + 0.1
    lokal = LangsamesLLM(dauer=5)
    assert f.frage(lokal, "S", "u") == "Aus der Cloud."
    assert f.ausgewichen
    # Der naechste Block desselben Diktats fragt die lokale KI nicht noch einmal.
    assert f.frage(lokal, "S", "u2") == "Aus der Cloud."
    assert lokal.calls == ["u"]


def test_ausfall_der_lokalen_ki_weicht_ebenfalls_aus():
    """Ollama-Absturz neben einem Spiel (HTTP 500, CUDA-OOM) — auch dann hilft es."""
    f = KiFrist()
    f.ausweich_llm = FakeLLM(reply="Cloud.")
    f.starte(10)
    assert f.frage(FakeLLM(error=OSError("500")), "S", "u") == "Cloud."


def test_scheitert_auch_die_cloud_zaehlt_der_lokale_grund():
    f = KiFrist()
    f.ausweich_llm = FakeLLM(error=ConnectionError("offline"))
    f._ende = time.monotonic() + 0.1
    with pytest.raises(FristAbgelaufen):
        f.frage(LangsamesLLM(dauer=5), "S", "u")


def test_ausweiche_nur_bei_lokaler_ki_und_eigener_wahl():
    ki = SimpleNamespace(anbieter="ollama", ausweichen="", ausweichen_modell="")
    assert ausweich_endpunkt(ki) is None                       # Standard: aus
    ki.ausweichen = "gemini"
    ep = ausweich_endpunkt(ki)
    assert ep.provider == "gemini" and ep.model == anbieter("gemini").modell
    assert ep.timeout == frist_mod.AUSWEICH_S and ep.num_ctx == 0
    ki.ausweichen_modell = "gemini-flash-lite-latest"
    assert ausweich_endpunkt(ki).model == "gemini-flash-lite-latest"
    ki.anbieter = "openai"                                     # Cloud als Haupt-KI
    assert ausweich_endpunkt(ki) is None
    ki.anbieter, ki.ausweichen = "ollama", "tippfehler"
    assert ausweich_endpunkt(ki) is None


def test_ausweiche_nimmt_das_schnellste_aktuelle_modell():
    gemini = anbieter("gemini")
    modelle = ["gemini-2.0-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-lite",
               "gemini-2.5-flash-lite-preview-09-2025", "gemini-2.5-pro"]
    assert ausweich_modell(gemini, modelle) == "gemini-2.5-flash-lite"
    assert ausweich_modell(gemini, modelle + ["gemini-flash-lite-latest"]) == \
        "gemini-flash-lite-latest"
    assert ausweich_modell(gemini, []) == gemini.modell


# -- Client: die Restzeit wird zum Socket-Timeout --------------------------------------

class _Antwort:
    def __init__(self, daten):
        self._daten = daten

    def read(self):
        return self._daten

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.mark.parametrize("vorgabe, erwartet", [(None, 60.0), (3.5, 3.5), (999, 60.0)])
def test_client_kuerzt_den_timeout_auf_die_restzeit(monkeypatch, vorgabe, erwartet):
    gesehen = []

    def urlopen(request, timeout=None):
        gesehen.append(timeout)
        return _Antwort(json.dumps({"message": {"content": "ok"}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    ChatClient(LLMEndpointConfig()).complete("S", "u", timeout=vorgabe)
    assert gesehen == [erwartet]


# -- In der Pipeline -------------------------------------------------------------------

@pytest.fixture
def kurze_grenze(monkeypatch):
    monkeypatch.setattr(frist_mod, "GRUND_S", 0.2)
    monkeypatch.setattr(frist_mod, "PRO_WORT_S", 0.0)


def test_pipeline_fuegt_bei_gerissener_grenze_den_rohtext_ein(kurze_grenze):
    p, _llm, injector = make_pipeline(RAW_NONTRIVIAL, llm=LangsamesLLM(dauer=5))
    t0 = time.monotonic()
    assert p.process(AUDIO, 16000) == "fallback"
    assert time.monotonic() - t0 < 2.0
    assert gruende.KI_FRIST in p.last_reason
    assert "rohe text" in injector.injected[-1]


def test_pipeline_ueberspringen_ist_kein_fehler(kurze_grenze, monkeypatch):
    monkeypatch.setattr(frist_mod, "GRUND_S", 10.0)
    p, _llm, injector = make_pipeline(RAW_NONTRIVIAL, llm=LangsamesLLM(dauer=5))
    threading.Timer(0.2, p.frist.ueberspringen).start()
    t0 = time.monotonic()
    assert p.process(AUDIO, 16000) == "ok"
    assert time.monotonic() - t0 < 2.0
    assert p.last_reason == gruende.UEBERSPRUNGEN
    assert "rohe text" in injector.injected[-1]


def test_pipeline_bereinigt_ueber_die_ausweiche(kurze_grenze):
    p, _llm, injector = make_pipeline(RAW_NONTRIVIAL, llm=LangsamesLLM(dauer=5))
    p.frist.ausweich_llm = FakeLLM(reply=CLEAN_NONTRIVIAL)
    p.frist.ausweich_name = "Google Gemini"
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected[-1] == CLEAN_NONTRIVIAL
    assert p.last_reason == gruende.mit_detail(gruende.AUSGEWICHEN, "Google Gemini")


def test_schnelle_ki_bleibt_unberuehrt():
    p, llm, injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply=CLEAN_NONTRIVIAL))
    assert p.process(AUDIO, 16000) == "ok"
    assert injector.injected[-1] == CLEAN_NONTRIVIAL and p.last_reason == ""


def test_nachbearbeitung_erbt_keine_abgelaufene_grenze():
    p, _llm, _inj = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply=CLEAN_NONTRIVIAL))
    p.frist._ende = time.monotonic() - 100     # Grenze des letzten Diktats
    assert p.reprocess(RAW_NONTRIVIAL) == CLEAN_NONTRIVIAL


# -- Der Haken in der App --------------------------------------------------------------

def _app(state):
    from fleech.ui.state import AppState

    gemeldet, gestoppt = [], []
    app = SimpleNamespace(
        _freihand_lauscher=lambda: None,
        bus=SimpleNamespace(state=getattr(AppState, state),
                            progress=SimpleNamespace(emit=gemeldet.append)),
        pipeline=SimpleNamespace(frist=KiFrist()),
        controller=SimpleNamespace(stop_if_active=lambda: gestoppt.append(True)),
    )
    return app, gemeldet, gestoppt


def test_haken_waehrend_der_verarbeitung_ueberspringt_die_ki():
    from fleech.ui.desktop import DesktopApp

    app, gemeldet, gestoppt = _app("PROCESSING")
    DesktopApp._finish_recording(app)
    assert app.pipeline.frist.uebersprungen and not gestoppt
    assert gemeldet == ["Füge ohne KI ein …"]


def test_haken_waehrend_der_aufnahme_beendet_sie_wie_bisher():
    from fleech.ui.desktop import DesktopApp

    app, _gemeldet, gestoppt = _app("LISTENING")
    DesktopApp._finish_recording(app)
    assert gestoppt and not app.pipeline.frist.uebersprungen


# -- Die Einstellung -------------------------------------------------------------------

def test_ausweiche_steht_nur_bei_lokaler_ki_und_ist_aus(qapp, tmp_path, monkeypatch):
    import fleech.usersettings as us
    from fleech.ui.settings import ki_ausweichen
    from fleech.ui.settings_window import SettingsPanel
    from fleech.usersettings import UserSettings
    from PySide6.QtWidgets import QComboBox

    monkeypatch.setattr(us, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(ki_ausweichen, "modelle_abrufen", lambda *a, **k: [])
    geaendert = []
    panel = SettingsPanel(UserSettings(), geaendert.append, lambda: [])
    seite = panel._pages.widget(SettingsPanel.PAGES.index("KI"))
    boxen = seite.findChildren(QComboBox)
    haupt = next(b for b in boxen if b.findData("ollama") >= 0)
    ausweiche = next(b for b in boxen if b.itemData(0) == "" and b.findData("gemini") > 0)

    assert ausweiche.currentData() == "" and panel.settings.ki.ausweichen == ""
    assert not ausweiche.isHidden()
    assert ausweiche.findData("ollama") < 0 and ausweiche.findData("custom") < 0

    ausweiche.setCurrentIndex(ausweiche.findData("gemini"))
    assert panel.settings.ki.ausweichen == "gemini" and geaendert[-1] == "ki"

    haupt.setCurrentIndex(haupt.findData("openai"))     # Cloud als Haupt-KI
    assert ausweiche.isHidden()
