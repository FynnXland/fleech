"""Prüft die Übersetzung gegen den Code — ohne Qt, für Test und Kommandozeile.

    python -m fleech.i18n.pruefung [pfade …]          fehlende/kaputte Einträge
    python -m fleech.i18n.pruefung --offen [pfade …]  Texte, die noch nicht durch tr() gehen

`--offen` ist eine Suchhilfe, kein Urteil: Es meldet deutsch aussehende Zeichenketten
außerhalb von `tr()`/`N_()`, Logmeldungen und Docstrings. Darunter sind auch
Prompts, Schlüssel und Muster, die bewusst deutsch bleiben.
"""

from __future__ import annotations

import ast
import re
import string
import sys
from pathlib import Path

from . import lade_katalog

PAKET = Path(__file__).resolve().parent.parent
_MARKER = {"tr", "N_"}
_LOG = {"debug", "info", "warning", "error", "exception", "critical", "log"}
_DEUTSCH = re.compile(r"[äöüÄÖÜß]|\b[A-Za-zÄÖÜäöüß]{2,} [A-Za-zÄÖÜäöüß]{2,}")


def _name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _dateien(pfade) -> list[Path]:
    if not pfade:
        pfade = [PAKET]
    out: list[Path] = []
    for p in map(Path, pfade):
        p = p.resolve()
        out += sorted(p.rglob("*.py")) if p.is_dir() else [p]
    return [p for p in out if "i18n" not in p.parts]


def _baum(datei: Path):
    return ast.parse(datei.read_text(encoding="utf-8"), filename=str(datei))


def texte(pfade=None) -> dict[str, list[str]]:
    """Alle Literale in tr("…")/N_("…") → Fundstellen."""
    funde: dict[str, list[str]] = {}
    for datei in _dateien(pfade):
        for knoten in ast.walk(_baum(datei)):
            if (isinstance(knoten, ast.Call) and _name(knoten.func) in _MARKER
                    and knoten.args and isinstance(knoten.args[0], ast.Constant)
                    and isinstance(knoten.args[0].value, str)):
                funde.setdefault(knoten.args[0].value, []).append(
                    f"{datei.relative_to(PAKET.parent)}:{knoten.lineno}")
    return funde


def platzhalter(text: str) -> set[str]:
    try:
        return {f for _, f, _, _ in string.Formatter().parse(text) if f is not None}
    except ValueError:
        return {"<kaputt>"}


def fehler(pfade=None, sprache: str = "en") -> list[str]:
    """Fehlende Einträge, abweichende Platzhalter, tr() auf Modulebene, tr(f"…")."""
    katalog = lade_katalog(sprache)
    meldungen = []
    for text, orte in texte(pfade).items():
        if text not in katalog:
            meldungen.append(f"fehlt ({orte[0]}): {text!r}")
        elif platzhalter(text) != platzhalter(katalog[text]):
            meldungen.append(f"Platzhalter weichen ab ({orte[0]}): {text!r}")
    for datei in _dateien(pfade):
        baum = _baum(datei)
        ort = datei.relative_to(PAKET.parent)
        for knoten in ast.walk(baum):
            if (isinstance(knoten, ast.Call) and _name(knoten.func) == "tr"
                    and knoten.args and isinstance(knoten.args[0], ast.JoinedStr)):
                meldungen.append(f"tr(f\"…\") ({ort}:{knoten.lineno}) — Platzhalter benutzen")
        for anweisung in baum.body:
            if isinstance(anweisung, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for knoten in ast.walk(anweisung):
                if isinstance(knoten, ast.Call) and _name(knoten.func) == "tr":
                    meldungen.append(f"tr() auf Modulebene ({ort}:{knoten.lineno}) — N_() benutzen")
    return meldungen


def offen(pfade=None) -> list[str]:
    """Deutsch aussehende Literale außerhalb von tr/N_, Logs und Docstrings."""
    meldungen = []
    for datei in _dateien(pfade):
        baum = _baum(datei)
        ausgenommen: set[int] = set()
        for knoten in ast.walk(baum):
            if isinstance(knoten, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if knoten.body and isinstance(knoten.body[0], ast.Expr):
                    ausgenommen.add(id(knoten.body[0].value))
            if isinstance(knoten, ast.Call):
                n = _name(knoten.func)
                if n in _MARKER or n in _LOG:
                    for kind in ast.walk(knoten):
                        ausgenommen.add(id(kind))
        for knoten in ast.walk(baum):
            if id(knoten) in ausgenommen:
                continue
            if isinstance(knoten, ast.JoinedStr):
                stueck = "".join(v.value for v in knoten.values if isinstance(v, ast.Constant))
                for kind in ast.walk(knoten):
                    ausgenommen.add(id(kind))
            elif isinstance(knoten, ast.Constant) and isinstance(knoten.value, str):
                stueck = knoten.value
            else:
                continue
            if _DEUTSCH.search(stueck):
                kurz = stueck.strip().replace("\n", " ")[:90]
                meldungen.append(f"{datei.relative_to(PAKET.parent)}:{knoten.lineno}: {kurz}")
    return meldungen


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if argv and argv[0] == "--offen":
        zeilen = offen(argv[1:])
    else:
        zeilen = fehler(argv)
    for z in zeilen:
        print(z)
    print(f"— {len(zeilen)} Meldung(en)", file=sys.stderr)
    return 1 if zeilen and (not argv or argv[0] != "--offen") else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
