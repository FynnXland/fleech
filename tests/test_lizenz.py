"""Lizenz: Fleech steht unter MIT (seit 6.2.0).

Wacht darueber, dass der Lizenztext da ist und ins Paket kommt, und dass keine
Datei des Repositorys mehr eine fruehere Lizenz von Fleech nennt. Fremdbibliotheken
mit eigener Lizenz stehen in THIRD-PARTY-NOTICES.md und sind davon ausgenommen.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Zusammengesetzt, damit dieser Test sich nicht selbst findet.
# Apache wird nur als Lizenzdatei von Fleech gesucht — Fremdmodelle unter Apache
# (Voxtral in docs/stt-vergleich.md) duerfen weiter so beschrieben werden.
VERBOTEN = ("General " + "Public License", "GPL-" + "3", "GNU " + "GPL",
            "LICENSE-" + "APACHE", "LICENSE-" + "MIT")
AUSGENOMMEN = {"THIRD-PARTY-NOTICES.md", "tests/test_lizenz.py"}


def test_mit_lizenz_liegt_bei():
    mit = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert mit.startswith("MIT License") and "FynnXland" in mit
    assert not (ROOT / "LICENSE-APACHE").exists()


def test_lizenz_und_hinweise_kommen_ins_paket():
    spec = (ROOT / "packaging" / "fleech.spec").read_text(encoding="utf-8")
    for name in ("LICENSE", "THIRD-PARTY-NOTICES.md"):
        assert f'"{name}"' in spec, f"{name} fehlt im Paket"


def test_readmes_nennen_die_mit_lizenz():
    for datei in ("README.md", "README.de.md"):
        text = (ROOT / datei).read_text(encoding="utf-8")
        assert "MIT" in text and "(LICENSE)" in text, datei


def test_keine_datei_nennt_die_fruehere_lizenz():
    roh = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.splitlines()
    treffer = []
    for rel in roh:
        if rel in AUSGENOMMEN or not (ROOT / rel).is_file():
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue                     # Binaerdateien (Bilder, Icons)
        if any(v in text for v in VERBOTEN):
            treffer.append(rel)
    assert not treffer, f"Fruehere Lizenz noch erwaehnt in: {treffer}"
