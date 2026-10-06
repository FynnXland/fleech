"""Farbe je Profil — waehlbar, und jedes Profil hat eine.

Vorher trugen nur die vier Format-Profile einen Punkt in der Liste; alle anderen
blieben farblos, was aussah, als fehle dort etwas. Jetzt hat jedes Profil eine
Farbe, sichtbar in der Liste UND am Punkt der Pille.
"""

import pytest

from fleech.profiles import PROFIL_FARBEN, profile_color

FARBEN = {f for f, _ in PROFIL_FARBEN}


# -- Jedes Profil bekommt eine Farbe ---------------------------------------------------


@pytest.mark.parametrize("profil", [
    {"name": "Standard", "default": True},
    {"name": "Coding"},
    {"name": "Privat", "mode": ""},
    {"name": "Irgendwas", "color": ""},
    {"name": ""},
    {},
])
def test_niemals_ohne_farbe(profil):
    """Der Kern des Wunsches: kein Profil ohne Punkt."""
    assert profile_color(profil) in FARBEN


def test_kaputte_eingabe_liefert_trotzdem_eine_farbe():
    """Die Profilliste kommt aus settings.json — dort kann alles stehen."""
    for murks in (None, "Text statt Dict", 42, []):
        assert profile_color(murks) in FARBEN


# -- Die Reihenfolge der drei Stufen ---------------------------------------------------


def test_selbst_gewaehlt_schlaegt_alles():
    profil = {"name": "E-Mail", "mode": "email", "color": "#E08585"}
    assert profile_color(profil) == "#E08585"


def test_ohne_wahl_gilt_die_formatfarbe():
    """Wer nie eine Farbe waehlt, soll vom Umbau nichts merken — die
    Format-Profile sehen aus wie vorher."""
    assert profile_color({"name": "KI-Prompt", "mode": "prompt"}) == "#E8A13C"
    assert profile_color({"name": "E-Mail", "mode": "email"}) == "#6E86C8"
    assert profile_color({"name": "Stichpunkte", "mode": "summary"}) == "#7FD1A6"


def test_ein_frueheres_formel_profil_behaelt_sein_violett():
    """„Formeln" ist seit Befund E-14 kein Ausgabeformat mehr — es hat nie etwas
    bewirkt. Damit das Profil in der Liste trotzdem aussieht wie bisher,
    schreibt die Migration ihm die alte Format-Farbe fest."""
    from fleech.profiles import ensure_default_profile

    alt = {"name": "Mathe", "intervention": "standard", "mode": "math"}
    ensure_default_profile([{"name": "Standard", "default": True}, alt])
    assert "mode" not in alt                    # der wirkungslose Slot ist weg
    assert alt["intervention"] == "standard"    # der Eingriffsgrad bleibt
    assert profile_color(alt) == "#AA78F0"


def test_unbekannte_farbe_wird_nicht_uebernommen():
    """Ein Wert ausserhalb der Palette waere auf dem dunklen Grund womoeglich
    unsichtbar oder grell — dann lieber die Vorgabe."""
    profil = {"name": "Coding", "color": "#000000"}
    assert profile_color(profil) in FARBEN
    assert profile_color(profil) != "#000000"


# -- Stabilitaet: der Punkt muss Wiedererkennung sein, nicht Rauschen ------------------


def test_gleicher_name_gleiche_farbe():
    assert profile_color({"name": "Coding"}) == profile_color({"name": "Coding"})


def test_umsortieren_faerbt_nicht_um():
    """Deshalb aus dem Namen und NICHT aus der Listenposition: Wer ein Profil
    nach oben schiebt, will keine neue Farbe."""
    liste = [{"name": "Coding"}, {"name": "Privat"}, {"name": "Notizen"}]
    vorher = [profile_color(p) for p in liste]
    nachher = [profile_color(p) for p in reversed(liste)]
    assert nachher == list(reversed(vorher))


def test_namensfarbe_sieht_nicht_aus_wie_ein_format():
    """Sonst haelt man ein beliebiges Profil fuer ein E-Mail- oder Formel-Profil."""
    formatfarben = {"#AA78F0", "#E8A13C", "#6E86C8", "#7FD1A6"}
    for name in ("Coding", "Privat", "Notizen", "Uni", "Journal", "Chat", "x"):
        assert profile_color({"name": name}) not in formatfarben


