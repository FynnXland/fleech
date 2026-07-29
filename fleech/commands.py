"""Prompt-2-Anbindung: Eingabe-Format bauen, JSON-Antwort robust parsen."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

# Die Wort-Ueberlappungs-Helfer sind generische Textwerkzeuge und liegen deshalb in
# textutils; hier re-exportiert, weil Aufrufer sie historisch von commands importieren.
from .textutils import content_words, replacement_overlap  # noqa: F401

log = logging.getLogger(__name__)

VALID_SCOPES = {
    "none", "last_sentence", "last_paragraph", "whole_document", "dictated", "as_described",
}

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass
class CommandResult:
    append_text: str = ""
    replace_scope: str = "none"
    replacement: str = ""


def build_user_message(context: str, utterance: str) -> str:
    return f'KONTEXT: "{context}"\nÄUSSERUNG: "{utterance}"'


# -- Plausibilitaets-Check gegen halluzinierte replacements -----------------------------
#
# Beobachteter Fehlermodus: das Modell liefert statt einer Umformulierung des Zieltexts
# einen ERFUNDENEN Satz, der die Situation oder die Aktion beschreibt. Eine echte
# Umformulierung teilt zwangslaeufig Inhaltswoerter mit dem Original (Namen, Zahlen,
# Kernbegriffe) — ein erfundener Satz kaum. Bei zu geringer Ueberlappung wird der
# Befehl als verdaechtig verworfen und die Pipeline faellt auf Cleanup zurueck.
#
# Bekannte Grenze: Anweisungen, die legitim (fast) alle Woerter ersetzen — z. B.
# "uebersetz das ins Englische" — koennen faelschlich als verdaechtig gelten und landen
# dann im Cleanup-Fallback (sichtbar, nichts geht verloren). Bewusster Trade-off:
# lieber ein umstaendlicher Fallback als ein halluziniertes replacement im Textfeld.

MIN_REPLACEMENT_OVERLAP = 0.3

# Anweisungs-sensitiver Guard: manche Befehle ersetzen LEGITIM (fast) alle Woerter.
# Uebersetzungen teilen sprachbedingt keinerlei Woerter mit dem Original → Guard aus.
# Kompressionen (kuerzen/zusammenfassen) verlieren legitim viele Woerter → Schwelle
# gesenkt (Kernbegriffe ueberleben trotzdem). Kein Sicherheitsrisiko: die Anweisung
# stammt vom Nutzer selbst (bewusst nach dem Safe-Word gesprochen).
_TRANSLATION_INSTRUCTION = re.compile(
    r"\bübersetz|\buebersetz|\bins (englische|deutsche|französische|franzoesische|"
    r"spanische|italienische)\b|\bauf (englisch|deutsch|französisch|franzoesisch|"
    r"spanisch|italienisch)\b",
    re.IGNORECASE,
)
_COMPRESSION_INSTRUCTION = re.compile(
    r"\bkürz|\bkuerz|zusammenfass|\bfass\w*\b.{0,24}\bzusammen\b|komprimier|"
    r"\bin einem satz\b|\bein wort\b",
    re.IGNORECASE,
)
COMPRESSION_MIN_OVERLAP = 0.1

# Schutz vor Totalverlust (real passiert: 2701 Zeichen geloescht): ein LEERES
# replacement bedeutet "Zieltext ersatzlos loeschen" — das ist nur legitim, wenn
# die Anweisung auch nach Loeschen klingt. Liefert das Modell bei einer
# Umformulierungs-Anweisung ein leeres replacement (ueberfordert/halluziniert),
# wird der Befehl verworfen statt Text zu vernichten.
_DELETION_INSTRUCTION = re.compile(
    r"\blösch|\bloesch|\bentfern|\bstreich|\bverwirf|\bvergiss|\bweg damit\b|"
    r"\bmach\w*\b.{0,16}\bweg\b|\bdelete\b",
    re.IGNORECASE,
)


def sounds_like_deletion(utterance: str) -> bool:
    return bool(_DELETION_INSTRUCTION.search(utterance))


# Reihenfolge = Vorrang: „lösch den zusammengefassten Absatz" ist eine Loeschung.
# Bewusst dieselben Regexe wie die Guards oben — es gibt genau EINE Definition
# davon, was eine Loesch-/Uebersetzungs-/Kuerzungs-Anweisung ist. Waeren es zwei,
# koennte die Statistik etwas anderes zaehlen, als der Guard tatsaechlich tut.
_COMMAND_KINDS = (
    ("Löschen", _DELETION_INSTRUCTION),
    ("Übersetzen", _TRANSLATION_INSTRUCTION),
    ("Kürzen", _COMPRESSION_INSTRUCTION),
)


def classify_command(utterance: str) -> str:
    """Art einer Befehls-Aeusserung fuer die Insights-Statistik.

    „Umformulieren" ist der Sammelbegriff fuer alles ohne eindeutigen Marker —
    das ist der Normalfall des Befehls-Modus, kein Rest-Eimer."""
    for name, pattern in _COMMAND_KINDS:
        if pattern.search(utterance or ""):
            return name
    return "Umformulieren"


def overlap_threshold_for(utterance: str) -> float | None:
    """Guard-Schwelle je nach Art der Anweisung. None = Guard aussetzen."""
    if _TRANSLATION_INSTRUCTION.search(utterance):
        return None
    if _COMPRESSION_INSTRUCTION.search(utterance):
        return COMPRESSION_MIN_OVERLAP
    return MIN_REPLACEMENT_OVERLAP

# Plausibilitaets-Deckel gegen Ausreisser-Antworten: das Modell soll den Zielbereich
# umformulieren, nicht einen Aufsatz darueber schreiben. Grosszuegig bemessen, damit
# "mach daraus einen ausfuehrlichen Absatz" noch durchgeht.
REPLACEMENT_MAX_FACTOR = 3
REPLACEMENT_LENGTH_BUDGET = 200  # Sockel, damit kurze Ziele wachsen duerfen


def replacement_too_long(original: str, replacement: str) -> bool:
    """True = der Ersatztext sprengt jedes plausible Mass fuer eine Umformulierung."""
    if not original:
        return False
    return len(replacement) > REPLACEMENT_MAX_FACTOR * len(original) + REPLACEMENT_LENGTH_BUDGET


def replacement_plausible(
    original: str, replacement: str, min_overlap: float = MIN_REPLACEMENT_OVERLAP
) -> bool:
    if not replacement.strip() or not original.strip():
        return True  # Loeschung bzw. kein Vergleichsziel
    if len(content_words(original)) < 3:
        return True  # zu wenig Signal fuer eine belastbare Entscheidung
    return replacement_overlap(original, replacement) >= min_overlap


def parse_command_json(reply: str) -> CommandResult:
    """Extrahiert das Befehls-JSON aus der Modell-Antwort. ValueError bei Muell."""
    text = reply.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"Kein JSON-Objekt in der Antwort: {reply[:200]!r}")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ungueltiges JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON ist kein Objekt.")

    scope = str(data.get("replace_scope") or "none").strip()
    if scope not in VALID_SCOPES:
        # Unbekannter Scope soll nicht den ganzen Befehl kippen: append_text bleibt
        # nutzbar, die Ersetzung wird spaeter als nicht-aufloesbar uebersprungen.
        log.warning("Unbekannter replace_scope %r — behandle als as_described.", scope)
        scope = "as_described"

    from .textutils import strip_wrapping_quotes

    return CommandResult(
        append_text=strip_wrapping_quotes(str(data.get("append_text") or "")),
        replace_scope=scope,
        replacement=strip_wrapping_quotes(str(data.get("replacement") or "")),
    )
