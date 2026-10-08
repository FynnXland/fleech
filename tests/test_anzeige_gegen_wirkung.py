"""Anzeige = Wirkung: Was die Oberflaeche verspricht, muss der Code auch tun.

Die Tiefenanalyse vom 08/2026 hat als groesste zusammenhaengende Fehlerfamilie
nicht Abstuerze gefunden, sondern Stellen, an denen Fleech etwas ANZEIGT, das es
nicht tut: ein Ausgabeformat, das die Pipeline nie erreicht (E-3), eine
Formel-Erkennung, die „Automatisch" meldet und aus ist (A-1), ein Schalter, der
gespeichert und nie gelesen wird (B-6). Solche Fehler sind teuer, weil kein Test
und kein Log sie meldet — das Ergebnis ist einfach das falsche.

Diese Datei ist der Wachhund dagegen. Sie prueft keine Optik und kein Verhalten
im Einzelfall (das tun die Tests bei den jeweiligen Modulen), sondern die
Verbindung: Jedes Bedienelement muss irgendwo gelesen werden, jedes angebotene
Format muss einen Weg haben, und die Anzeige der Formel-Stufe muss aus denselben
Feldern kommen wie die Pipeline-Verdrahtung.
"""

import ast
import dataclasses
import pathlib

import pytest

KERN = pathlib.Path(__file__).resolve().parents[1] / "fleech"
SEITEN = KERN / "ui" / "settings"


def _baum(datei: pathlib.Path):
    return ast.parse(datei.read_text(encoding="utf-8"))


# -- (a) Jedes Bedienelement schreibt in ein Feld, das jemand liest --------------------


def _settings_feldnamen() -> set:
    """Alle Feldnamen der Einstellungs-Abschnitte (general, recording, …)."""
    from fleech.usersettings import UserSettings

    namen = set()
    s = UserSettings()
    for feld in dataclasses.fields(s):
        abschnitt = getattr(s, feld.name)
        if dataclasses.is_dataclass(abschnitt):
            namen.update(g.name for g in dataclasses.fields(abschnitt))
    return namen


def _in_den_seiten_geschrieben() -> set:
    """{(Seitendatei, Feldname)} — was die Einstellungsseiten setzen.

    Erfasst `setattr(s.abschnitt, "feld", …)` (das uebliche Muster der
    Widget-Bauer) und direkte Zuweisungen. Ein Setter, der den Feldnamen aus
    einer Variablen zieht (`setattr(s.sounds, k, v)` in sounds.py), faellt
    bewusst durch — dort ist der Name zur Analysezeit nicht bekannt."""
    felder = _settings_feldnamen()
    treffer = set()
    for datei in sorted(SEITEN.glob("*.py")):
        for k in ast.walk(_baum(datei)):
            if (isinstance(k, ast.Call) and isinstance(k.func, ast.Name)
                    and k.func.id == "setattr" and len(k.args) >= 2
                    and isinstance(k.args[1], ast.Constant)
                    and k.args[1].value in felder):
                treffer.add((datei.name, k.args[1].value))
            elif isinstance(k, ast.Assign):
                for ziel in k.targets:
                    if isinstance(ziel, ast.Attribute) and ziel.attr in felder:
                        treffer.add((datei.name, ziel.attr))
    return treffer


def _anderswo_gelesen() -> set:
    """Feldnamen, die IRGENDWO ausserhalb der Einstellungsseiten und der
    Feldablage gelesen werden — als Attribut-Zugriff oder ueber getattr/hasattr.

    Bewusst grob (nur der Name, nicht der Abschnitt): Diese Pruefung soll das
    tote Feld finden, das nirgends vorkommt, und nicht bei jedem gleichnamigen
    Attribut Alarm schlagen. Genau so arbeitet auch
    `test_kernstruktur.test_kein_name_ist_beim_verschieben_zurueckgeblieben`."""
    gefunden = set()
    for datei in sorted(KERN.rglob("*.py")):
        if datei.parent == SEITEN or datei.name == "usersettings.py":
            continue
        for k in ast.walk(_baum(datei)):
            if isinstance(k, ast.Attribute) and isinstance(k.ctx, ast.Load):
                gefunden.add(k.attr)
            elif (isinstance(k, ast.Call) and isinstance(k.func, ast.Name)
                    and k.func.id in ("getattr", "hasattr") and len(k.args) >= 2
                    and isinstance(k.args[1], ast.Constant)):
                gefunden.add(k.args[1].value)
    return gefunden


# Felder, die absichtlich nur gespeichert werden. Jeder Eintrag braucht eine
# Begruendung — „faellt sonst durch" ist keine.
NUR_GESPEICHERT = {
    # (Feldname, Grund)
    ("hinweis_text", "Die Anzeige IST hier die Wirkung: der Satz des Modellberaters, "
                     "warum ein neueres Modell vorgeschlagen wird. Geschrieben vom "
                     "Wochen-Check (desktopapp/modellpruefung.py) und von „Jetzt "
                     "prüfen“, gelesen nur von der KI-Seite, die ihn zeigt."),
}


