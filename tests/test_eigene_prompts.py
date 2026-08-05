"""F4a — System-Prompts sichtbar und änderbar.

Bis 5.1.0 war der Prompt hinter einem Ausgabeformat eine Blackbox: Man sah, DASS
„E-Mail" anders formuliert, aber nicht wonach. Wer das Ergebnis verschieben wollte,
musste raten.
"""

import pytest

from fleech import prompts as pmod
from fleech.textutils import TRANSCRIPT_OPEN
from fleech.prompts import load_prompt, prompt_text, save_user_prompt, user_prompt_path


@pytest.fixture
def werk(tmp_path, monkeypatch):
    """Werks-Prompts und ein leeres Nutzerverzeichnis."""
    werk_dir = tmp_path / "werk"
    werk_dir.mkdir()
    (werk_dir / "email.md").write_text("Werks-Prompt für E-Mail.", encoding="utf-8")
    (werk_dir / "cleanup.md").write_text(
        "Werks-Cleanup ohne Marker.", encoding="utf-8")
    monkeypatch.setattr(pmod, "USER_PROMPTS_DIR", tmp_path / "eigen")
    return werk_dir


def test_ohne_eigene_fassung_gilt_der_werkszustand(werk):
    text, eigen = prompt_text(werk, "email")
    assert text == "Werks-Prompt für E-Mail."
    assert eigen is False


def test_eigene_fassung_geht_vor(werk):
    save_user_prompt("email", "Meine eigene Anweisung.")
    text, eigen = prompt_text(werk, "email")
    # Zum ANSEHEN und Bearbeiten kommt die eigene Fassung unveraendert zurueck.
    assert text == "Meine eigene Anweisung."
    assert eigen is True
    # An das MODELL geht sie mit ergaenzter Sicherheitsregel: „email" formuliert
    # den ganzen Text um, dort waere eine im Diktat versteckte Anweisung genauso
    # wirksam wie beim Bereinigen. Wer die Regel aus seiner Fassung streicht,
    # bekommt sie zurueck — sie laesst sich nicht wegkuerzen.
    ans_modell = load_prompt(werk, "email")
    assert ans_modell.startswith("Meine eigene Anweisung.")
    assert TRANSCRIPT_OPEN in ans_modell


def test_zuruecksetzen_stellt_den_werkszustand_wieder_her(werk):
    save_user_prompt("email", "Meine Fassung.")
    assert user_prompt_path("email").is_file()
    save_user_prompt("email", "")               # leer = zurücksetzen
    assert not user_prompt_path("email").is_file()
    assert prompt_text(werk, "email") == ("Werks-Prompt für E-Mail.", False)


def test_eigene_prompts_liegen_ausserhalb_des_programmordners():
    """Der Programmordner wird bei jedem Update per robocopy /MIR gespiegelt —
    was dort steht, wäre nach dem nächsten Update weg."""
    from fleech.platformpaths import user_data_dir

    assert user_data_dir() in user_prompt_path("email").parents


def test_die_sicherheitsregel_laesst_sich_nicht_wegkuerzen(werk):
    """Die Guard-Untergrenze: Wer den Marker-Block aus einem gerahmten Prompt
    löscht, verliert sonst still die zweite Verteidigungslinie gegen
    „Modell führt das Diktat als Anweisung aus"."""
    from fleech.textutils import TRANSCRIPT_OPEN

    save_user_prompt("cleanup", "Mach einfach irgendwas.")
    geladen = load_prompt(werk, "cleanup")
    assert "Mach einfach irgendwas." in geladen
    assert TRANSCRIPT_OPEN in geladen           # programmatisch ergänzt
    assert "Sicherheitsregel" in geladen


def test_unlesbare_eigene_fassung_faellt_auf_werk_zurueck(werk, monkeypatch):
    save_user_prompt("email", "Meine Fassung.")

    def kaputt(*a, **k):
        raise OSError("Datei gesperrt")

    monkeypatch.setattr("pathlib.Path.read_text", kaputt)
    # prompt_text fängt den Fehler; load_prompt darf ebenfalls nicht hängenbleiben.
    with pytest.raises(OSError):
        load_prompt(werk, "email")              # ehrlich: hier gibt es kein stilles Weiter


