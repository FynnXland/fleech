"""Persoenliches Woerterbuch: Vokabular-Priming und deterministische Ersetzung.

Zwei Wirkpfade gegen systematisch falsch erkannte Fachbegriffe und Eigennamen —
Priming vor der Erkennung, Ersetzung nach der Erkennung — plus die Auto-Erkennung
wahrscheinlicher Fehlschreibungen, aus der Vorschlaege fuers Woerterbuch entstehen.

Lag bis 5.5.1 in textutils.py. Der Name verdeckte, dass hier eine eigene Funktion
mit eigenem Zustand (Nutzungszaehler, Ignorier-Liste) steckt und nicht Texthelfer.
"""

from __future__ import annotations

import re


# Eintraege kommen als rohe Zeilen aus dem Settings-UI:
#   "Begriff"            → nur Vokabular-Priming (wirkt VOR der Erkennung)
#   "falsch => richtig"  → Priming (richtig) + Ersetzungsregel auf dem fertigen Text
#                          (greift auch, wenn Whisper den Begriff schon falsch schrieb)

_DICT_MAX_PROMPT_TERMS = 60  # initial_prompt klein halten (Whisper-Kontextfenster)


def parse_dictionary(lines: list) -> tuple[list[str], list[tuple[str, str]]]:
    """Rohzeilen → (Vokabular-Begriffe, Ersetzungsregeln). Ignoriert Leeres/Kommentare."""
    terms: list[str] = []
    rules: list[tuple[str, str]] = []
    for line in lines or []:
        line = str(line).strip()
        if not line or line.startswith("#"):
            continue
        if "=>" in line:
            wrong, _, right = line.partition("=>")
            wrong, right = wrong.strip(), right.strip()
            if wrong and right:
                rules.append((wrong, right))
                terms.append(right)
        else:
            terms.append(line)
    # Duplikate raus, Reihenfolge stabil (erste Nennung gewinnt).
    seen: set[str] = set()
    unique_terms = []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            unique_terms.append(t)
    return unique_terms, rules


def primed_terms(terms: list[str], usage: dict | None = None) -> list[str]:
    """Die Begriffe, die tatsaechlich ins Whisper-Priming gehen (max. 60).

    Ueber dem Limit wurde bisher stumpf nach Dateireihenfolge abgeschnitten — wer
    viel Fachvokabular pflegt, verlor Priming ausgerechnet fuer die Begriffe am
    Listenende, ohne es zu merken. Jetzt entscheidet die tatsaechliche Nutzung
    (wie oft der Begriff zuletzt in eingefuegtem Text vorkam); bei Gleichstand
    bleibt die Dateireihenfolge erhalten (sorted ist stabil)."""
    if usage:
        terms = sorted(terms, key=lambda t: -int(usage.get(t.lower(), 0)))
    return terms[:_DICT_MAX_PROMPT_TERMS]


def vocab_initial_prompt(terms: list[str], usage: dict | None = None) -> str:
    """Whisper-Priming-Satz aus dem Nutzer-Vokabular ("" wenn leer)."""
    if not terms:
        return ""
    return "Vokabular: " + ", ".join(primed_terms(terms, usage)) + "."


def find_terms_in_text(text: str, terms: list[str]) -> list[str]:
    """Welche Woerterbuch-Begriffe kommen im Text vor? (wortgrenzen-basiert, case-
    insensitiv) — Grundlage fuer die Nutzungs-Priorisierung des Primings."""
    found = []
    for term in terms:
        cleaned = term.strip()
        if not cleaned:
            continue
        try:
            if re.search(rf"\b{re.escape(cleaned)}\b", text, re.IGNORECASE):
                found.append(cleaned)
        except re.error:  # kaputter Nutzer-Eintrag darf nie stoeren
            continue
    return found


