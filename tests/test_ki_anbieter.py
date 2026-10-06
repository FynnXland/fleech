"""KI-Anbieter (6.1.0): lokal, Cloud mit eigenem Schluessel, oder ohne KI.

Kein Test spricht ein echtes Netz an: `urlopen` wird ersetzt, der Schluesselbund
ist ein Dict (conftest.schluesselbund).
"""

import io
import json
import urllib.error

import pytest

from fleech.config import AppConfig
from fleech.llm import ChatClient, apikeys
from fleech.llm.providers import (
    AUS, OLLAMA, anbieter, ist_lokales_ollama, ki_lokal, modell_vorschlag,
    modelle_abrufen, wende_an,
)
from fleech.usersettings import KiSettings, UserSettings


class _Antwort(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen(monkeypatch, antwort: dict, gesehen: list):
    def falsch(request, timeout=None):
        gesehen.append(request)
        return _Antwort(json.dumps(antwort).encode())

    monkeypatch.setattr("urllib.request.urlopen", falsch)


# -- Liste und Wahl ------------------------------------------------------------------


def test_unbekannter_anbieter_faellt_auf_lokal():
    assert anbieter("gibtsnicht").id == OLLAMA
    assert anbieter("").id == OLLAMA
    assert anbieter("OpenAI").id == "openai"


def test_lokal_laesst_config_yaml_stehen():
    cfg = AppConfig()
    wende_an(KiSettings(), cfg)
    assert cfg.llm_cleanup.provider == OLLAMA
    assert cfg.llm_cleanup.base_url == "http://127.0.0.1:11434"
    assert cfg.llm_cleanup.num_ctx == 8192


def test_lokal_mit_eigenem_modell():
    cfg = AppConfig()
    wende_an(KiSettings(modell="qwen3:8b"), cfg)
    assert {cfg.llm_cleanup.model, cfg.llm_command.model,
            cfg.llm_cleanup_fast.model} == {"qwen3:8b"}


def test_cloud_setzt_alle_drei_endpunkte():
    cfg = AppConfig()
    wende_an(KiSettings(anbieter="anthropic"), cfg)
    for ep in (cfg.llm_cleanup, cfg.llm_cleanup_fast, cfg.llm_command):
        assert ep.provider == "anthropic"
        assert ep.base_url == "https://api.anthropic.com/v1"
        assert ep.model == anbieter("anthropic").modell
        assert ep.num_ctx == 0 and ep.reasoning_effort == ""


def test_eigener_server_nimmt_die_eingetragene_adresse():
    cfg = AppConfig()
    wende_an(KiSettings(anbieter="custom", adresse="http://127.0.0.1:1234/v1",
                        modell="local-model"), cfg)
    assert cfg.llm_cleanup.base_url == "http://127.0.0.1:1234/v1"
    assert cfg.llm_cleanup.model == "local-model"
    # localhost-Adresse, aber KEIN Ollama — keine Vorlade-/Entladeaufrufe dorthin.
    assert not ist_lokales_ollama(cfg.llm_cleanup)


def test_ohne_ki_laesst_endpunkte_unberuehrt():
    cfg = AppConfig()
    wende_an(KiSettings(anbieter=AUS), cfg)
    assert cfg.llm_cleanup.provider == OLLAMA


def test_ki_lokal():
    s = UserSettings()
    assert ki_lokal(s)
    s.ki.anbieter = "gemini"
    assert not ki_lokal(s)
    s.ki.anbieter = AUS
    assert not ki_lokal(s)


def test_modell_vorschlag_bevorzugt_schnelle_modelle():
    gemini = anbieter("gemini")
    liste = ["gemini-9-pro", "gemini-9-flash", "gemini-9-flash-lite"]
    assert modell_vorschlag(gemini, liste) == "gemini-9-flash-lite"
    assert modell_vorschlag(gemini, [gemini.modell, "x"]) == gemini.modell


def test_einstellungen_tragen_den_abschnitt_und_alte_dateien_laden(tmp_path):
    pfad = tmp_path / "settings.json"
    s = UserSettings()
    s.ki.anbieter = "openai"
    s.ki.modell = "gpt-4o-mini"
    s.save(pfad)
    roh = json.loads(pfad.read_text(encoding="utf-8"))
    assert roh["ki"] == {"anbieter": "openai", "modell": "gpt-4o-mini", "adresse": ""}
    assert "sk-" not in pfad.read_text(encoding="utf-8")
    alt = tmp_path / "alt.json"
    alt.write_text('{"general": {"display_name": "X"}}', encoding="utf-8")
    assert UserSettings.load(alt).ki.anbieter == OLLAMA


# -- Schluessel ----------------------------------------------------------------------


def test_schluessel_im_bund(schluesselbund):
    assert apikeys.lies("openai") == ""
    assert apikeys.speichere("openai", "  sk-geheim-123456  ")
    assert schluesselbund.daten[("Fleech", "openai")] == "sk-geheim-123456"
    assert apikeys.lies("openai") == "sk-geheim-123456"
    assert apikeys.speichere("openai", "")              # leer = entfernen
    assert apikeys.lies("openai") == ""


def test_schluessel_aus_umgebung(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "aus-env")
    assert apikeys.lies("anthropic") == "aus-env"
    monkeypatch.setenv("FLEECH_GROQ_API_KEY", "fleech-env")
    assert apikeys.lies("groq") == "fleech-env"


def test_ohne_schluesselbund_wird_nichts_in_dateien_geschrieben(monkeypatch):
    monkeypatch.setattr(apikeys, "_bund", lambda: None)
    assert apikeys.speichere("openai", "sk-x") is False


def test_maskiert_zeigt_nie_die_mitte():
    assert apikeys.maskiert("sk-" + "proj-abcdefghijklmnop") == "sk-p…mnop"
    assert apikeys.maskiert("kurz") == "••••"


# -- Client: drei Schnittstellen -----------------------------------------------------


def _endpunkt(anbieter_id, modell="m"):
    cfg = AppConfig()
    wende_an(KiSettings(anbieter=anbieter_id, modell=modell), cfg)
    return cfg.llm_cleanup


def test_openai_form(monkeypatch):
    apikeys.speichere("openai", "sk-test")
    gesehen = []
    _urlopen(monkeypatch, {"choices": [{"message": {"content": "Sauber."},
                                        "finish_reason": "stop"}]}, gesehen)
    client = ChatClient(_endpunkt("openai", "gpt-4o-mini"))
    assert client.complete("SYS", "roh") == "Sauber."
    anfrage = gesehen[0]
    assert anfrage.full_url == "https://api.openai.com/v1/chat/completions"
    assert anfrage.get_header("Authorization") == "Bearer sk-test"
    body = json.loads(anfrage.data)
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    assert body["temperature"] == 0.0
    assert "options" not in body and "keep_alive" not in body
    assert client.last_truncated is False


def test_openai_denkmodelle_ohne_temperature_und_abbruch_erkannt(monkeypatch):
    gesehen = []
    _urlopen(monkeypatch, {"choices": [{"message": {"content": "halb"},
                                        "finish_reason": "length"}]}, gesehen)
    client = ChatClient(_endpunkt("openai", "gpt-5-mini"))
    client.complete("S", "u")
    assert "temperature" not in json.loads(gesehen[0].data)
    assert client.last_truncated is True


def test_gemini_ueber_openai_form(monkeypatch):
    gesehen = []
    _urlopen(monkeypatch, {"choices": [{"message": {"content": "ok"}}]}, gesehen)
    ChatClient(_endpunkt("gemini", "gemini-x")).complete("S", "u")
    assert gesehen[0].full_url.startswith(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")


def test_anthropic_form(monkeypatch):
    apikeys.speichere("anthropic", "sk-" + "ant-test")
    gesehen = []
    _urlopen(monkeypatch, {"content": [{"type": "text", "text": "Hallo."}],
                           "stop_reason": "end_turn"}, gesehen)
    client = ChatClient(_endpunkt("anthropic", "claude-haiku-4-5"))
    assert client.complete("SYS", "roh") == "Hallo."
    anfrage = gesehen[0]
    assert anfrage.full_url == "https://api.anthropic.com/v1/messages"
    assert anfrage.get_header("X-api-key") == "sk-" + "ant-test"
    assert anfrage.get_header("Anthropic-version")
    body = json.loads(anfrage.data)
    assert body["system"] == "SYS" and body["max_tokens"] > 0
    assert body["messages"] == [{"role": "user", "content": "roh"}]


def test_anthropic_abbruch_bei_max_tokens(monkeypatch):
    _urlopen(monkeypatch, {"content": [{"type": "text", "text": "x"}],
                           "stop_reason": "max_tokens"}, [])
    client = ChatClient(_endpunkt("anthropic"))
    client.complete("S", "u")
    assert client.last_truncated is True


def test_ollama_bleibt_beim_eigenen_weg(monkeypatch):
    gesehen = []
    _urlopen(monkeypatch, {"message": {"content": "ok"}, "done_reason": "stop"}, gesehen)
    ChatClient(_endpunkt(OLLAMA)).complete("S", "u")
    assert gesehen[0].full_url.endswith("/api/chat")
    assert json.loads(gesehen[0].data)["options"]["num_ctx"] == 8192


def test_modellliste_filtert_und_kuerzt(monkeypatch):
    gesehen = []
    _urlopen(monkeypatch, {"data": [{"id": "models/gemini-9-flash"},
                                    {"id": "text-embedding-3"},
                                    {"id": "gpt-4o-mini"}]}, gesehen)
    namen = modelle_abrufen(anbieter("openai"), "sk-x")
    assert namen == ["gemini-9-flash", "gpt-4o-mini"]
    assert gesehen[0].full_url == "https://api.openai.com/v1/models"


# -- Pipeline -----------------------------------------------------------------------


def _pipeline():
    from fleech.pipeline import Pipeline

    return Pipeline(stt=None, cleanup_llm=None, injector=None, cleanup_prompt="S")


@pytest.mark.parametrize("code,grund,art", [
    (401, "KI_SCHLUESSEL", "key"),
    (429, "KI_KONTINGENT", "quota"),
    (500, "KI_DIENST", ""),
])
def test_cloud_ausfall_wird_benannt(code, grund, art):
    from types import SimpleNamespace

    from fleech import gruende

    p = _pipeline()
    llm = SimpleNamespace(cfg=_endpunkt("openai"))
    fehler = urllib.error.HTTPError("u", code, "x", {}, None)
    p._merke_llm_ausfall(llm, fehler)
    assert getattr(gruende, grund) in p.last_reason
    assert p.last_error_kind == art


def test_ohne_ki_fragt_kein_modell():
    class Verboten:
        def complete(self, *a):
            raise AssertionError("Modell gefragt, obwohl die KI aus ist")

    p = _pipeline()
    p.cleanup_llm = p.fast_llm = Verboten()
    p.ki_aus = True
    text, rueckfall = p._clean_text("also das ist ein ganz normaler satz mit inhalt")
    assert rueckfall is False
    assert text.startswith("also das ist")


def test_ohne_ki_ruhen_befehle_und_formate(monkeypatch, tmp_path):
    from fleech import pipeline_factory
    from fleech.config import load_config

    monkeypatch.setattr(pipeline_factory, "create_stt", lambda cfg: None)
    s = UserSettings()
    s.ki.anbieter = AUS
    cfg = load_config()
    s.apply_to(cfg)
    p = pipeline_factory.build_pipeline(cfg, s, injector=object())
    assert p.ki_aus and p.trigger_word == "" and p.format_prompts == {}


def test_einrichtung_ohne_lokale_ki_nur_spracherkennung(monkeypatch):
    from fleech import provisioning

    monkeypatch.setattr(provisioning, "whisper_present", lambda m: True)
    schritte = provisioning.build_steps([], "large-v3-turbo", "")
    assert [s.key for s in schritte] == ["stt"]


# -- Einstellungsseite ----------------------------------------------------------------


def test_datenschutz_satz_je_wahl():
    from fleech.ui.settings.ki import datenschutz_satz

    assert "auf diesem Rechner" in datenschutz_satz(OLLAMA)[0]
    assert "Anthropic" in datenschutz_satz("anthropic")[0]
    assert "nicht die Tonaufnahme" in datenschutz_satz("openai")[0]
    assert "Nur Spracherkennung" in datenschutz_satz(AUS)[0]


def test_fehlertexte_sagen_was_zu_tun_ist():
    from fleech.ui.settings.ki import fehlertext

    def http(code):
        return urllib.error.HTTPError("u", code, "x", {}, None)

    assert "Schlüssel" in fehlertext(http(401))
    assert "Kontingent" in fehlertext(http(429))
    assert "Verbindung" in fehlertext(urllib.error.URLError("weg"))


def test_seite_zeigt_schluesselfeld_nur_bei_cloud(qapp, tmp_path, monkeypatch):
    import fleech.usersettings as us
    from fleech.ui.settings_window import SettingsPanel

    monkeypatch.setattr(us, "SETTINGS_PATH", tmp_path / "settings.json")
    geaendert = []
    panel = SettingsPanel(UserSettings(), geaendert.append, lambda: [])
    seite = panel._pages.widget(SettingsPanel.PAGES.index("KI"))
    from PySide6.QtWidgets import QComboBox, QLineEdit

    anbieter_box = next(b for b in seite.findChildren(QComboBox) if b.count() > 5)
    passwort = next(e for e in seite.findChildren(QLineEdit)
                    if e.echoMode() == QLineEdit.Password)
    assert passwort.parentWidget().isHidden()          # lokal: kein Schluessel
    anbieter_box.setCurrentIndex(anbieter_box.findData("openai"))
    assert panel.settings.ki.anbieter == "openai"
    assert geaendert[-1] == "ki"
    assert not passwort.parentWidget().isHidden()
    passwort.setText("sk-neu-1234567890")
    passwort.editingFinished.emit()
    assert apikeys.lies("openai") == "sk-neu-1234567890"
    assert passwort.text() == ""                        # Feld leert sich wieder
