"""Baut eine einsatzbereite Pipeline aus AppConfig + UserSettings.

Eine Stelle fuer die Verdrahtung (STT/LLM-Endpoints/Prompts/Intervention/Mathe-
Prioritaet), die sowohl die Desktop-App als auch der --pipeline-selftest-Diagnose-
modus nutzen — verhindert Drift zwischen "echtem Betrieb" und Selbsttest.
"""

from __future__ import annotations

from .config import AppConfig
from .document import DocumentTracker
from .injection import TextInjector
from .llm import ChatClient
from .pipeline import Pipeline
from .prompts import load_command_prompt, load_prompt
from .stt import create_stt
from .usersettings import UserSettings


def build_pipeline(config: AppConfig, settings: UserSettings, injector=None,
                   status=None) -> Pipeline:
    """status: optionales Callable(str) fuer laengere Zwischenschritte ("Formel wird
    berechnet …"). Die Desktop-App reicht hier den StateBus durch; CLI/Tests lassen
    es weg."""
    pipeline = _build(config, settings, injector, status)
    pipeline.set_dictionary(settings.output.dictionary,
                            settings.output.dictionary_usage)
    pipeline.set_snippets(settings.output.snippets, settings.output.snippet_keyword)
    pipeline.auto_latex = settings.math.enabled and settings.math.auto_latex
    pipeline.spoken_symbols = settings.output.spoken_symbols
    pipeline.status_callback = status
    return pipeline


def _build(config, settings, injector, status=None) -> Pipeline:
    # Defensiv: ein aelterer Benutzer-Prompt-Ordner (%APPDATA%\Fleech\prompts) hat die
    # neue Datei evtl. nicht — dann faellt der KI-Prompting-Modus auf Cleanup zurueck,
    # statt den App-Start zu reissen.
    try:
        prompt_engineer = load_prompt(config.prompts_dir, "prompt_engineer")
    except FileNotFoundError:
        prompt_engineer = ""
    return Pipeline(
        stt=create_stt(config.stt),
        cleanup_llm=ChatClient(config.llm_cleanup),
        fast_llm=ChatClient(config.llm_cleanup_fast),
        adaptive=settings.advanced.adaptive_cleanup,
        injector=injector if injector is not None else TextInjector(
            config.injection.restore_clipboard, config.injection.paste_delay_ms
        ),
        cleanup_prompt=load_prompt(config.prompts_dir, "cleanup"),
        trigger_word=config.command.trigger_word,
        command_llm=ChatClient(config.llm_command),
        command_prompt=load_command_prompt(config.prompts_dir, config.command.trigger_word),
        prompt_engineer_prompt=prompt_engineer,
        tracker=DocumentTracker(),
        intervention=settings.output.intervention,
        strong_addendum=load_prompt(config.prompts_dir, "cleanup-strong"),
    )