# Gesprochene Zeichen, die ausgeschrieben nie gemeint sind. Wer „Slash Hunter Help"
# diktiert, meint `/hunter help` — das Wort „Slash" im Fliesstext ist der Ausnahmefall.
#
# BEWUSST KLEIN GEHALTEN. Nicht dabei sind „Minus", „Plus", „Mal", „Punkt", „Komma“:
# das sind gewoehnliche deutsche Woerter („minus zwanzig Grad", „ein Punkt, der …"),
# und eine Ersetzung wuerde dort mehr kaputt machen als sie hilft. Rechnende Minus-
# Zeichen entstehen ohnehin im Formel-Parser. Wer mehr braucht, legt sich eine eigene
# Ersetzungsregel unter „Textersetzung" an.
_GESPROCHENE_ZEICHEN = {
    "slash": "/", "schrägstrich": "/", "schraegstrich": "/",
    "backslash": "\\", "hashtag": "#", "raute": "#",
    "unterstrich": "_", "klammeraffe": "@",
}
# Das Zeichen klebt am FOLGENDEN Wort ("Slash Hunter" → "/Hunter"): so wird es
# gesprochen (Pfade, Handles, Kanaele). Am Satzende bleibt es allein stehen.
_ZEICHEN_RE = re.compile(
    r"\b(" + "|".join(sorted(_GESPROCHENE_ZEICHEN, key=len, reverse=True)) + r")\b"
    r"(\s+)(?=\S)", re.IGNORECASE)


def spoken_symbols(text: str) -> str:
    """„Slash Hunter" → „/Hunter". Wandelt nur die eindeutigen Zeichenwoerter."""
    if not text:
        return text

    def ersetze(m):
        return _GESPROCHENE_ZEICHEN[m.group(1).lower()]

    return _ZEICHEN_RE.sub(ersetze, text)


def apply_dictionary(text: str, rules: list[tuple[str, str]]) -> str:
    """Wendet die Ersetzungsregeln wortgrenzen-basiert und case-insensitiv an."""
    for wrong, right in rules:
        try:
            text = re.sub(
                rf"\b{re.escape(wrong)}\b", right.replace("\\", "\\\\"), text,
                flags=re.IGNORECASE,
            )
        except re.error:
            continue  # kaputte Nutzer-Regel darf das Diktat nie reissen
    return text


# -- Auto-Erkennung wahrscheinlicher Fehlschreibungen ------------------------------------
#
# "Selbstlernendes Woerterbuch": Woerter im fertigen Text, die einem Woerterbuch-
# Begriff SEHR aehnlich sind (Edit-Distanz 1–2), aber nicht exakt passen, sind mit
# hoher Wahrscheinlichkeit ASR-Fehlschreibungen ("Kimano" statt "Kimono"). Sie
# loesen eine Rueckfrage aus; bestaetigt der Nutzer, wird daraus automatisch eine
# Ersetzungsregel. Bewusst NUR gegen das Nutzer-Woerterbuch geprueft — eine
# allgemeine "ungewoehnliche Woerter"-Heuristik ohne Referenzlexikon wuerde
# staendig falsch anschlagen.


def levenshtein(a: str, b: str, max_dist: int = 3) -> int:
    """Edit-Distanz mit Abbruch bei > max_dist (dann max_dist+1)."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            val = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur.append(val)
            best = min(best, val)
        if best > max_dist:
            return max_dist + 1
        prev = cur
    return prev[-1]


_CANDIDATE_WORD_RE = re.compile(r"[a-zA-ZäöüÄÖÜß]+")


def find_dictionary_candidates(
    text: str, terms: list[str], ignores: list | None = None
) -> list[tuple[str, str]]:
    """[(erkanntes_wort, gemeinter_begriff)] — nahe, aber nicht exakte Treffer.

    Distanz-Toleranz laengenabhaengig (kurze Woerter: 1, ab 6 Zeichen: 2), damit
    kurze Alltagswoerter nicht faelschlich "in der Naehe" von Begriffen liegen.
    ignores: bereits abgelehnte Paare "erkannt => gemeint" (nie wieder fragen).
    """
    if not terms:
        return []
    ignored = {str(i).lower() for i in (ignores or [])}
    term_by_lower = {t.lower(): t for t in terms}
    seen: set[str] = set()
    results: list[tuple[str, str]] = []
    for word in _CANDIDATE_WORD_RE.findall(text):
        lower = word.lower()
        if len(lower) < 4 or lower in seen or lower in term_by_lower:
            continue
        seen.add(lower)
        for term_lower, term in term_by_lower.items():
            if len(term_lower) < 4:
                continue
            allowed = 2 if min(len(lower), len(term_lower)) >= 6 else 1
            if levenshtein(lower, term_lower, allowed) <= allowed:
                if f"{lower} => {term_lower}" not in ignored:
                    results.append((word, term))
                break
    return results
