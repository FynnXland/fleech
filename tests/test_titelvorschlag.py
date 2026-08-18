"""Titel anbieten statt abtippen (V-11/G-3) — ohne Qt.

Die Titel-Regel ist der einzige Hebel fuer Anwendungen mit vielen Kontexten (ein
Browser, ein Editor). Sie war praktisch unbedienbar: Man muss den Titel kennen und
fehlerfrei abtippen, sieht ihn aber nicht, solange man in Fleech steht.
"""

from fleech.ui.pages.titelvorschlag import MAX_PUFFER, angebot, merke, segmente


def test_puffer_haelt_die_neuesten_fenster_vorn():
    puffer: list = []
    for i in range(3):
        puffer = merke(puffer, "Code.exe", f"datei{i}.py - Fleech - Visual Studio Code")
    assert puffer[0][1].startswith("datei2")
    assert len(puffer) == 3


def test_dasselbe_fenster_steigt_auf_statt_sich_zu_haeufen():
    """Sonst waere der Puffer nach einer Minute Stillstand achtmal dasselbe."""
    puffer: list = []
    for _ in range(10):
        puffer = merke(puffer, "Code.exe", "Fleech - Visual Studio Code")
    assert len(puffer) == 1


def test_puffer_laeuft_nicht_ueber():
    puffer: list = []
    for i in range(MAX_PUFFER + 5):
        puffer = merke(puffer, f"app{i}.exe", f"Fenster {i}")
    assert len(puffer) == MAX_PUFFER


def test_leerer_titel_kommt_nicht_in_den_puffer():
    assert merke([], "Code.exe", "") == []
    assert merke([], "", "Irgendein Fenster") == []


def test_angebot_bevorzugt_die_gewaehlte_anwendung():
    """Eine Titel-Regel gilt immer nur fuer ihre Anwendung — ein Titel aus einer
    anderen waere als Bedingung sinnlos."""
    puffer = merke(merke([], "Code.exe", "Fleech - Visual Studio Code"),
                   "comet.exe", "Claude — Fleech")
    assert angebot(puffer, "Code.exe") == ("Fleech - Visual Studio Code", "Code.exe")
    # Ohne eigenes Fenster: das zuletzt gesehene, aber mit genannter Herkunft.
    assert angebot(puffer, "Word.exe") == ("Claude — Fleech", "comet.exe")
    assert angebot([], "Code.exe") == ("", "")


def test_segmente_setzen_das_gemeinsame_nach_vorn():
    """„Fleech" steht in beiden Fenstern, der Dateiname nur in einem — genau der
    stabile Teil ist die Bedingung, die man haben will."""
    puffer = merke(merke([], "Code.exe", "apps.py - Fleech - Visual Studio Code"),
                   "Code.exe", "profiles.py - Fleech - Visual Studio Code")
    treffer = segmente(puffer, "Code.exe")
    assert treffer[0] == "fleech"
    assert "apps.py" in treffer or "profiles.py" in treffer


def test_gelerntes_wiegt_schwerer_als_eine_einzelne_sichtung():
    """Was `kontext.db` ueber viele Diktate gelernt hat, ist der bessere Hinweis
    als das Fenster von gerade eben."""
    puffer = merke([], "Code.exe", "kurzbesuch.py - Anderes Projekt - Visual Studio Code")
    treffer = segmente(puffer, "Code.exe", gelernt=["fleech"])
    assert treffer[0] == "fleech"


def test_segmente_fremder_anwendungen_bleiben_draussen():
    puffer = merke(merke([], "Code.exe", "apps.py - Fleech - Visual Studio Code"),
                   "comet.exe", "Eldorado — Kaufrichtlinien")
    assert "eldorado" not in segmente(puffer, "Code.exe")
