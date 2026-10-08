"""F2 — Rohtranskript sofort sichtbar, Statuszeile an echten Stufen.

Die Erkennung ist nach ~0,8 s durch, die Bereinigung erst nach ~4 s. Bis 5.1.0
stand in dieser Lücke nichts in der Pille. Wer schon lesen kann, während das
Modell arbeitet, wartet gefühlt nicht mehr — das ist der ganze Punkt.
"""

import types

import pytest

from fleech.pipeline import Pipeline
from fleech.ui.overlay_qt import OverlayWindow
from fleech.ui.state import AppState
from fleech.usersettings import UserSettings


@pytest.fixture
def pille(qapp):
    o = OverlayWindow(UserSettings().overlay)
    o.set_app_state(AppState.PROCESSING)
    yield o
    o.deleteLater()


# -- Pipeline meldet den Rohtext -------------------------------------------------------


def test_pipeline_meldet_rohtext_an_die_oberflaeche():
    gemeldet = []
    fake = types.SimpleNamespace(raw_callback=gemeldet.append)
    Pipeline._melde_roh(fake, "Der erkannte Text")
    assert gemeldet == ["Der erkannte Text"]


def test_leerer_rohtext_wird_nicht_gemeldet():
    gemeldet = []
    fake = types.SimpleNamespace(raw_callback=gemeldet.append)
    Pipeline._melde_roh(fake, "")
    assert gemeldet == []


def test_fehler_in_der_vorschau_haelt_das_diktat_nicht_auf():
    """Die Vorschau ist Komfort. Ein Fehler darin darf nie den Text kosten."""
    def kaputt(_t):
        raise RuntimeError("Oberfläche weg")

    fake = types.SimpleNamespace(raw_callback=kaputt)
    Pipeline._melde_roh(fake, "Text")          # darf nicht werfen

    ohne = types.SimpleNamespace(raw_callback=None)
    Pipeline._melde_roh(ohne, "Text")


# -- Die Pille zeigt ihn ---------------------------------------------------------------


def test_rohtext_erscheint_in_der_pille(pille):
    pille.show_raw_preview("Das ist der erkannte Text")
    assert not pille._caption.isHidden()
    assert "Das ist der erkannte Text" in pille._caption._label.text()


def test_stufe_tritt_unter_den_text_statt_ihn_zu_ersetzen(pille):
    """Der Kern: Sonst wäre der Gewinn wieder weg, kaum dass er da war."""
    pille.show_raw_preview("Der erkannte Text")
    pille.show_progress("Bereinige …")
    angezeigt = pille._caption._label.text()
    assert "Der erkannte Text" in angezeigt
    assert "Bereinige …" in angezeigt


def test_ohne_rohtext_zeigt_die_stufe_allein(pille):
    """Vor der Erkennung (Modell lädt) gibt es noch keinen Text — dann steht die
    Meldung wie bisher für sich."""
    pille.show_progress("KI-Modell wird geladen …")
    assert pille._caption._label.text() == "KI-Modell wird geladen …"


def test_fertige_fassung_loest_den_rohtext_ab(pille):
    pille.show_raw_preview("roher text ohne satzzeichen")
    pille.show_transcript("Roher Text, ohne Satzzeichen.")
    assert pille._roh_vorschau == ""
    assert "Roher Text, ohne Satzzeichen." in pille._caption._label.text()
    assert "ohne satzzeichen" not in pille._caption._label.text()


def test_langer_rohtext_wird_gekuerzt(pille):
    lang = "Wort " * 200
    pille.show_raw_preview(lang)
    assert len(pille._roh_vorschau) <= OverlayWindow.ROH_MAX + 2
    assert pille._roh_vorschau.endswith("…")


def test_abgeschaltete_transkript_blase_bleibt_abgeschaltet(pille):
    """Wer die Blase aus hat, will sie auch nicht als Vorschau."""
    pille.settings.show_transcript = False
    pille.show_raw_preview("Text")
    assert pille._roh_vorschau == ""


def test_nach_dem_diktat_bleibt_nichts_stehen(pille):
    pille.show_raw_preview("Text")
    pille._clear_status_caption()
    assert pille._roh_vorschau == ""
    assert pille._caption.isHidden()


# -- Die Stufen entsprechen echten Schritten -------------------------------------------


def test_statusmeldungen_haengen_an_echten_stufen():
    """Kein Fake-Fortschritt: Jede Meldung steht unmittelbar vor dem Schritt, den
    sie benennt. Dieser Test hält fest, dass sie überhaupt gemeldet werden."""
    import inspect

    quelle = inspect.getsource(Pipeline)
    # Bereinigung und Einfügen melden sich; die Formate haben eigene Meldungen.
    # Der Text der Bereinigung ist ein Attribut (die App setzt ihn, solange das
    # Modell erst geladen wird), gemeldet wird er unmittelbar vor dem Bereinigen.
    assert '_status(self.status_bereinigen)' in quelle
    assert Pipeline(stt=None, cleanup_llm=None, injector=None,
                    cleanup_prompt="S").status_bereinigen == "Bereinige …"
    assert '_status("Füge ein …")' in quelle
    # Die Meldung fürs Einfügen steht IN _inject_append — also erst, wenn
    # tatsächlich eingefügt wird, nicht vorher irgendwo im Ablauf.
    rumpf = inspect.getsource(Pipeline._inject_append)
    assert '_status("Füge ein …")' in rumpf
