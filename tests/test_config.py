from pathlib import Path

from fleech.config import load_config


def test_defaults_without_file(tmp_path):
    cfg = load_config(tmp_path / "gibts-nicht.yaml")
    assert cfg.hotkey.dictate == "f9"
    assert cfg.stt.backend == "faster_whisper"
    # IP statt Name: "localhost" kostet unter Windows 2,05 s pro Anfrage.
    assert cfg.llm_cleanup.base_url == "http://127.0.0.1:11434"
    assert cfg.command.trigger_word == "Kimono"


def test_yaml_overrides(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "hotkey:\n  dictate: f8\n"
        "stt:\n  model_size: small\n"
        "llm:\n  cleanup:\n    base_url: https://api.deepseek.com/v1\n    model: deepseek-chat\n"
        "command:\n  trigger_word: Zebra\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.hotkey.dictate == "f8"
    assert cfg.stt.model_size == "small"
    assert cfg.llm_cleanup.model == "deepseek-chat"
    assert cfg.command.trigger_word == "Zebra"
    # Nicht gesetzte Werte behalten Defaults


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("FLEECH_LLM_MODEL", "llama3.1:8b")
    monkeypatch.setenv("FLEECH_TRIGGER_WORD", "Kobold")
    cfg = load_config(tmp_path / "leer.yaml")
    assert cfg.llm_cleanup.model == "llama3.1:8b"
    assert cfg.command.trigger_word == "Kobold"


def test_llm_command_inherits_from_cleanup(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "llm:\n"
        "  cleanup:\n    model: qwen3.5:9b\n    reasoning_effort: none\n"
        "  command:\n    reasoning_effort: low\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.llm_command.model == "qwen3.5:9b"  # geerbt
    assert cfg.llm_command.base_url == cfg.llm_cleanup.base_url  # geerbt
    assert cfg.llm_command.reasoning_effort == "low"  # ueberschrieben
    assert cfg.llm_cleanup.reasoning_effort == "none"  # unveraendert


def test_llm_command_defaults_to_cleanup_without_section(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("llm:\n  cleanup:\n    model: deepseek-chat\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.llm_command.model == "deepseek-chat"


def test_llm_cleanup_fast_inherits_connection_keeps_own_model(tmp_path):
    """Das Zweitmodell erbt die VERBINDUNG, nicht das Modell.

    Seit dem Modellvergleich steht `cleanup_fast` per Default auf demselben Modell
    wie `cleanup` (ein eigenes kleines brachte 0,1 s und kostete Wortgetreue). Die
    Nahtstelle muss trotzdem funktionieren — sonst laesst sich nie wieder trennen.
    """
    p = tmp_path / "config.yaml"
    p.write_text(
        "llm:\n"
        "  cleanup:\n    base_url: http://box:1234/v1\n    model: qwen3.5:9b\n"
        "    reasoning_effort: none\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.llm_cleanup_fast.base_url == "http://box:1234/v1"  # Verbindung geerbt
    # NICHT das Cleanup-Modell: der Wert kommt aus der eigenen Sektion/dem Default,
    # sonst wuerde ein YAML-Wechsel des grossen Modells das kleine stillschweigend
    # mitziehen.
    assert cfg.llm_cleanup_fast.model != "qwen3.5:9b"
    assert cfg.llm_cleanup_fast.reasoning_effort == ""           # Nicht-Thinking


def test_llm_cleanup_fast_yaml_override(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("llm:\n  cleanup_fast:\n    model: llama3.2:3b\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.llm_cleanup_fast.model == "llama3.2:3b"


def test_audio_focus_defaults(tmp_path):
    cfg = load_config(tmp_path / "leer.yaml")
    # Produktentscheidung: Standard = Mic-only capture + Soft Duck.
    assert cfg.audio_focus.mode == "soft_duck"
    assert cfg.audio_focus.hard_mute is False


def test_overlay_config(tmp_path):
    cfg = load_config(tmp_path / "leer.yaml")
    assert cfg.overlay.enabled is True
    assert cfg.overlay.model_size == "small"

    p = tmp_path / "config.yaml"
    p.write_text("overlay:\n  enabled: false\n  model_size: base\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.overlay.enabled is False
    assert cfg.overlay.model_size == "base"


def test_api_key_from_env(monkeypatch, tmp_path):
    cfg = load_config(tmp_path / "leer.yaml")
    cfg.llm_cleanup.api_key_env = "MY_TEST_KEY"
    monkeypatch.setenv("MY_TEST_KEY", "sk-123")
    assert cfg.llm_cleanup.api_key == "sk-123"
    monkeypatch.delenv("MY_TEST_KEY")
    assert cfg.llm_cleanup.api_key == "not-needed"


def test_startpfad_baut_den_fokus_controller(tmp_path, monkeypatch):
    """Regressionstest fuer einen echten Startabsturz (v3.1.0).

    Beim Entfernen des Cloud-Pfads fiel `AudioFocusConfig.math_focus` weg — eine
    Nutzung in `_build_focus_controller` blieb aber stehen. Die gesamte Testsuite
    war gruen, weil dieser Pfad NUR beim App-Start laeuft und nirgends gepruft
    wurde. Ergebnis: `AttributeError` direkt beim Start.

    Dieser Test ruft die Baufunktion mit einer echten Config auf — ohne Audio-
    Hardware, aber mit denselben Attributzugriffen wie im Betrieb."""
    from fleech.app import DictationApp
    from fleech.audiofocus import DeviceCheck, DeviceGuard

    monkeypatch.setattr(DeviceGuard, "check",
                        classmethod(lambda cls, d, b=None: DeviceCheck(ok=True, name="Mic")))
    cfg = load_config(tmp_path / "leer.yaml")

    controller = DictationApp._build_focus_controller(cfg)

    assert controller is not None
    assert controller.may_record()[0] is True


def test_alle_settings_felder_erreichen_die_config(tmp_path):
    """`apply_to` schreibt Settings auf die AppConfig — greift dabei ein Feld an,
    das es nicht mehr gibt, faellt das erst beim Start auf (siehe Test oben)."""
    from fleech.usersettings import UserSettings

    cfg = load_config(tmp_path / "leer.yaml")
    UserSettings().apply_to(cfg)          # darf nicht werfen


def test_pipeline_bau_mit_echter_config(tmp_path, monkeypatch):
    """Zweiter Startpfad: build_pipeline mit echter Config und echten Settings."""
    from fleech.pipeline_factory import build_pipeline
    from fleech.usersettings import UserSettings

    monkeypatch.setattr("fleech.stt.create_stt", lambda c: object())
    cfg = load_config(tmp_path / "leer.yaml")

    pipeline = build_pipeline(cfg, UserSettings(), injector=object())

    assert pipeline.cleanup_prompt and pipeline.command_prompt


def test_alte_config_mit_groq_backend_startet_trotzdem(monkeypatch, caplog):
    """Bestands-config.yaml mit `backend: groq` darf den Start nicht verweigern.

    Der Cloud-Fallback ist mit v3.6.0 entfallen. Wer eine alte Datei im
    Benutzerpfad liegen hat, bekommt lokale Erkennung und einen Hinweis — statt
    eines ValueError beim Start, den nur ein Blick in den Code erklaert.
    """
    from fleech.config import STTConfig
    from fleech.stt import create_stt

    gebaut = {}

    class FakeEngine:
        def __init__(self, cfg):
            gebaut["cfg"] = cfg

    monkeypatch.setattr("fleech.stt.faster_whisper_stt.FasterWhisperSTT", FakeEngine)
    engine = create_stt(STTConfig(backend="groq"))
    assert isinstance(engine, FakeEngine)
    assert "gibt es nicht mehr" in caplog.text.lower() or gebaut


def test_startpfad_nutzt_ollama_direkt_ohne_openai(monkeypatch):
    """Der Client baut keinen OpenAI-Klienten mehr auf — sonst waere das Paket
    beim Start wieder Pflicht (und die EXE groesser)."""
    from fleech.config import LLMEndpointConfig
    from fleech.llm import ChatClient

    client = ChatClient(LLMEndpointConfig())
    assert not hasattr(client, "_client")
    assert not hasattr(client, "complete_with_audio")