def test_die_palette_ist_brauchbar():
    farben, namen = zip(*PROFIL_FARBEN)
    assert len(set(farben)) == len(farben), "doppelte Farbe in der Palette"
    assert len(set(namen)) == len(namen), "doppelter Name in der Palette"
    assert all(f.startswith("#") and len(f) == 7 for f in farben)
    # Genug fuer Unterscheidbarkeit, wenig genug fuer eine Reihe in der Spalte
    assert 6 <= len(farben) <= 10


def test_die_akzentfarbe_ist_nicht_waehlbar():
    """#35C0D8 steht im ganzen Programm fuer „ausgewaehlt". Als Profilfarbe
    gelesen wirkt ein Punkt darin wie eine Markierung — bei den Format-Farben
    wurde genau das schon einmal gemeldet, deshalb steht die Begruendung dort im
    Code. Sie ist zusaetzlich die Farbe des Freihand-Rings an der Pille: Ein
    tuerkises Profil haette dort zwei fast gleiche Ringe ergeben.

    Dieser Test existiert, weil ich die Farbe beim ersten Entwurf genau so in die
    Palette geschrieben hatte."""
    from fleech.ui.theme import ACCENT

    assert ACCENT.upper() not in {f.upper() for f, _ in PROFIL_FARBEN}
    for name in ("Coding", "Privat", "Notizen", "Uni", "Journal", "Chat", "x", ""):
        assert profile_color({"name": name}).upper() != ACCENT.upper()


def test_farbe_ueberlebt_das_speichern(tmp_path, monkeypatch):
    """Additive Migration: `color` ist ein neues Feld — alte settings.json muessen
    weiterlaufen, neue duerfen nichts verlieren."""
    import fleech.usersettings as us

    pfad = tmp_path / "settings.json"
    monkeypatch.setattr(us, "SETTINGS_PATH", pfad)

    s = us.UserSettings()
    s.profiles.items = [{"name": "Coding", "color": "#D982C0", "apps": []}]
    s.save(pfad)

    geladen = us.UserSettings.load(pfad)
    assert geladen.profiles.items[0]["color"] == "#D982C0"
    assert profile_color(geladen.profiles.items[0]) == "#D982C0"


def test_alte_profile_ohne_farbfeld_laufen_weiter():
    """Eine settings.json von vor dem Update hat kein `color` — das darf nichts
    brechen und muss dieselbe Optik ergeben wie vorher."""
    alt = {"name": "Geschäftlich", "intervention": "strong", "tags": ["sachlich"],
           "apps": ["WINWORD.EXE"], "mode": "email"}
    assert profile_color(alt) == "#6E86C8"


# -- Der Punkt in der Pille --------------------------------------------------------------


def test_der_punkt_nimmt_die_profilfarbe_an(qapp):
    from fleech.ui.overlay_qt import _StatusDot

    dot = _StatusDot()
    assert dot._profil_farbe == ""
    dot.set_profile_color("#D982C0")
    assert dot._profil_farbe == "#D982C0"


def test_ohne_profil_bleibt_der_punkt_wie_frueher(qapp):
    """Wer keine Profile nutzt, soll keinen bunten Ring bekommen, der etwas
    ankuendigt, das es bei ihm gar nicht gibt."""
    from fleech.ui.overlay_qt import _StatusDot

    dot = _StatusDot()
    dot.set_profile_color("")
    assert dot._profil_farbe == ""


def test_farbe_und_eingerastet_bleiben_unterscheidbar(qapp):
    """Der Kern des Entwurfs: Ring = welches Profil, Fuellung = eingerastet.

    Beide auf die Fuellung zu legen haette die zweite Aussage geloescht — man
    haette nicht mehr gesehen, ob KI-Prompting aktiv ist oder nur ein buntes
    Profil gilt. Deshalb rendern die Zustaende unterschiedlich."""
    from PySide6.QtGui import QPixmap
    from fleech.ui.overlay_qt import _StatusDot

    def bild(farbe: str, modus: str) -> bytes:
        dot = _StatusDot()
        dot.resize(28, 28)
        dot.set_profile_color(farbe)
        dot.set_mode(modus)
        pm: QPixmap = dot.grab()
        return pm.toImage().bits().tobytes()

    ruhe_ohne = bild("", "")
    ruhe_mit = bild("#D982C0", "")
    eingerastet = bild("#D982C0", "prompt")

    assert ruhe_ohne != ruhe_mit, "Profilfarbe ist am Punkt nicht sichtbar"
    assert ruhe_mit != eingerastet, "eingerastet sieht aus wie nur-Profil"


