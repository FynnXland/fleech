"""Konfiguration: config.yaml + ENV-Overrides (FLEECH_*).

Prioritaet: ENV-Variable > config.yaml > eingebaute Defaults.
API-Keys stehen nie in der YAML-Datei — dort steht nur der Name der ENV-Variable,
aus der der Key gelesen wird (api_key_env).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .platformpaths import user_data_dir
from .resources import resource_dir

PROJECT_ROOT = resource_dir()  # Dev = Projektordner, gepackt = sys._MEIPASS
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# Benutzerpfad fuer Overrides der gepackten App (config.yaml/.env editierbar, ohne
# den Installationsordner anzufassen).
USER_DIR = user_data_dir()


@dataclass
class HotkeyConfig:
    dictate: str = "f9"


@dataclass
class AudioConfig:
    samplerate: int = 16000
    device: Any = None  # None = Standard-Mikrofon; sonst Index oder Name (sounddevice)


@dataclass
class STTConfig:
    # Der Cloud-Fallback (Groq) ist mit v3.6.0 entfallen: Er lief ueber das
    # OpenAI-SDK, war ohne API-Key ohnehin nie aktiv und widersprach der Zusage,
    # dass kein Ton den Rechner verlaesst.
    backend: str = "faster_whisper"
    model_size: str = "large-v3-turbo"
    device: str = "auto"  # auto | cuda | cpu
    compute_type: str = "auto"
    language: str = "de"
    vad_filter: bool = True
    # Erkennen, waehrend man spricht (`fleech/stt/abschnitte.py`): Abschnitte an
    # Sprechpausen schon in der Aufnahme erkennen — nach dem Loslassen bleibt nur
    # der letzte. Aus = alles erst nach dem Loslassen, am Stueck.
    abschnitte: bool = True


@dataclass
class LLMEndpointConfig:
    """Ein OpenAI-kompatibler Chat-Endpoint (Ollama, DeepSeek, Groq, ...)."""

    # BEWUSST die IP, nicht "localhost": Der Name kostet unter Windows 2,05 s pro
    # Anfrage (fehlschlagende IPv6-Aufloesung, gemessen). `ollama_root()` korrigiert
    # Bestandskonfigurationen zusaetzlich zur Laufzeit.
    base_url: str = "http://127.0.0.1:11434"
    # An echten Diktaten gemessen schneller als qwen3.5:9b UND wortgetreuer als jedes
    # getestete kleine Modell (siehe config.yaml). Halbe Groesse = haelt sich eher im
    # VRAM, was in der Praxis mehr Zeit spart als die reine Rechenzeit.
    model: str = "gemma3:4b"
    api_key_env: str = ""
    temperature: float = 0.0
    timeout: float = 60.0
    # Fuer Thinking-Modelle (z. B. qwen3.5 auf Ollama): "none" schaltet das Reasoning
    # ab — sonst denkt das Modell sekundenlang pro Diktat. Leer = Parameter nicht senden.
    # gemma3 denkt nicht → leer.
    reasoning_effort: str = ""
    # Zusaetzliche Regex-Muster fuer Denkbloecke dieses Providers (die gaengigen
    # <think>/<reasoning>-Varianten kennt der Client bereits). Noetig, falls ein
    # neues Modell ein unbekanntes Format nutzt — sonst landet das Reasoning
    # sichtbar im eingefuegten Text.
    reasoning_patterns: list = field(default_factory=list)
    # Kontextfenster fuer LOKALES Ollama (0 = Ollama-Default 4096). Ollama laedt
    # Modelle immer mit 4096 Token, unabhaengig davon, was das Modell koennte —
    # und der OpenAI-Aufsatz ignoriert jede Option dagegen. Bei einem langen Diktat
    # verbraucht allein der System-Prompt ~3000 Token; die Antwort bricht dann mitten
    # im Satz ab. Deshalb setzt Fleech den Wert ueber Ollamas eigene API.
    # Gemessen: bei normalen Diktaten kostet das keine Zeit (die Rechenzeit haengt an
    # den tatsaechlichen Token, nicht am reservierten Fenster).
    num_ctx: int = 8192

@dataclass
class CommandConfig:
    # ASR-Robustheit empirisch getestet (TTS + large-v3-turbo/large-v3): "Kimono",
    # "Ananas", "Salami" ueberleben beide Modelle fehlerfrei; "Redax" wurde
    # durchgaengig als "Idax"/"Edax"/"Redux" gehoert und ist raus.
    trigger_word: str = "Kimono"


@dataclass
class AudioFocusConfig:
    mode: str = "soft_duck"          # pure_mic | soft_duck | hard_focus
    duck_level: float = 0.25         # Soft Duck: Restlautstaerke fremder Apps (relativ)
    hard_duck_level: float = 0.08    # Hard Focus: deutlich staerkere Absenkung
    fade_ms: int = 250               # weiche Rampe statt hartem Cut
    hard_mute: bool = False          # opt-in: komplett stummschalten statt ducken
    # Nutzer-Sperrliste (Teilstrings von Geraetenamen) aus den Einstellungen.
    blocked_devices: list = field(default_factory=list)


@dataclass
class OverlayConfig:
    enabled: bool = True
    model_size: str = "small"     # kleines, eigenes Modell nur fuer die Vorschau
    # Wie oft neu dekodiert wird. 1000 statt 700 ms (5.12.4): Die Vorschau ist
    # eine Lesehilfe, das Diktat haengt nicht an ihr — und jeder Lauf konkurriert
    # mit dem finalen Erkennen um dieselbe Grafikkarte.
    interval_ms: int = 1000
    window_seconds: float = 12.0  # gleitendes Fenster; Aelteres wird eingefroren


@dataclass
class InjectionConfig:
    restore_clipboard: bool = True
    paste_delay_ms: int = 150


@dataclass
class AppConfig:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    llm_cleanup: LLMEndpointConfig = field(default_factory=LLMEndpointConfig)
    # Zweitmodell fuer kurze Aeusserungen (adaptives Routing) — BEWUSST dasselbe
    # Modell wie llm_cleanup. Ein eigenes kleines Modell brachte nur 0,1 s, ergaenzte
    # aber viermal so viel eigenen Text und kostete dauerhaft VRAM fuer einen zweiten
    # Satz Gewichte. Bleibt als Nahtstelle erhalten: Taucht ein deutlich schnelleres
    # Modell auf, das genauso wortgetreu ist, wird hier wieder getrennt.
    llm_cleanup_fast: LLMEndpointConfig = field(
        default_factory=lambda: LLMEndpointConfig(reasoning_effort="")
    )
    # Befehls-Modus (Prompt 2): erbt alles von llm_cleanup; in der YAML koennen unter
    # llm.command einzelne Felder (z. B. reasoning_effort, model) abweichen.
    llm_command: LLMEndpointConfig = field(default_factory=LLMEndpointConfig)
    command: CommandConfig = field(default_factory=CommandConfig)
    audio_focus: AudioFocusConfig = field(default_factory=AudioFocusConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    injection: InjectionConfig = field(default_factory=InjectionConfig)
    prompts_dir: Path = PROJECT_ROOT / "prompts"


def _apply(obj: Any, data: dict | None) -> None:
    """Uebertraegt YAML-Werte auf ein Dataclass-Objekt (nur bekannte Felder)."""
    if not data:
        return
    for key, value in data.items():
        if hasattr(obj, key):
            setattr(obj, key, value)


# ENV-Variable → (Config-Objektpfad, Feldname)
_ENV_OVERRIDES = {
    "FLEECH_HOTKEY": ("hotkey", "dictate"),
    "FLEECH_STT_BACKEND": ("stt", "backend"),
    "FLEECH_STT_MODEL": ("stt", "model_size"),
    "FLEECH_STT_DEVICE": ("stt", "device"),
    "FLEECH_STT_LANGUAGE": ("stt", "language"),
    "FLEECH_LLM_BASE_URL": ("llm_cleanup", "base_url"),
    "FLEECH_LLM_MODEL": ("llm_cleanup", "model"),
    "FLEECH_TRIGGER_WORD": ("command", "trigger_word"),
}


def _load_dotenv() -> None:
    """Laedt KEY=VALUE-Zeilen aus .env — Benutzerpfad zuerst, dann Projekt/Bundle.

    Bereits gesetzte ENV-Variablen werden NICHT ueberschrieben.
    """
    for base in (USER_DIR, PROJECT_ROOT):
        dotenv = base / ".env"
        if not dotenv.is_file():
            continue
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _resolve_config_path(path: Path | str | None) -> Path:
    if path:
        return Path(path)
    user_cfg = USER_DIR / "config.yaml"  # Override der installierten App
    return user_cfg if user_cfg.is_file() else DEFAULT_CONFIG_PATH


def load_config(path: Path | str | None = None) -> AppConfig:
    import copy

    cfg = AppConfig()
    _load_dotenv()
    llm_command_overrides: dict | None = None
    llm_fast_overrides: dict | None = None
    fast_model_default = cfg.llm_cleanup_fast.model  # vor der Vererbung sichern

    config_path = _resolve_config_path(path)
    if config_path.is_file():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        _apply(cfg.hotkey, raw.get("hotkey"))
        _apply(cfg.audio, raw.get("audio"))
        _apply(cfg.stt, raw.get("stt"))
        llm = raw.get("llm") or {}
        _apply(cfg.llm_cleanup, llm.get("cleanup"))
        llm_command_overrides = llm.get("command")
        llm_fast_overrides = llm.get("cleanup_fast")
        _apply(cfg.command, raw.get("command"))
        _apply(cfg.overlay, raw.get("overlay"))
        _apply(cfg.injection, raw.get("injection"))
        if raw.get("prompts_dir"):
            cfg.prompts_dir = Path(raw["prompts_dir"])
            if not cfg.prompts_dir.is_absolute():
                cfg.prompts_dir = config_path.parent / cfg.prompts_dir

    for env_name, (section, attr) in _ENV_OVERRIDES.items():
        value = os.environ.get(env_name)
        if value:
            setattr(getattr(cfg, section), attr, value)

    # Befehls-Endpoint erbt vom (fertig aufgeloesten) Cleanup-Endpoint; die YAML-Sektion
    # llm.command ueberschreibt nur die dort explizit gesetzten Felder.
    cfg.llm_command = copy.deepcopy(cfg.llm_cleanup)
    _apply(cfg.llm_command, llm_command_overrides)

    # Schnelles Cleanup-Modell erbt die Verbindung (base_url/api_key/timeout) vom
    # Cleanup-Endpoint, behaelt aber sein kleines Modell + leeres reasoning_effort.
    fast = copy.deepcopy(cfg.llm_cleanup)
    fast.model = fast_model_default
    fast.reasoning_effort = ""
    _apply(fast, llm_fast_overrides)
    cfg.llm_cleanup_fast = fast

    return cfg
