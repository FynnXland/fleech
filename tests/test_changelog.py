"""CHANGELOG.md ist die EINE Quelle für „was ist neu".

`release.py` zieht daraus die GitHub-Release-Notizen. Eine zweite Liste von Hand
zu pflegen hiesse, dass beide irgendwann auseinanderlaufen — und der Empfaenger
liest dann die falsche.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

from release import changelog_abschnitt          # noqa: E402

from fleech.version import APP_VERSION           # noqa: E402

CHANGELOG = ROOT / "CHANGELOG.md"


def _versionen() -> list:
    return re.findall(r"^## (\d+\.\d+\.\d+)", CHANGELOG.read_text(encoding="utf-8"),
                      re.MULTILINE)


def test_changelog_existiert_und_hat_eintraege():
    assert CHANGELOG.is_file()
    assert len(_versionen()) >= 5


def test_aktuelle_version_steht_drin():
    """Der haeufigste Fehler: Version hochgezogen, Eintrag vergessen — das Release
    ginge dann ohne Notizen raus."""
    assert APP_VERSION in _versionen(), (
        f"Kein CHANGELOG-Eintrag fuer {APP_VERSION}. Vor dem Release nachtragen.")


def test_abschnitt_endet_vor_der_naechsten_version():
    """Sonst stuende im Release der Text aller aelteren Versionen mit drin."""
    versionen = _versionen()
    text = changelog_abschnitt(versionen[0])
    assert text
    for aeltere in versionen[1:]:
        assert f"## {aeltere}" not in text


def test_abschnitt_traegt_keine_layout_reste():
    text = changelog_abschnitt(_versionen()[0])
    assert not text.startswith("#")
    assert not text.endswith("---")
    assert text == text.strip()


def test_unbekannte_version_liefert_leer_statt_falsch():
    """Lieber ein Release ohne Notizen als eines, das den Text der Vorversion
    behauptet."""
    assert changelog_abschnitt("99.99.99") == ""


def test_versionen_stehen_absteigend():
    """Neueste zuerst — wer die Datei oeffnet, will den letzten Stand sehen."""
    def sortier(v):
        return tuple(int(t) for t in v.split("."))

    versionen = _versionen()
    assert versionen == sorted(versionen, key=sortier, reverse=True)


@pytest.mark.parametrize("version", ["4.0.0", "4.4.0", "4.10.0"])
def test_wichtige_versionen_sind_beschrieben(version):
    text = changelog_abschnitt(version)
    assert len(text) > 100, f"{version} hat kaum Inhalt"


def test_notizen_enthalten_changelog_und_pruefsumme(tmp_path):
    """Die Release-Notizen tragen beides: was neu ist UND die Pruefsumme, gegen
    die der Update-Client die geladene Datei haelt."""
    from release import notizen

    datei = tmp_path / f"FleechSetup-{APP_VERSION}.exe"
    datei.write_bytes(b"x" * 2048)
    text = notizen("abc123", datei)
    assert APP_VERSION in text
    assert "SHA256: abc123" in text
    assert changelog_abschnitt().splitlines()[0][:40] in text