def test_kaputte_farbe_zeichnet_trotzdem(qapp):
    """`color` kommt aus settings.json — dort kann Unsinn stehen. Ein ungueltiger
    Wert darf den Punkt nicht verschwinden lassen."""
    from fleech.ui.overlay_qt import _StatusDot

    dot = _StatusDot()
    dot.resize(28, 28)
    dot.set_profile_color("kein-farbwert")
    dot.grab()          # darf nicht werfen


def test_overlay_reicht_die_farbe_durch(qapp):
    from fleech.ui.overlay_qt import OverlayWindow
    from fleech.usersettings import UserSettings

    ov = OverlayWindow(UserSettings().overlay)
    ov.set_profile_color("#7FD1A6")
    assert ov._math_dot._profil_farbe == "#7FD1A6"


# -- Verdrahtung in der App --------------------------------------------------------------


def test_desktop_meldet_die_farbe_des_aktiven_profils():
    import types

    from fleech.ui.desktop import DesktopApp

    gemeldet = []
    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=types.SimpleNamespace(
            enabled=True, active="Coding",
            items=[{"name": "Coding", "color": "#D982C0"}, {"name": "Alle", "default": True}],
        )),
        overlay=types.SimpleNamespace(set_profile_color=gemeldet.append),
        active_profile_name=lambda: "Coding",
    )
    DesktopApp._melde_profilfarbe(fake)
    assert gemeldet == ["#D982C0"]


def test_bei_global_ausgeschalteten_profilen_kein_ring():
    """Ein bunter Ring wuerde etwas anzeigen, das gerade gar nicht greift."""
    import types

    from fleech.ui.desktop import DesktopApp

    gemeldet = []
    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=types.SimpleNamespace(
            enabled=False, active="Coding",
            items=[{"name": "Coding", "color": "#D982C0"}],
        )),
        overlay=types.SimpleNamespace(set_profile_color=gemeldet.append),
        active_profile_name=lambda: "Coding",
    )
    DesktopApp._melde_profilfarbe(fake)
    assert gemeldet == [""]


def test_fehler_beim_faerben_haelt_das_diktieren_nicht_auf():
    """Der Aufruf haengt an Profilwechsel und Einstellungsaenderung — also an
    Wegen, die mitten im Arbeiten laufen. Eine Anzeige darf dort nie werfen."""
    import types

    from fleech.ui.desktop import DesktopApp

    def kaputt(_farbe):
        raise RuntimeError("Overlay weg")

    fake = types.SimpleNamespace(
        settings=types.SimpleNamespace(profiles=types.SimpleNamespace(
            enabled=True, active="X", items=[{"name": "X"}])),
        overlay=types.SimpleNamespace(set_profile_color=kaputt),
        active_profile_name=lambda: "X",
    )
    DesktopApp._melde_profilfarbe(fake)        # darf nicht werfen


def test_jedes_profil_in_der_liste_traegt_einen_punkt(qapp, tmp_path, monkeypatch):
    """Der ausgesprochene Wunsch: „dass alle einen farbigen Punkt haben"."""
    import fleech.usersettings as us

    monkeypatch.setattr(us, "SETTINGS_PATH", tmp_path / "settings.json")
    from fleech.history import HistoryStore
    from fleech.ui.pages.profiles import ProfilesPage
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    seite = ProfilesPage(settings, HistoryStore(tmp_path / "h.db"), lambda s: None)
    seite.refresh()          # wie beim Seitenwechsel im Hauptfenster
    liste = seite._profiles_list
    assert liste.count() >= 4
    for i in range(liste.count()):
        icon = liste.item(i).icon()
        assert not icon.isNull(), f"Zeile {i} ({liste.item(i).text()}) hat keinen Punkt"


def test_farbwahl_landet_im_profil(qapp, tmp_path, monkeypatch):
    import fleech.usersettings as us

    monkeypatch.setattr(us, "SETTINGS_PATH", tmp_path / "settings.json")
    from fleech.history import HistoryStore
    from fleech.ui.pages.profiles import ProfilesPage
    from fleech.profiles import profile_color
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    gemeldet = []
    seite = ProfilesPage(settings, HistoryStore(tmp_path / "h.db"), gemeldet.append)
    seite.refresh()
    seite._profiles_list.setCurrentRow(0)
    seite._farbe_gewaehlt("#E08585")

    assert profile_color(seite._current_profile()) == "#E08585"
    assert "profiles" in gemeldet, "die Pille erfaehrt nichts von der neuen Farbe"
