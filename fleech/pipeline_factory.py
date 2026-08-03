"""Baut eine einsatzbereite Pipeline aus AppConfig + UserSettings.

Eine Stelle fuer die Verdrahtung (STT/LLM-Endpoints/Prompts/Intervention/Mathe-
Prioritaet), die sowohl die Desktop-App als auch der --pipeline-selftest-Diagnose-
modus nutzen — verhindert Drift zwischen "echtem Betrieb" und Selbsttest.
"""

from __future__ import annotations

import logging

from .config import AppConfig
from .document import DocumentTracker
from .injection import TextInjector
from .llm import ChatClient
from .pipeline import Pipeline
from .prompts import load_command_prompt, load_prompt
from .stt import create_stt
from .usersettings import UserSettings

log = logging.getLogger(__name__)


# Ausgabeformate mit eigener Prompt-Datei. "prompt" laeuft weiterhin ueber das
# eigene Feld (Bestandscode), alles Weitere kommt hierueber dazu.
_FORMAT_PROMPT_FILES = {"email": "email", "summary": "summary"}


def _load_format_prompts(config: AppConfig) -> dict:
    """{Format: System-Prompt}. Fehlende Datei = Format faellt auf Cleanup zurueck.

    Defensiv, weil ein aelterer Benutzer-Prompt-Ordner (%APPDATA%\Fleech\prompts)
    die neuen Dateien nicht hat — das darf den Start nie reissen."""
    geladen = {}
    for fmt, datei in _FORMAT_PROMPT_FILES.items():
        try:
            geladen[fmt] = load_prompt(config.prompts_dir, datei)
        except FileNotFoundError:
            log.info("Prompt fuer Ausgabeformat %r fehlt — faellt auf Cleanup zurueck.", fmt)
    return geladen


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
    # Weitere Ausgabeformate: eine Prompt-Datei je Format. Fehlt sie, faellt genau
    # dieses Format auf normales Cleanup zurueck — kein Startfehler.
    pipeline.format_prompts = _load_format_prompts(config)
    # Absendername fuer die E-Mail-Signatur (Einstellungen → Allgemein).
    pipeline.author_name = settings.general.display_name
    # Englischer Cleanup-Prompt (optional): fehlt er, bleibt es beim deutschen.
    try:
        pipeline.cleanup_prompt_en = load_prompt(config.prompts_dir, "cleanup-en")
    except FileNotFoundError:
        log.debug("prompts/cleanup-en.md fehlt — englische Diktate laufen ueber "
                  "den deutschen Prompt.")
    pipeline.sprache = settings.general.language or "de"
    pipeline.status_callback = status
    # Projekt-Gedaechtnis (fleech/kontext.py). Die Erstbefuellung aus dem Verlauf
    # laeuft im HINTERGRUND: An 1189 Diktaten gemessen 3,7 s — im Start waere das
    # eine spuerbare Verzoegerung fuer etwas, das erst beim naechsten Diktat zaehlt.
    pipeline.kontext_lernen = bool(
        getattr(settings.advanced, "kontext_lernen", True))
    if pipeline.kontext is not None and pipeline.kontext_lernen:
        import threading

        def _fuellen():
            try:
                from .kontext import erstbefuellung

                erstbefuellung(pipeline.kontext)
            except Exception:
                log.debug("Erstbefuellung des Gedaechtnisses fehlgeschlagen.",
                          exc_info=True)

        threading.Thread(target=_fuellen, daemon=True).start()
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
