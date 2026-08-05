"""Den gesamten Quellcode in EINE Datei schreiben — Vorlage fuer eine externe Analyse.

## Wozu

Ein Gutachten (Deep Research, Code-Review durch ein anderes Modell) braucht den Code am
Stueck. Die Konzeptdatei beschreibt, WAS Fleech tut und warum; sie ist bewusst keine
Code-Ablage. Deshalb ein eigener Export daneben.

## Was NICHT exportiert wird

Alles, was mit echten Diktaten zu tun hat. Der Verlauf (`history.db`), das Protokoll,
`settings.json` mit Lizenzschluessel und Woerterbuch, die Diagnose-Aufnahmen — nichts
davon gehoert in eine Datei, die aus der Hand gegeben wird. Der Export liest
ausschliesslich aus dem Projektordner und dort nur Quelldateien; er fasst
`%APPDATA%\\Fleech` nie an.

Zusaetzlich laeuft eine Geheimnis-Pruefung ueber jede Datei: Wer versehentlich einen
Schluessel einchecken wuerde, soll ihn nicht auch noch exportieren.

## Aufruf

    .venv/Scripts/python packaging/export_quellcode.py
    .venv/Scripts/python packaging/export_quellcode.py --ohne-tests --ziel D:/pfad.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent

# Was hinein gehoert — Quellcode, Prompts, Konfiguration, Doku.
ORDNER = [
    ("fleech", "*.py", "Anwendung"),
    ("tests", "*.py", "Testsuite"),
    ("packaging", "*.py", "Build und Auslieferung"),
    ("prompts", "*.md", "Prompt-Dateien (die Anweisungen an das Sprachmodell)"),
    ("docs", "*.md", "Dokumentation"),
]
EINZELDATEIEN = ["config.yaml", "CLAUDE.md", "CHANGELOG.md", "README.md",
                 "requirements.txt", "pyproject.toml", "pytest.ini"]

# Muster, die auf ein echtes Geheimnis hindeuten. Bewusst eng: Ein zu breites Muster
# wuerde bei jedem Testschluessel anschlagen und die Pruefung waere schnell abgeschaltet.
_GEHEIMNISSE = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI-artiger Schluessel"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "GitHub-Token"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,}"), "Google-API-Schluessel"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "privater Schluessel"),
]


# Geprüfte Fundstellen. Bewusst EINZELN und mit Begruendung statt eines weichen
# Musters: Eine Ausnahme, die man versteht, bleibt ueberpruefbar — eine Heuristik,
# die „Testschluessel" zu erraten versucht, laesst irgendwann einen echten durch.
_GEPRUEFT = {
    "tests/test_licensing.py":
        "Wegwerf-Ed25519-Schluessel, eigens fuer diesen Test erzeugt (siehe Kommentar "
        "dort). Er signiert nichts Echtes; der Test prueft nur die Formatpruefung.",
}


def _pruefe_geheimnisse(pfad: Path, inhalt: str) -> list:
    schluessel = pfad.as_posix()
    treffer = []
    for muster, was in _GEHEIMNISSE:
        if not muster.search(inhalt):
            continue
        if schluessel in _GEPRUEFT:
            print(f"[export] geprueft und in Ordnung — {schluessel}: {_GEPRUEFT[schluessel]}")
            continue
        treffer.append(f"{pfad}: {was}")
    return treffer


def _sammle(ohne_tests: bool) -> list:
    dateien = []
    for name in EINZELDATEIEN:
        pfad = WURZEL / name
        if pfad.is_file():
            dateien.append(("Projektwurzel", pfad))
    for ordner, muster, titel in ORDNER:
        if ohne_tests and ordner == "tests":
            continue
        basis = WURZEL / ordner
        if not basis.is_dir():
            continue
        for pfad in sorted(basis.rglob(muster)):
            if "__pycache__" in pfad.parts or ".venv" in pfad.parts:
                continue
            dateien.append((titel, pfad))
    return dateien


def _git_stand() -> str:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=WURZEL,
                                capture_output=True, text=True, timeout=10).stdout.strip()
        zweig = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=WURZEL,
                               capture_output=True, text=True, timeout=10).stdout.strip()
        sauber = subprocess.run(["git", "status", "--porcelain"], cwd=WURZEL,
                                capture_output=True, text=True, timeout=10).stdout.strip()
        return f"{zweig} @ {commit}" + ("" if not sauber else " (mit ungespeicherten Änderungen)")
    except Exception:
        return "unbekannt"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ziel", default=str(WURZEL / "export" / "fleech-quellcode.md"))
    p.add_argument("--ohne-tests", action="store_true",
                   help="Testsuite weglassen (rund ein Drittel der Zeilen)")
    args = p.parse_args()

    sys.path.insert(0, str(WURZEL))
    from fleech.version import APP_VERSION

    dateien = _sammle(args.ohne_tests)
    ziel = Path(args.ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)

    teile, warnungen, zeilen_gesamt = [], [], 0
    letzte_gruppe = None
    for gruppe, pfad in dateien:
        try:
            inhalt = pfad.read_text(encoding="utf-8")
        except Exception as fehler:
            warnungen.append(f"{pfad}: nicht lesbar ({fehler})")
            continue
        warnungen.extend(_pruefe_geheimnisse(pfad.relative_to(WURZEL), inhalt))
        zeilen = inhalt.count("\n") + 1
        zeilen_gesamt += zeilen
        if gruppe != letzte_gruppe:
            teile.append(f"\n\n# {gruppe}\n")
            letzte_gruppe = gruppe
        rel = pfad.relative_to(WURZEL).as_posix()
        sprache = {"py": "python", "md": "markdown", "yaml": "yaml",
                   "toml": "toml", "ini": "ini", "txt": "text"}.get(pfad.suffix.lstrip("."), "")
        teile.append(f"\n## `{rel}`  ({zeilen} Zeilen)\n\n```{sprache}\n{inhalt}\n```\n")

    kopf = (
        f"# Fleech — vollständiger Quellcode\n\n"
        f"> Version **{APP_VERSION}** · Git: {_git_stand()}\n"
        f"> {len(dateien)} Dateien, {zeilen_gesamt:,} Zeilen.\n\n"
        f"Automatisch erzeugt von `packaging/export_quellcode.py`. Diese Datei enthält\n"
        f"**nur Quellcode, Prompts, Konfiguration und Dokumentation** — keine Diktate,\n"
        f"keinen Verlauf, keine Einstellungen, keinen Lizenzschlüssel.\n\n"
        f"Die inhaltliche Darstellung des Projekts steht in\n"
        f"`docs/fleech-gesamtkonzept.md`; sie ist der bessere Einstieg als diese Datei.\n"
    ).replace(",", ".")

    ziel.write_text(kopf + "".join(teile), encoding="utf-8")
    groesse = ziel.stat().st_size

    print(f"[export] {ziel}")
    print(f"[export] {len(dateien)} Dateien, {zeilen_gesamt} Zeilen, "
          f"{groesse / 1024 / 1024:.1f} MB")
    # Grobe Schaetzung fuer die Planung eines Gutachtens: ~3,4 Zeichen je Token.
    print(f"[export] grob {groesse / 3.4 / 1000:.0f}k Token")
    if warnungen:
        print("\n[export] WARNUNGEN:")
        for w in warnungen:
            print(f"  ! {w}")
        return 1
    print("[export] Keine Geheimnisse gefunden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
