"""build_pipeline() verdrahtet Config+Settings korrekt — ohne Netzwerk/Modelle zu laden.

create_stt(faster_whisper)/ChatClient laden nichts beim Konstruieren (nur beim ersten
transcribe()/complete()), daher ist dieser Test schnell und offline.
"""

from fleech.config import load_config
from fleech.pipeline_factory import build_pipeline
from fleech.usersettings import UserSettings


def test_build_pipeline_uses_custom_injector(tmp_path):
    cfg = load_config(tmp_path / "leer.yaml")
    sentinel = object()
    pipeline = build_pipeline(cfg, UserSettings(), injector=sentinel)
    assert pipeline.injector is sentinel


def test_keine_cloud_anbindung_mehr(tmp_path):
    """Zusicherung fuer „100 % lokal": Es darf keinen Client geben, der Audio oder
    Text an einen externen Dienst schickt. Frueher hing hier das multimodale
    Formel-Modell; seit v3.0.0 uebersetzt der lokale Parser (fleech/formula.py).

    Der Test ist absichtlich streng — er soll fehlschlagen, wenn jemand (auch ich)
    versehentlich einen Cloud-Pfad wieder einbaut."""
    cfg = load_config(tmp_path / "leer.yaml")
    pipeline = build_pipeline(cfg, UserSettings())

    assert not hasattr(pipeline, "math_llm")
    assert not hasattr(pipeline, "process_mixed")
    assert not hasattr(pipeline, "transcribe_math_segment")


def test_formel_automatik_kommt_aus_den_settings(tmp_path):
    cfg = load_config(tmp_path / "leer.yaml")

    settings = UserSettings()
    settings.math.enabled, settings.math.auto_latex = True, True
    assert build_pipeline(cfg, settings).auto_latex is True

    settings.math.enabled = False           # global aus schlaegt die Automatik
    assert build_pipeline(cfg, settings).auto_latex is False
