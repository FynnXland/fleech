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


def test_kein_name_ist_beim_verschieben_zurueckgeblieben():
    """Faengt den teuersten Fehler beim Aufteilen von Dateien.

    Beim Umzug von `_start_ipc_server` nach `desktopapp/lebenszyklus.py` blieb die
    Konstante `IPC_NAME` in `desktop.py` zurueck. Kein Test schlug an — die Methode
    laeuft nur beim echten Start —, und die App meldete den NameError still ins Log:
    „Zweitstart oeffnet kein Fenster". Genau so verschwinden Funktionen unbemerkt.

    Geprueft wird bewusst grob: Kommt ein geladener Name IRGENDWO in der Datei als
    Zuweisung, Argument, Import oder Definition vor? Das findet keine
    Scope-Fehler, aber jeden Namen, der beim Verschieben nicht mitgekommen ist —
    und genau darum geht es hier."""
    import builtins

    fehler = []
    for datei in sorted(KERN.rglob("*.py")):
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        gebunden = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
        for k in ast.walk(baum):
            if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                gebunden.add(k.name)
            elif isinstance(k, ast.Name) and isinstance(k.ctx, (ast.Store, ast.Del)):
                gebunden.add(k.id)
            elif isinstance(k, ast.arg):
                gebunden.add(k.arg)
            elif isinstance(k, (ast.Import, ast.ImportFrom)):
                for a in k.names:
                    gebunden.add((a.asname or a.name).split(".")[0])
            elif isinstance(k, (ast.Global, ast.Nonlocal)):
                gebunden.update(k.names)
            elif isinstance(k, ast.ExceptHandler) and k.name:
                gebunden.add(k.name)
        for k in ast.walk(baum):
            if isinstance(k, ast.Name) and isinstance(k.ctx, ast.Load):
                if k.id not in gebunden:
                    rel = datei.relative_to(KERN.parent).as_posix()
                    fehler.append(f"{rel}:{k.lineno} {k.id}")

    assert not fehler, "Unbekannte Namen:\n  " + "\n  ".join(sorted(set(fehler)))


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


def test_die_doppelte_formatliste_bleibt_deckungsgleich():
    """Der Preis der Entkopplung, jetzt abgesichert.

    `REWRITING_FORMATS` steht bewusst zweimal: in `pipeline.py` (die ohne
    settings.json laufen muss, siehe Test darueber) und in `profiles.py`. Bis
    5.10.0 war das nur durch einen Kommentar zusammengehalten — ein neues Format,
    das nur in `profiles.py` landet, faellt in der Pipeline lautlos auf Cleanup
    zurueck. Kein Fehler, kein Log, einfach das falsche Ergebnis.

    Der Befund stammt aus dem externen Gutachten vom 2026-08-05 und war der
    einzige der sechs Punkte, der eine echte, unbemerkte Luecke traf.
    """
    from fleech.pipeline import REWRITING_FORMATS as in_pipeline
    from fleech.profiles import REWRITING_FORMATS as in_profiles

    assert in_pipeline == in_profiles, (
        "Die beiden Kopien von REWRITING_FORMATS sind auseinandergelaufen:\n"
        f"  pipeline.py: {in_pipeline}\n"
        f"  profiles.py: {in_profiles}\n"
        "Beide Stellen pflegen — die Trennung ist Absicht, das Auseinanderlaufen nicht."
    )


def test_jedes_umformulierende_format_hat_eine_prompt_datei():
    """Ein Format ohne Prompt-Datei faellt zur Laufzeit auf Cleanup zurueck — auch
    das lautlos. Die Liste und die Dateien muessen zusammenpassen."""
    from pathlib import Path

    from fleech.pipeline import REWRITING_FORMATS

    prompts = Path(__file__).resolve().parent.parent / "prompts"
    fehlend = [f for f in REWRITING_FORMATS
               if not (prompts / f"{f}.md").is_file()
               and not (prompts / f"{f}_engineer.md").is_file()]
    assert not fehlend, f"Formate ohne Prompt-Datei in prompts/: {fehlend}"
