"""Wächter: Es darf kein echtes Geheimnis im Repository landen.

Das Repository ist öffentlich — alles, was einmal committet ist, steht für immer
in der Historie. Deshalb prüft das hier bei JEDEM Testlauf auf die typischen
Zugangsdaten und auf Schlüsseldateien.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Muster, die in einem Quellbaum nichts zu suchen haben. Bewusst zusammengesetzt,
# damit die Datei sich nicht selbst als Treffer meldet.
MUSTER = {
    "GitHub-Token (fein)": "github" + "_pat_",
    "GitHub-Token (klassisch)": "ghp" + "_",
    "Google/Gemini-Key": "AIza" + "Sy",
    "Anthropic-Key": "sk-" + "ant-",
    "OpenAI-Key": "sk-" + "proj-",
}


def _dateien():
    """Alle von Git verfolgten Textdateien — nur die landen im Repository."""
    roh = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True, text=True).stdout
    for zeile in roh.splitlines():
        pfad = ROOT / zeile
        if pfad.suffix.lower() in {".png", ".ico", ".wav", ".db", ".exe"}:
            continue
        if not pfad.is_file():
            continue
        try:
            yield zeile, pfad.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


@pytest.mark.parametrize("name,muster", sorted(MUSTER.items()))
def test_keine_zugangsdaten_im_repository(name, muster):
    treffer = [d for d, inhalt in _dateien()
               if muster in inhalt and d != "tests/test_keine_geheimnisse.py"]
    assert not treffer, f"{name} gefunden in: {treffer}"


def test_keine_privaten_schluesseldateien_verfolgt():
    """Nicht nur der Inhalt — auch die Datei selbst darf nie verfolgt werden."""
    roh = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True, text=True).stdout.splitlines()
    verdaechtig = [d for d in roh
                   if d.endswith((".pem", ".key", ".p12", ".pfx")) or d == ".env"]
    assert not verdaechtig, f"Schluesseldateien im Repository: {verdaechtig}"
