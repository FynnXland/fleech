"""Text-Bausteine: ein gesprochenes Kuerzel fuegt einen festen Textblock ein.

„Baustein Signatur" → die E-Mail-Signatur, „Baustein Absage" → die Standard-Absage.
Bausteine sind bewusst *deterministisch*: kein LLM entscheidet ueber ihren Inhalt,
sie werden Zeichen fuer Zeichen so eingefuegt, wie sie in den Einstellungen stehen.

Damit das auch MITTEN im Diktat funktioniert („Vielen Dank fuer Ihre Nachricht.
Baustein Signatur"), laeuft es wie bei den Inline-Formeln ueber Platzhalter: Der
Baustein-Aufruf wird VOR dem Cleanup durch einen Marker ([[B1]]) ersetzt, das
Modell sieht also nur den kurzen Marker, und erst unmittelbar vor der Injection
tritt der echte Text an dessen Stelle. Das hat zwei Vorteile gegenueber „Text
direkt einsetzen und dann bereinigen":

- Das Modell kann eine Signatur oder ein Code-Geruest nicht umformulieren.
- Die Ausgabe-Guards (Grounding, Wortgetreue) vergleichen Marker mit Marker und
  schlagen nicht an, nur weil ein langer Block Text dazugekommen ist.

Eintraege kommen als rohe Zeilen aus dem Settings-UI: "Kuerzel => Text".
Ein "\\n" im Text wird zum echten Zeilenumbruch (das Zeilen-Eingabefeld kann
keine mehrzeiligen Werte).
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

DEFAULT_KEYWORD = "Baustein"

# Priming-Deckel: der initial_prompt teilt sich das Whisper-Kontextfenster mit
# Woerterbuch und Signalwort — nur die ersten Kuerzel nennen.
_MAX_PRIMED = 20


def parse_snippets(lines: list) -> list[tuple[str, str]]:
    """Rohzeilen → [(Kuerzel, Text)]. Ignoriert Leeres/Kommentare/kaputte Zeilen.

    Laengere Kuerzel stehen vorn: „Absage Termin" muss vor „Absage" greifen,
    sonst bliebe das zweite Wort als Diktat-Rest stehen."""
    parsed: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in lines or []:
        line = str(line).strip()
        if not line or line.startswith("#") or "=>" not in line:
            continue
        key, _, text = line.partition("=>")
        key, text = key.strip(), text.strip()
        if not key or not text or key.lower() in seen:
            continue
        seen.add(key.lower())
        parsed.append((key, text.replace("\\n", "\n")))
    parsed.sort(key=lambda item: -len(item[0].split()))
    return parsed


def snippet_marker(index: int) -> str:
    """Platzhalter fuer einen Baustein. Gleiche ASCII-Form wie die Formel-Marker
    ([[F1]]) — Cleanup-Modelle uebernehmen die zuverlaessig."""
    return f"[[B{index + 1}]]"


def _key_pattern(keyword: str, key: str) -> re.Pattern | None:
    """Regex fuer „<Signalwort> <Kuerzel>" mit ASR-Toleranz.

    Zwischen Signalwort und Kuerzel (und zwischen mehrwortigen Kuerzel-Teilen)
    darf Whisper Komma, Doppelpunkt oder Bindestrich setzen — genau wie beim
    Formel-Ende („Formel Ende" / „Formel-Ende" / „Formelende")."""
    gap = r"[\s:,\-]*"
    try:
        parts = gap.join(re.escape(w) for w in key.split())
        return re.compile(
            rf"\b{re.escape(keyword)}{gap}{parts}\b[\s:,.!?\-]*",
            re.IGNORECASE,
        )
    except re.error:  # kaputter Nutzer-Eintrag darf das Diktat nie reissen
        log.warning("Baustein-Kuerzel %r ergibt kein gueltiges Muster — ignoriert.", key)
        return None


def expand_snippets(raw: str, snippets: list[tuple[str, str]],
                    keyword: str = DEFAULT_KEYWORD) -> tuple[str, list[str]]:
    """(Text mit Markern, [Baustein-Texte in Marker-Reihenfolge]).

    Ohne Treffer kommt der Text unveraendert und eine leere Liste zurueck — der
    Aufrufer laeuft dann exakt wie bisher."""
    text = raw or ""
    if not text or not snippets or not keyword:
        return text, []

    texts: list[str] = []

    for key, value in snippets:
        pattern = _key_pattern(keyword, key)
        if pattern is None:
            continue

        def _swap(_match, _value=value):
            marker = snippet_marker(len(texts))
            texts.append(_value)
            return f"{marker} "

        text = pattern.sub(_swap, text)

    if texts:
        log.info("Bausteine erkannt: %d (%s).", len(texts),
                 ", ".join(t.splitlines()[0][:30] for t in texts))
    return re.sub(r"[ \t]{2,}", " ", text).strip(), texts


_SENTENCE_END = ".!?:;,"


def restore_snippets(text: str, texts: list[str]) -> str:
    """Marker → die echten Baustein-Texte. Ein nicht mehr vorhandener Marker wird
    stillschweigend uebersprungen; darum kuemmert sich der Aufrufer (Platzhalter-
    Ueberlebens-Check), damit ein Baustein nie einfach verschwindet.

    Naht-Kosmetik: Das Cleanup-Modell setzt hinter den Marker gern ein Satzzeichen
    („… nochmal [[B1]]."). Endet der Baustein selbst schon auf einem Satzzeichen,
    ergaebe das „… absagen.." — live beobachtet. Das doppelte Zeichen faellt weg;
    der Baustein-Text selbst bleibt unangetastet.
    """
    for i, value in enumerate(texts):
        marker = snippet_marker(i)
        while marker in text:
            start = text.index(marker)
            after = start + len(marker)
            if value.rstrip().endswith(tuple(_SENTENCE_END)):
                while after < len(text) and text[after] in _SENTENCE_END:
                    after += 1
            text = text[:start] + value + text[after:]
    return text


def markers_survived(before: str, after: str, count: int) -> bool:
    """Sind alle Marker, die vor dem Cleanup im Text standen, noch da?"""
    return not any(
        snippet_marker(i) in before and snippet_marker(i) not in after
        for i in range(count)
    )


def snippet_initial_prompt(snippets: list[tuple[str, str]],
                           keyword: str = DEFAULT_KEYWORD) -> str:
    """Whisper-Priming fuer Signalwort + Kuerzel ("" wenn keine Bausteine).

    Ohne Priming verhoert sich die Erkennung genau an der Stelle, an der es weh
    tut: „Baustein Signatur" wird zu „Bau Stein Signatur" und der Baustein
    greift nicht."""
    if not snippets or not keyword:
        return ""
    keys = [k for k, _ in snippets][:_MAX_PRIMED]
    return "Bausteine: " + ", ".join(f"{keyword} {k}" for k in keys) + "."


def mentions_keyword(raw: str, keyword: str = DEFAULT_KEYWORD) -> bool:
    """Kommt das Signalwort vor? Fuer die Diagnose: Signalwort gehoert, aber kein
    Kuerzel getroffen = vermutlich verhoertes Kuerzel — das gehoert ins Log,
    sonst sucht der Nutzer den Fehler bei sich."""
    if not keyword:
        return False
    return bool(re.search(rf"\b{re.escape(keyword)}\b", raw or "", re.IGNORECASE))