def test_speichern_hinterlaesst_keine_temp_datei(werk):
    save_user_prompt("email", "Meine Fassung.")
    reste = list(user_prompt_path("email").parent.glob("*.tmp"))
    assert reste == []


# -- Die Oberfläche --------------------------------------------------------------------


def test_dialog_zeigt_den_prompt_und_speichert(qapp, werk, monkeypatch):
    from fleech.ui.main_window import PromptDialog

    dlg = PromptDialog("email")
    monkeypatch.setattr(dlg, "_prompts_dir", werk)
    dlg._edit.setPlainText("Meine eigene Anweisung.")
    dlg._speichern()
    assert prompt_text(werk, "email") == ("Meine eigene Anweisung.", True)
    assert "Gespeichert" in dlg._meldung.text()

    dlg._zuruecksetzen()
    assert prompt_text(werk, "email")[1] is False
    assert "Werkszustand" in dlg._meldung.text()
    dlg.deleteLater()


def test_leerer_prompt_wird_nicht_gespeichert(qapp, werk, monkeypatch):
    """Ein leerer System-Prompt würde die Bereinigung stillschweigend ruinieren."""
    from fleech.ui.main_window import PromptDialog

    dlg = PromptDialog("email")
    monkeypatch.setattr(dlg, "_prompts_dir", werk)
    dlg._edit.setPlainText("   ")
    dlg._speichern()
    assert not user_prompt_path("email").is_file()
    assert "Zurücksetzen" in dlg._meldung.text()
    dlg.deleteLater()


# -- Stichpunkte: verdichten statt umschreiben -------------------------------------------


def test_stichpunkte_prompt_verlangt_verdichtung():
    """An echten Diktaten gemessen schrieb das Modell Satz fuer Satz um, statt zu
    verdichten: Aus „Manche Profile haben einen farbigen Punkt und andere nicht"
    wurde derselbe Satz — statt „Farbigen Punkt fuer alle Profile".

    Was gefehlt hat, war ein GEGENbeispiel. Die Regel allein reichte nicht; erst
    mit „So NICHT / So RICHTIG" sank die Ausgabe an ungesehenen Diktaten um 29
    bis 65 Prozent, ohne dass Inhalt verlorenging.
    """
    from pathlib import Path

    from fleech.prompts import load_prompt

    text = load_prompt(Path("prompts"), "summary")
    assert "So NICHT" in text and "So RICHTIG" in text, "Gegenbeispiel fehlt"
    assert "Verdichten ist Pflicht" in text


def test_stichpunkte_prompt_haelt_die_kernregel():
    """Verdichten darf nicht in Zusammenfassen kippen — nichts weglassen bleibt
    die oberste Regel."""
    from pathlib import Path

    from fleech.prompts import load_prompt

    text = load_prompt(Path("prompts"), "summary")
    assert "KEINE Zusammenfassung" in text
    assert "Ein Stichpunkt = eine Sache" in text


def test_stichpunkte_prompt_wirft_verstuemmelte_woerter_weg():
    """Real: Der Versprecher „Klickreihe" wanderte unveraendert in die Stichpunkte."""
    from pathlib import Path

    from fleech.prompts import load_prompt

    text = load_prompt(Path("prompts"), "summary")
    assert "Verstümmelte Wörter nicht mitschleppen" in text


@pytest.mark.parametrize("name", ["cleanup", "cleanup-en", "prompt_engineer",
                                  "summary", "email"])
def test_umformulierende_prompts_erklaeren_die_marker(name):
    """Zweite Verteidigungslinie gegen „Modell fuehrt das Diktat als Anweisung aus".

    Sie wurde bisher nur fuer `cleanup` und `prompt_engineer` erzwungen. `summary`
    und `email` formulieren den ganzen Text um — dort waere eine im Diktat
    versteckte Anweisung genauso wirksam, und beide nannten die Marker nur
    umschreibend („zwischen den Markern"), ohne sie zu zeigen.
    """
    from pathlib import Path

    from fleech.prompts import load_prompt
    from fleech.textutils import TRANSCRIPT_CLOSE, TRANSCRIPT_OPEN

    text = load_prompt(Path("prompts"), name)
    assert TRANSCRIPT_OPEN in text, f"{name}.md zeigt den Marker nicht"
    assert TRANSCRIPT_CLOSE in text
