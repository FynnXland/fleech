"""Die Aufteilung des Kerns — Struktur als Test, nicht als Absichtserklaerung.

Gegenstueck zu `test_ui_struktur.py`, eine Etage tiefer. Zwei Dateien waren hier
zu Sammelbecken geworden:

- `textutils.py` (898 Z.) hiess „Texthelfer", enthielt aber die Halluzinations-
  Abwehr der Pipeline. Aufgeteilt in `textfilter` (Guards) und `dictionary`
  (Woerterbuch); uebrig bleibt der Rahmen um den LLM-Call.
- `usersettings.py` (872 Z.) war Feldablage MIT einem 294-Zeilen-Block echter
  Profil-Logik darin. Der liegt jetzt in `profiles.py`.

Solche Aufteilungen halten nur, wenn etwas dagegen wacht — sonst waechst das
naechste Thema wieder dort, wo gerade Platz ist, und niemand merkt es, weil
nichts kaputtgeht.
"""

import ast
import pathlib

import pytest

KERN = pathlib.Path(__file__).resolve().parents[1] / "fleech"


def _quelle(name: str) -> str:
    return (KERN / name).read_text(encoding="utf-8")


def _zeilen(name: str) -> int:
    return len(_quelle(name).splitlines())


# -- Die Aufteilung besteht ------------------------------------------------------------


def test_die_teile_existieren():
    for name in ("textfilter.py", "dictionary.py", "profiles.py"):
        assert (KERN / name).exists(), f"{name} fehlt"


# Grosszuegig gewaehlt: Die Grenze soll nicht bei jeder Zeile anschlagen, sondern
# verhindern, dass wieder ein ganzes Thema einzieht. Wer eine reisst, erhoeht nicht
# die Zahl, sondern gibt dem neuen Thema einen eigenen Namen.
OBERGRENZEN = {
    "textutils.py": (150, "Rahmen um den LLM-Call — Guards nach textfilter.py"),
    "usersettings.py": (700, "Feldablage und Persistenz — Logik in eigene Module"),
    "textfilter.py": (800, "Qualitaets-Guards der Pipeline"),
    "pipeline.py": (1300, "Orchestrierung — Guards gehoeren nach textfilter.py"),
}


@pytest.mark.parametrize("datei", sorted(OBERGRENZEN))
def test_die_kernmodule_bleiben_schlank(datei):
    grenze, wohin = OBERGRENZEN[datei]
    n = _zeilen(datei)
    assert n < grenze, (
        f"{datei} hat {n} Zeilen (Grenze {grenze}). Gehoert der neue Code wirklich "
        f"hierher? {wohin}."
    )


# -- Die Richtung der Abhaengigkeiten stimmt -------------------------------------------


def test_profiles_kennt_die_einstellungen_nicht():
    """`usersettings` importiert `profiles`, nie umgekehrt. Ein Profil ist eine
    Regel, kein Speicherort — es darf weder Pfade noch das Schreiben kennen."""
    for k in ast.walk(ast.parse(_quelle("profiles.py"))):
        if isinstance(k, ast.ImportFrom):
            assert "usersettings" not in (k.module or ""), (
                "profiles.py importiert usersettings — damit haengen beide aneinander."
            )
            assert "platformpaths" not in (k.module or "")


def test_die_guards_kennen_kein_woerterbuch_und_umgekehrt():
    """Zwei getrennte Themen, die nur zufaellig in derselben Datei lagen. Wenn hier
    wieder ein Import entsteht, war die Trennung die falsche."""
    for a, b in (("textfilter.py", "dictionary"), ("dictionary.py", "textfilter")):
        for k in ast.walk(ast.parse(_quelle(a))):
            if isinstance(k, ast.ImportFrom):
                assert b not in (k.module or ""), f"{a} importiert {b}"


def test_der_kern_kennt_die_oberflaeche_nicht():
    """Der Grund, warum die Pipeline ohne Qt testbar ist. Einzige erlaubte Ausnahme
    ist `__main__.py` — der Starter, der die UI hochfaehrt."""
    for datei in KERN.glob("*.py"):
        if datei.name == "__main__.py":
            continue
        for k in ast.walk(ast.parse(datei.read_text(encoding="utf-8"))):
            if isinstance(k, ast.ImportFrom) and (k.module or "").startswith("ui"):
                assert False, f"{datei.name} importiert aus der Oberflaeche: {k.module}"


def test_die_pipeline_haengt_nicht_an_den_einstellungen():
    """Die Pipeline bekommt Werte gereicht, sie holt sie nicht. Deshalb steht
    REWRITING_FORMATS dort bewusst ein zweites Mal — kein Versehen, sondern der
    Preis dafuer, dass `pipeline.py` ohne settings.json laeuft."""
    for k in ast.walk(ast.parse(_quelle("pipeline.py"))):
        if isinstance(k, ast.ImportFrom):
            assert "usersettings" not in (k.module or ""), (
                "pipeline.py importiert usersettings — die Verdrahtung gehoert in "
                "pipeline_factory.py."
            )
