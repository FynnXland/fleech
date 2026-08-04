"""Die Aufteilung des Hauptfensters — Struktur als Test, nicht als Absichtserklaerung.

`ui/main_window.py` war 2970 Zeilen lang: vier Seiten, vier Dialoge, funfzehn
Widgets und das Fenstergeruest in einer Datei. Aufgeteilt in `theme` (Farben),
`widgets` (Bausteine), `dialogs` und `pages/`.

Solche Aufteilungen halten nur, wenn etwas dagegen wacht. Ohne Test waechst die
naechste Seite wieder dort, wo gerade Platz ist — und niemand merkt es, weil
nichts kaputtgeht.
"""

import ast
import pathlib

import pytest

UI = pathlib.Path(__file__).resolve().parents[1] / "fleech" / "ui"


def _baum(pfad: pathlib.Path) -> ast.Module:
    return ast.parse(pfad.read_text(encoding="utf-8"))


def _zeilen(pfad: pathlib.Path) -> int:
    return len(pfad.read_text(encoding="utf-8").splitlines())


# -- Die Aufteilung besteht ------------------------------------------------------------


def test_die_teile_existieren():
    for name in ("theme.py", "widgets.py", "dialogs.py"):
        assert (UI / name).exists(), f"{name} fehlt"
    for name in ("home.py", "insights.py", "apps.py", "profiles.py"):
        assert (UI / "pages" / name).exists(), f"pages/{name} fehlt"


def test_das_fenster_bleibt_schlank():
    """Die Zahl ist grosszuegig gewaehlt — sie soll nicht bei jeder Zeile
    anschlagen, sondern verhindern, dass wieder eine Seite hier einzieht."""
    n = _zeilen(UI / "main_window.py")
    assert n < 500, (
        f"main_window.py hat {n} Zeilen. Gehoert der neue Code wirklich ins "
        f"Fenstergeruest, oder in pages/ bzw. widgets.py?"
    )


def test_nur_das_fenstergeruest_liegt_im_hauptfenster():
    """Klassen, die keine Seite und kein Fenster sind, gehoeren woandershin."""
    klassen = [k.name for k in _baum(UI / "main_window.py").body
               if isinstance(k, ast.ClassDef)]
    assert klassen == ["MainWindow"], f"Unerwartete Klassen: {klassen}"


# -- Die Richtung der Abhaengigkeiten stimmt -------------------------------------------


def test_theme_haengt_an_nichts_aus_der_app():
    """Der Grund fuer den ganzen Umbau: Vorher zogen sechs Module ihre Farben aus
    `main_window` — `updatedialog` importierte das Hauptfenster, nur um CARD zu
    kennen. Damit lag halb die Oberflaeche an der Wurzel des Abhaengigkeitsbaums.

    `theme` darf deshalb NICHTS aus fleech importieren. Sonst faengt es wieder an."""
    for k in ast.walk(_baum(UI / "theme.py")):
        if isinstance(k, ast.ImportFrom):
            assert not k.level, f"theme.py importiert relativ: {ast.dump(k)[:60]}"
            assert not (k.module or "").startswith("fleech")


@pytest.mark.parametrize("modul", [
    "licensedialog.py", "onboarding.py", "profilepicker.py", "setuppage.py",
    "updatedialog.py", "settings_window.py",
])
def test_kein_dialog_haengt_mehr_am_hauptfenster(modul):
    quelle = (UI / modul).read_text(encoding="utf-8")
    assert "from .main_window import" not in quelle, (
        f"{modul} zieht wieder aus main_window — die Farben stehen in theme.py, "
        f"die Bausteine in widgets.py."
    )


def test_seiten_kennen_das_hauptfenster_nicht():
    """Eine Seite, die ihr Fenster kennt, ist keine Seite mehr — und der naechste
    Zyklus im Importgraph ist nur eine Zeile entfernt."""
    for datei in (UI / "pages").glob("*.py"):
        quelle = datei.read_text(encoding="utf-8")
        assert "main_window" not in quelle, f"pages/{datei.name} nennt main_window"


def test_keine_importzyklen_in_der_oberflaeche():
    import collections

    graph = collections.defaultdict(set)
    dateien = list(UI.rglob("*.py"))
    namen = {f: f.relative_to(UI.parent.parent).with_suffix("").as_posix().replace("/", ".")
             for f in dateien}

    for f in dateien:
        quelle = namen[f]
        paket = ".".join(quelle.split(".")[:-1])
        for k in ast.walk(_baum(f)):
            if not isinstance(k, ast.ImportFrom) or not k.level:
                continue
            teile = paket.split(".")
            stamm = ".".join(teile[:len(teile) - (k.level - 1)]) if k.level > 1 else paket
            ziel = f"{stamm}.{k.module}" if k.module else stamm
            if ziel in namen.values() and ziel != quelle:
                graph[quelle].add(ziel)

    def zyklus(knoten, pfad):
        for n in graph.get(knoten, ()):
            if n in pfad:
                return pfad[pfad.index(n):] + [n]
            if (gefunden := zyklus(n, pfad + [n])):
                return gefunden
        return None

    for start in graph:
        assert not (z := zyklus(start, [start])), f"Importzyklus: {' -> '.join(z)}"