def test_jedes_bedienelement_schreibt_in_ein_gelesenes_feld():
    """Befund B-6: „Debug-Logging" wurde gespeichert und projektweit nie gelesen —
    der Tooltip versprach ein ausfuehrliches Protokoll, das nie entstand. Genau
    diese Klasse Fehler ist von aussen unsichtbar: Der Haken bleibt gesetzt, die
    Datei wird geschrieben, und nichts passiert.

    Reisst dieser Test, gibt es zwei ehrliche Antworten: das Feld anschliessen
    oder das Bedienelement entfernen. Eine dritte (Ausnahme eintragen) gibt es
    nur mit Begruendung im Katalog oben."""
    gelesen = _anderswo_gelesen()
    ausnahmen = {name for name, _grund in NUR_GESPEICHERT}
    tot = sorted(f"{datei}: {name}"
                 for datei, name in _in_den_seiten_geschrieben()
                 if name not in gelesen and name not in ausnahmen)
    assert not tot, (
        "Einstellungen, die geschrieben und nirgends gelesen werden:\n  "
        + "\n  ".join(tot)
        + "\nEntweder anschliessen oder das Bedienelement entfernen."
    )


def test_der_debug_schalter_wirkt_wirklich_auf_das_protokoll():
    """Die Gegenprobe zum Test darueber am konkreten Fall (B-6): Der Haken muss
    beim Start den Log-Level anheben, sonst ist er wieder nur Zierde."""
    quelle = (KERN / "__main__.py").read_text(encoding="utf-8")
    assert "debug_logging" in quelle
    assert "setLevel(logging.DEBUG)" in quelle


# -- (b) Jedes angebotene Ausgabeformat hat einen Weg ---------------------------------


def test_jedes_angebotene_profilformat_erreicht_die_pipeline():
    """Befunde E-3 und E-14: `PROFILE_FORMATS` bot Formate an, die kein Codepfad
    auswertete — „Stichpunkte" fiel in `desktop.py` aus der Whitelist, „Formeln"
    hatte seit v3.0.0 ueberhaupt keinen Modus mehr. Beide waren auf der
    Profilseite waehlbar, farbig markiert und mit Prompt-Knopf beworben.

    Wer hier ein Format ergaenzt, ergaenzt es in `REWRITING_FORMATS` mit — oder
    er bietet dem Nutzer wieder etwas an, das nichts tut."""
    from fleech.profiles import PROFILE_FORMATS, REWRITING_FORMATS

    werte = [v for v, _label in PROFILE_FORMATS]
    assert werte[0] == ""                     # „Diktat (Standard)" = kein Format
    ohne_weg = [v for v in werte[1:] if v not in REWRITING_FORMATS]
    assert not ohne_weg, (
        f"Ausgabeformate ohne Wirkung: {ohne_weg}. Entweder in REWRITING_FORMATS "
        "aufnehmen (mit Prompt-Datei) oder aus der Auswahl nehmen."
    )


def test_die_dritte_kopie_der_formatliste_ist_verschwunden():
    """`desktop.py` fuehrte die Formate ein drittes Mal als hartes Tupel — daran
    ist E-3 gestorben. Der Filter muss aus der gemeinsamen Liste kommen."""
    zuweisungen = [k for k in ast.walk(_baum(KERN / "ui" / "desktop.py"))
                   if isinstance(k, ast.Assign)
                   and any(isinstance(z, ast.Name) and z.id == "output_format"
                           for z in k.targets)]
    assert zuweisungen, "desktop.py setzt kein output_format mehr — Test nachziehen."
    for k in zuweisungen:
        assert "REWRITING_FORMATS" in ast.dump(k.value), (
            "Das Ausgabeformat wird wieder gegen eine eigene Liste geprueft — "
            "genau daran ist E-3 gestorben."
        )


# -- (c) Formel-Anzeige und Formel-Wirkung fragen dieselben Felder --------------------


def _auto_latex_ausdruck():
    """Der Ausdruck, mit dem `pipeline_factory` `pipeline.auto_latex` setzt —
    aus dem Quelltext geholt, damit dieser Test nicht seine eigene Kopie pflegt."""
    for k in ast.walk(_baum(KERN / "pipeline_factory.py")):
        if isinstance(k, ast.Assign) and len(k.targets) == 1:
            ziel = k.targets[0]
            if isinstance(ziel, ast.Attribute) and ziel.attr == "auto_latex":
                return compile(ast.Expression(k.value), "<pipeline_factory>", "eval")
    raise AssertionError("pipeline_factory.py setzt pipeline.auto_latex nicht mehr — "
                         "dann muss dieser Test der neuen Stelle folgen.")


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("auto_latex", [True, False])
def test_die_formel_stufe_zeigt_was_die_pipeline_tut(enabled, auto_latex):
    """Befund A-1: `math_level` las nur `enabled`, wirksam war `auto_latex`.
    Vorgabe ist `enabled=True, auto_latex=False` — eine frische Installation
    zeigte also „Automatisch" und erkannte nie eine Formel.

    Geprueft wird gegen den ECHTEN Ausdruck aus `pipeline_factory` (ohne Modelle
    zu laden): Die Stufe steht genau dann auf „auto", wenn die Pipeline auch
    Formeln uebersetzen wuerde."""
    from fleech.usersettings import UserSettings, math_level

    s = UserSettings()
    s.math.enabled, s.math.auto_latex = enabled, auto_latex
    wirkung = bool(eval(_auto_latex_ausdruck(), {"settings": s}))
    assert (math_level(s.math) == "auto") is wirkung


def test_die_stufe_schaltet_die_pipeline_wirklich_um():
    """Und die Gegenrichtung: Was der Regler setzt, muss die Pipeline sehen."""
    from fleech.usersettings import UserSettings, apply_math_level, math_level

    s = UserSettings()
    for stufe in ("auto", "off"):
        apply_math_level(s.math, stufe)
        assert math_level(s.math) == stufe
        wirkung = bool(eval(_auto_latex_ausdruck(), {"settings": s}))
        assert wirkung is (stufe == "auto")
