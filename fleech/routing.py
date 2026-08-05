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


# Gesprochene Namen der Ausgabeformate. Mehrere Fassungen je Format, weil man es
# beim Sprechen nicht zweimal gleich sagt — und weil die Erkennung „Stichpunkte"
# je nach Betonung als „Stichpunkt" oder „Stich Punkte" liefert.
_FORMAT_WOERTER = {
    "summary": ("stichpunkte", "stichpunkt", "stich punkte", "bulletpoints",
                "stichpunktliste", "als liste", "auflistung"),
    "email": ("email", "e mail", "mail"),
    "prompt": ("ki prompt", "prompt", "ki-prompt", "promt"),
    "": ("diktat", "normal", "standard", "fliesstext", "fliess text"),
}

# Wie der Zusatz eingeleitet wird. „als" ist der Normalfall; „bitte als" und
# „mach das als" kommen im Sprechfluss genauso vor.
_EINLEITUNG = r"(?:bitte\s+)?(?:mach(?:e)?\s+(?:das\s+)?)?(?:bitte\s+)?als"

# Nur in den letzten Woertern suchen. Ein „als E-Mail" mitten im Diktat („ich
# schicke das als E-Mail raus") ist Inhalt, kein Befehl — die Beschraenkung aufs
# Ende ist der ganze Unterschied.
_MAX_ZUSATZ_WOERTER = 6


def _normalisiere_endstueck(text: str) -> str:
    text = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def split_format_suffix(raw: str) -> tuple[str, str | None]:
    """Trennt ein am ENDE angesagtes Ausgabeformat ab.

    „Text Text Text, als Stichpunkte" → („Text Text Text", "summary")

    Rueckgabe: (Diktat ohne den Zusatz, Format) — Format ist None, wenn keiner
    gefunden wurde. Ein leerer String als Format heisst „ausdruecklich normal",
    was etwas anderes ist als None (kein Wunsch geaeussert).

    Bewusst NUR am Ende und nur mit Einleitung: „Ich schicke das als E-Mail raus"
    steht mitten im Satz und bleibt Diktat. Wer das Format ansagt, tut das zum
    Schluss und mit „als".
    """
    text = (raw or "").rstrip()
    if not text:
        return raw, None
    woerter = text.split()
    # Nur das Endstueck betrachten: Einleitung + Formatname sind hoechstens
    # ein paar Woerter.
    # Von LANG nach kurz: Sonst greift „als E-Mail" schon bei zwei Woertern und
    # das „Mach das" davor bliebe als Text stehen („… Mach das" im Diktat).
    for anzahl in range(min(_MAX_ZUSATZ_WOERTER, len(woerter)), 1, -1):
        kandidat = _normalisiere_endstueck(" ".join(woerter[-anzahl:]))
        treffer = re.fullmatch(rf"{_EINLEITUNG}\s+(.+)", kandidat)
        if not treffer:
            continue
        rest = treffer.group(1).strip()
        for fmt, namen in _FORMAT_WOERTER.items():
            if rest in namen:
                davor = " ".join(woerter[:-anzahl]).rstrip(" ,.;:-–—")
                # Ohne Diktat davor waere nur der Befehl gesprochen worden —
                # dann gibt es nichts zu formatieren.
                if not davor.strip():
                    return raw, None
                return davor, fmt
    return raw, None