# -- Was von aussen erreichbar war, bleibt erreichbar ----------------------------------


@pytest.mark.parametrize("name", [
    # Seiten und Fenster
    "MainWindow", "HomePage", "InsightsPage", "AppsPage", "ProfilesPage",
    # Dialoge — desktop.py und Tests holen sie hier ab
    "DictionarySuggestionDialog", "PromptDialog", "TranscriptDetailDialog",
    "WordDetailDialog",
    # Widgets und Helfer, die Tests direkt importieren
    "HistoryEntryRow", "UsageBar", "WpmGauge", "StreakCalendar", "HelpBadge",
    "_dauer", "_diktierzeit_text", "_passt",
    # Farben und Buttons
    "ACCENT", "ACCENT_DIM", "CARD", "TEXT", "MUTED", "style_button", "button_qss",
])
def test_alter_importweg_funktioniert_weiter(name):
    """Aufraeumen darf nichts brechen, was heute laeuft. Diese Namen wurden vor
    der Aufteilung aus `main_window` gezogen — von Tests, von `desktop.py`, von
    `docs/_briefing_shots.py`. Sie bleiben dort erreichbar."""
    import fleech.ui.main_window as mw

    assert hasattr(mw, name), f"{name} ist aus main_window verschwunden"


def test_die_farben_sind_ueberall_dieselben():
    """Re-Export heisst dasselbe Objekt, nicht eine zweite Kopie mit eigenem Wert
    — sonst driften Fenster und Dialoge irgendwann farblich auseinander."""
    from fleech.ui import main_window as mw
    from fleech.ui import theme

    for name in ("ACCENT", "CARD", "TEXT", "MUTED", "SIDEBAR", "BORDER_HAIRLINE"):
        assert getattr(mw, name) is getattr(theme, name)


# -- Keine neuen Monsterfunktionen -----------------------------------------------------

# Was heute schon laenger ist als die Grenze. Die Liste ist bewusst kurz und
# bewusst sichtbar: Sie ist die Arbeitsliste, nicht der Freibrief. Wer hier etwas
# ergaenzt, sollte einen Grund haben — wer etwas streicht, hat aufgeraeumt.
LANGE_ALTLASTEN = {
    ("fleech/ui/pages/profiles.py", "__init__"),   # 276 Z. — naechster Kandidat
}
GRENZE = 200


def test_keine_funktion_waechst_ins_unermessliche():
    """`_build_pages` hatte 674 Zeilen — mehr als die halbe Klasse in einer
    Funktion. Zerlegt in neun Methoden, eine je Einstellungsseite.

    Die Grenze steht bei 200 und nicht hoeher, weil eine Grenze, die nichts
    faengt, auch nichts schuetzt."""
    import ast as _ast

    zu_lang = []
    for datei in (UI.parent).rglob("*.py"):
        rel = datei.relative_to(UI.parent.parent).as_posix()
        for k in _ast.walk(_baum(datei)):
            if not isinstance(k, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                continue
            n = k.end_lineno - k.lineno + 1
            if n > GRENZE and (rel, k.name) not in LANGE_ALTLASTEN:
                zu_lang.append(f"{rel}:{k.lineno} {k.name} ({n} Zeilen)")

    assert not zu_lang, "Zu lange Funktionen:\n  " + "\n  ".join(zu_lang)


def test_die_einstellungsseiten_sind_je_ein_modul():
    """Eine Seite, ein Modul in `ui/settings/` — und jedes bietet `build(panel)`.

    Bis 5.6.0 war je Seite eine Methode in settings_window.py; die Datei kam damit
    auf 1379 Zeilen. Der Test prueft weiter dasselbe: dass keine Seite ohne eigenen
    Ort dazukommt und die Navigation nicht mehr Eintraege hat als es Seiten gibt."""
    from fleech.ui import settings as seiten
    from fleech.ui.settings_window import SettingsPanel

    assert len(seiten.SEITEN) == len(SettingsPanel.PAGES), (
        f"{len(SettingsPanel.PAGES)} Eintraege in der Navigation, aber "
        f"{len(seiten.SEITEN)} Seitenmodule"
    )
    ohne_build = [m.__name__ for m in seiten.SEITEN if not callable(getattr(m, "build", None))]
    assert not ohne_build, f"Seitenmodule ohne build(panel): {ohne_build}"


def test_alle_neun_seiten_werden_wirklich_gebaut(qapp, tmp_path, monkeypatch):
    """Die Zerlegung darf keine Seite verschlucken — eine vergessene Zeile in
    `_build_pages` faellt sonst erst auf, wenn jemand die Seite sucht."""
    import fleech.usersettings as us

    monkeypatch.setattr(us, "SETTINGS_PATH", tmp_path / "settings.json")
    from fleech.ui.settings_window import SettingsPanel
    from fleech.usersettings import UserSettings

    panel = SettingsPanel(UserSettings(), lambda s: None, lambda: ["Mikrofon A"])
    assert panel._pages.count() == len(SettingsPanel.PAGES)
    for idx in range(panel._pages.count()):
        seite = panel._pages.widget(idx)
        assert seite is not None
        # Eine leer gebliebene Seite haette keine Kind-Widgets
        assert seite.findChildren(object), f"Seite {SettingsPanel.PAGES[idx]} ist leer"
