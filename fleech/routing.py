"""Modus-Routing: billiger String-Check auf dem Roh-Transkript nach dem Loslassen.

Befehls-Modus (Trigger-Wort) → Cleanup (Default). Formeln haben seit v3.0.0 KEINEN
eigenen Modus mehr: Sie werden vor dem Cleanup deterministisch uebersetzt
(fleech/formula.py), es gibt also nichts mehr zu routen.
"""

from __future__ import annotations

import re
from enum import Enum


class Mode(Enum):
    CLEANUP = "cleanup"
    COMMAND = "command"
    # KI-Prompting: Diktat → professionell strukturierter Prompt. Wird NICHT ueber
    # den Text erkannt, sondern per Hotkey-Latch aktiviert (prompt_mode-Parameter).
    PROMPT = "prompt"


def detect_mode(raw_transcript: str, trigger_word: str) -> Mode:
    """Entscheidet auf dem rohen ASR-Text, welche Pipeline laeuft."""
    text = raw_transcript.strip()
    if trigger_word and re.search(
        rf"\b{re.escape(trigger_word)}\b", text, re.IGNORECASE
    ):
        return Mode.COMMAND
    return Mode.CLEANUP


def text_before_trigger(raw: str, trigger_word: str) -> str:
    """Der reine Diktat-Teil VOR dem ersten Safe-Word (ohne Befehl).

    Scheitert ein Befehl, fuegen wir nur diesen Teil ein — Safe-Word UND Anweisung
    tauchen dann NIE im Ergebnis auf. Ohne/kein Trigger im Text: der ganze Rohtext.
    """
    if not trigger_word:
        return raw
    match = re.search(rf"\b{re.escape(trigger_word)}\b", raw, re.IGNORECASE)
    if not match:
        return raw
    return raw[: match.start()].strip()


def split_command_continuation(raw: str, trigger_word: str) -> tuple[str, str]:
    """Teilt eine Befehls-Aeusserung am Signal-Endwort ("<Trigger> Ende").

    "… Kimono, mach das formeller. Kimono Ende. Und weiter im Text …"
    → ("… Kimono, mach das formeller.", "Und weiter im Text …")

    Der Teil vor dem Endwort ist die Anweisung, der Teil danach normales Diktat,
    das nach dem Befehl weiterverarbeitet wird. Ohne Endwort: (raw, "").
    ASR-Toleranz wie beim Formel-Ende: "Kimono Ende" / "Kimono-Ende" / "Kimonoende".
    """
    if not trigger_word:
        return raw, ""
    match = re.search(
        rf"\b{re.escape(trigger_word)}[\s\-]*,?\s*ende\b[\s.,!?]*",
        raw, re.IGNORECASE,
    )
    if not match:
        return raw, ""
    return raw[: match.start()].strip(), raw[match.end():].strip()
