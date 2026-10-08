"""Die READMEs und die Doku: Links, Bilder und beide Sprachfassungen.

README.md (englisch, Startseite auf GitHub) und README.de.md erzählen dasselbe in
derselben Reihenfolge mit denselben Bildern. Läuft eine Fassung der anderen davon,
merkt das niemand beim Lesen der eigenen Sprache — deshalb wacht dieser Test darüber.
Dazu: Jeder lokale Link und jedes Bild in den öffentlichen Markdown-Dateien muss auf
eine vorhandene Datei zeigen. Ein toter Link ist auf GitHub der erste Eindruck.
"""

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parent.parent
README_EN = ROOT / "README.md"
README_DE = ROOT / "README.de.md"

# Dateien, deren lokale Links geprüft werden. Fehlt eine (noch), wird sie
# übersprungen statt zu scheitern.
GEPRUEFT = ["README.md", "README.de.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md",
            "THIRD-PARTY-NOTICES.md", "docs/media/README.md", "tests/fixtures/README.md",
            ".github/PULL_REQUEST_TEMPLATE.md"] + sorted(
    p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").glob("*.md"))

# Ziel eines Markdown-Links/-Bilds `](ziel)` oder `](ziel "Titel")`,
# einer Referenz `[name]: ziel` und der HTML-Attribute src/href.
_MD_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_MD_REF = re.compile(r"^\s*\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+\"[^\"]*\")?\s*$", re.MULTILINE)
_HTML_ATTR = re.compile(r"\b(?:src|href)\s*=\s*\"([^\"]+)\"", re.IGNORECASE)
_EXTERN = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)   # https:, mailto: …


def _ohne_code(text: str) -> str:
    """Code-Blöcke und Inline-Code entfernen — dort stehen Beispiele, keine Links."""
    text = re.sub(r"^(```|~~~).*?^\1[^\n]*$", "", text, flags=re.MULTILINE | re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", text)


def _ziele(text: str) -> list:
    text = _ohne_code(text)
    return (_MD_LINK.findall(text) + _MD_REF.findall(text)
            + _HTML_ATTR.findall(text))


def _lokale_ziele(text: str) -> list:
    """Nur Dateiziele: ohne externe Adressen, ohne reine Sprungmarken."""
    ergebnis = []
    for ziel in _ziele(text):
        if _EXTERN.match(ziel) or ziel.startswith("#"):
            continue
        ziel = unquote(ziel.split("#", 1)[0].split("?", 1)[0])
        if ziel:
            ergebnis.append(ziel)
    return ergebnis


def _medien(text: str) -> set:
    """Verwendete Dateien aus docs/media, ohne Sprachkennung (.en./.de.)."""
    return {re.sub(r"\.(en|de)\.", ".", z) for z in _lokale_ziele(text)
            if z.lstrip("./").startswith("docs/media/")}


def _abschnitte(text: str) -> list:
    return re.findall(r"^## (.+)$", _ohne_code(text), re.MULTILINE)


def _anker(text: str) -> set:
    """Sprungmarken, wie GitHub sie aus Überschriften bildet: klein, Satzzeichen
    weg (Buchstaben mit Umlaut bleiben), Leerzeichen → Bindestrich, Dubletten
    mit -1, -2 …"""
    gesehen: dict = {}
    anker = set()
    for titel in re.findall(r"^#{1,6} +(.+?) *#*$", _ohne_code(text), re.MULTILINE):
        slug = re.sub(r"[^\w\- ]", "", titel.strip().lower()).replace(" ", "-")
        n = gesehen.get(slug, 0)
        gesehen[slug] = n + 1
        anker.add(slug if n == 0 else f"{slug}-{n}")
    return anker


def _lesen(pfad: Path) -> str:
    return pfad.read_text(encoding="utf-8")


def test_beide_readmes_haben_gleich_viele_abschnitte():
    en, de = _abschnitte(_lesen(README_EN)), _abschnitte(_lesen(README_DE))
    assert len(en) >= 5
    assert len(en) == len(de), (
        f"README.md hat {len(en)} Abschnitte, README.de.md {len(de)}.\n"
        f"EN: {en}\nDE: {de}")


@pytest.mark.parametrize("datei", GEPRUEFT)
def test_lokale_links_zeigen_auf_vorhandene_dateien(datei):
    pfad = ROOT / datei
    if not pfad.is_file():
        pytest.skip(f"{datei} gibt es (noch) nicht")
    tot = []
    for ziel in _lokale_ziele(_lesen(pfad)):
        basis = ROOT if ziel.startswith("/") else pfad.parent
        if not (basis / ziel.lstrip("/")).exists():
            tot.append(ziel)
    assert not tot, f"Tote lokale Links in {datei}: {tot}"


def test_readmes_zeigen_dieselben_medien():
    en, de = _medien(_lesen(README_EN)), _medien(_lesen(README_DE))
    assert en, "README.md zeigt kein einziges Bild aus docs/media"
    assert en == de, (f"Nur in README.md: {sorted(en - de)}; "
                      f"nur in README.de.md: {sorted(de - en)}")


def test_readmes_nutzen_ihre_sprachfassung():
    """Gibt es ein Bild in zwei Sprachen, zeigt jede README ihre eigene."""
    for pfad, fremd in ((README_EN, ".de."), (README_DE, ".en.")):
        falsch = [z for z in _lokale_ziele(_lesen(pfad))
                  if z.startswith("docs/media/") and fremd in z]
        assert not falsch, f"{pfad.name} zeigt die andere Sprachfassung: {falsch}"


@pytest.mark.parametrize("pfad", [README_EN, README_DE], ids=lambda p: p.name)
def test_sprungmarken_in_den_readmes_gibt_es(pfad):
    text = _lesen(pfad)
    vorhanden = _anker(text)
    fehlend = [z for z in _ziele(text)
               if z.startswith("#") and unquote(z[1:]).lower() not in vorhanden]
    assert not fehlend, f"{pfad.name}: Sprungmarken ohne Überschrift: {fehlend}"


@pytest.mark.parametrize("pfad", [README_EN, README_DE], ids=lambda p: p.name)
def test_keine_steuerzeichen_in_den_readmes(pfad):
    """Ein Skript, das `\\f` aus „…\\Fleech\\fleech.log" macht, hinterlässt einen
    Seitenvorschub statt eines Backslashs — im Editor unsichtbar, auf GitHub kaputt."""
    text = _lesen(pfad)
    falsch = sorted({hex(ord(z)) for z in text if ord(z) < 32 and z not in "\n\r\t"})
    assert not falsch, f"{pfad.name} enthält Steuerzeichen: {falsch}"


def test_kein_verweis_auf_den_alten_bilderordner():
    """docs/bilder heißt seit 6.x docs/media — ein alter Pfad wäre ein totes Bild."""
    roh = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    alt = "docs/" + "bilder"
    treffer = [rel for rel in roh
               if (ROOT / rel).is_file() and alt in _lesen(ROOT / rel)]
    assert not treffer, f"Verweis auf {alt} in: {treffer}"
