"""Einstellung „Spracherkennung": Standard oder Deutsch-optimiert."""

import types

from fleech.config import AppConfig
from fleech.stt.modellwahl import DEUTSCH, STANDARD, modell_fuer
from fleech.usersettings import UserSettings


def test_modell_fuer():
    assert modell_fuer("deutsch", STANDARD) == DEUTSCH
    assert modell_fuer("standard", DEUTSCH) == STANDARD
    # Ein in config.yaml eigens gesetztes Modell bleibt bei „standard" stehen.
    assert modell_fuer("standard", "medium") == "medium"
    assert modell_fuer("unsinn", "medium") == "medium"


def test_deutsch_braucht_eine_fassung_mit_tokenizer():
    """Ohne tokenizer.json nimmt faster-whisper den whisper-tiny-Tokenizer — mit
    falsch gezaehlten v3-Sondertoken. Die gewaehlte Fassung bringt ihn mit."""
    assert DEUTSCH == "jimmymeister/whisper-large-v3-turbo-german-ct2"


def test_apply_to_setzt_das_modell():
    s, cfg = UserSettings(), AppConfig()
    s.advanced.stt_modell = "deutsch"
    s.apply_to(cfg)
    assert cfg.stt.model_size == DEUTSCH
    s.advanced.stt_modell = "standard"
    s.apply_to(cfg)
    assert cfg.stt.model_size == STANDARD


def test_vorgabe_ist_standard():
    assert UserSettings().advanced.stt_modell == "standard"


class _SyncThread:
    def __init__(self, target=None, name=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


def _app(wahl, monkeypatch, vorhanden=True, laden_ok=True):
    import fleech.provisioning as prov
    import fleech.stt as stt_mod
    import fleech.ui.desktopapp.modelle as modelle

    monkeypatch.setattr(modelle.threading, "Thread", _SyncThread)
    monkeypatch.setattr(prov, "whisper_present", lambda ziel: vorhanden)
    geladen = []
    monkeypatch.setattr(prov, "ensure_whisper",
                        lambda ziel, on_progress=None: geladen.append(ziel) or laden_ok)
    monkeypatch.setattr(stt_mod, "create_stt", lambda cfg: ("stt", cfg.model_size))
    hinweise, gestoppt = [], []
    app = types.SimpleNamespace(
        settings=types.SimpleNamespace(advanced=types.SimpleNamespace(stt_modell=wahl)),
        config=types.SimpleNamespace(stt=types.SimpleNamespace(model_size=STANDARD)),
        pipeline=types.SimpleNamespace(stt="alt"),
        bus=types.SimpleNamespace(hinweis=types.SimpleNamespace(emit=hinweise.append)),
        controller=types.SimpleNamespace(stop_if_active=lambda: gestoppt.append(1)),
        _warm_up_stt=lambda: None,
    )
    return app, hinweise, geladen


def test_wechsel_auf_deutsch_steckt_um(monkeypatch):
    from fleech.ui.desktopapp.modelle import ModelleMixin

    app, hinweise, geladen = _app("deutsch", monkeypatch)
    ModelleMixin._wechsle_stt_modell(app)
    assert app.pipeline.stt == ("stt", DEUTSCH)
    assert app.config.stt.model_size == DEUTSCH
    assert geladen == []                     # war schon da
    assert hinweise == ["Jetzt aktiv: deutsche Spracherkennung."]


def test_fehlendes_modell_wird_erst_geladen(monkeypatch):
    from fleech.ui.desktopapp.modelle import ModelleMixin

    app, hinweise, geladen = _app("deutsch", monkeypatch, vorhanden=False)
    ModelleMixin._wechsle_stt_modell(app)
    assert geladen == [DEUTSCH]
    assert hinweise[0].startswith("Lade deutsche Spracherkennung")
    assert app.pipeline.stt == ("stt", DEUTSCH)


def test_gescheiterter_download_laesst_die_alte_erkennung_stehen(monkeypatch):
    from fleech.ui.desktopapp.modelle import ModelleMixin

    app, hinweise, _ = _app("deutsch", monkeypatch, vorhanden=False, laden_ok=False)
    ModelleMixin._wechsle_stt_modell(app)
    assert app.pipeline.stt == "alt"
    assert app.config.stt.model_size == STANDARD
    assert "bisherige bleibt aktiv" in hinweise[-1]


def test_gleiche_wahl_tut_nichts(monkeypatch):
    from fleech.ui.desktopapp.modelle import ModelleMixin

    app, hinweise, _ = _app("standard", monkeypatch)
    ModelleMixin._wechsle_stt_modell(app)
    assert app.pipeline.stt == "alt" and hinweise == []


def test_rechenart_auto_wird_int8_auf_der_grafikkarte(monkeypatch):
    import ctranslate2

    from fleech.stt.faster_whisper_stt import waehle_rechenart

    assert waehle_rechenart("cuda", "auto") == "int8_float16"
    assert waehle_rechenart("cpu", "auto") == "int8"
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 0)
    assert waehle_rechenart("auto", "auto") == "int8"
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)
    assert waehle_rechenart("auto", "auto") == "int8_float16"
    # Ausdruecklich gesetzt = unveraendert.
    assert waehle_rechenart("cuda", "float16") == "float16"
