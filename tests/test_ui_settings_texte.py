"""U3: Hilfetexte, Sichtbarkeit und Ausgrauen auf den Einstellungsseiten.

Deckt die Befunde E-1, E-5, E-9/E-12, E-11, E-15, E-17, A-2/E-10, A-14/E-16 ab —
Teil der Qt-Smoke-Tests (offscreen, siehe conftest.py).
"""

import pytest

pytest.importorskip("PySide6")


def _panel(settings=None, **kw):
    from fleech.ui.settings_window import SettingsPanel
    from fleech.usersettings import UserSettings

    settings = settings or UserSettings()
    return SettingsPanel(settings, lambda sec: None, lambda: [], **kw), settings


# -- E-1: Hinweistext am Diktat-Hotkey -----------------------------------------------

def test_diktat_hotkey_hint_text_nennt_loeschen_nicht_abbrechen(qapp):
    """Esc LOESCHT die Bindung (siehe hotkey_recorder.py) — der Hinweis muss das
    sagen, nicht "abbrechen" versprechen (das war der Vorgabe-Wortlaut)."""
    import inspect

    from fleech.ui.settings import aufnahme

    quelle = inspect.getsource(aufnahme.build)
    assert "Esc, Entf oder Backspace = Bindung löschen" in quelle
    assert "Esc = abbrechen" not in quelle


# -- E-5: Badge-Tooltip einer Auswahlliste zeigt ALLE Optionen -----------------------

def test_combo_help_text_zeigt_alle_optionen_mit_erklaerung(qapp):
    from fleech.ui.settings_window import _combo_help_text

    values = [("a", "Option A"), ("b", "Option B")]
    help_map = {"a": "Erklärung A", "b": "Erklärung B"}
    text = _combo_help_text(values, help_map, "a")
    assert "Erklärung A" in text
    assert "Erklärung B" in text          # NICHT nur die aktive Option
    assert "<b>Option A</b>" in text      # aktive fett markiert
    assert "<b>Option B</b>" not in text


def test_combo_badge_traegt_alle_optionen_und_wandert_mit(qapp):
    """Integrationstest: der tatsaechlich gebaute Badge-Tooltip, nicht nur die
    Hilfsfunktion — und er zieht beim Umschalten nach (die neue Aktive wird fett)."""
    from PySide6.QtWidgets import QFormLayout, QWidget

    from fleech.ui.widgets import HelpBadge

    panel, settings = _panel()
    holder = QWidget()
    form = QFormLayout(holder)
    box = panel._combo(
        form, "Test", [("a", "A"), ("b", "B")], "a", "output", lambda v: None,
        help_map={"a": "Erklärung A", "b": "Erklärung B"},
    )
    badge = holder.findChild(HelpBadge)
    assert "Erklärung A" in badge._tip
    assert "Erklärung B" in badge._tip
    assert "<b>A</b>" in badge._tip

    box.setCurrentIndex(1)                # auf "B" wechseln
    assert "<b>B</b>" in badge._tip
    assert "<b>A</b>" not in badge._tip
    assert "Erklärung A" in badge._tip    # A bleibt lesbar, auch nicht mehr aktiv


# -- E-5/E-9/E-12: Freihand-Block ganz weg, Sprechpause bleibt beim Anstupsen ------

def test_freihand_block_steht_nicht_mehr_auf_der_aufnahme_seite(qapp):
    """Befund E-5: Bis 5.10.x war der Block nur AUSGEGRAUT — dieser Test prüfte
    genau das. Ausgegraute Zeilen unter einem toten Schalter erklären trotzdem
    nichts; in 5.11.0 ist die Oberfläche entfernt (Code eingefroren, STILLGELEGT
    bleibt). Was der Nutzer sehen kann, muss wahr sein."""
    from fleech.freihand import STILLGELEGT

    assert STILLGELEGT is True
    panel, _ = _panel()
    namen = ("_freihand_cb", "_startwort_liste", "_startwort_probe_btn",
             "_freihand_genauigkeit", "_freihand_abbruchwort",
             "_freihand_fehlersuche", "_freihand_ausgeschlossen")
    for name in namen:
        assert getattr(panel, name, None) is None, f"{name} steht noch in der Seite"


def test_sprechpause_bleibt_und_spricht_vom_anstupsen(qapp):
    """Der Regler gehört zum Anstupsen-Modus, nicht zu Freihand — er darf mit dem
    Freihand-Block NICHT verschwunden sein (er teilt sich nur das Settings-Feld)."""
    import inspect

    from fleech.ui.settings import aufnahme

    panel, _ = _panel()
    assert getattr(panel, "_sprechpause_box", None) is not None
    quelle = inspect.getsource(aufnahme.build)
    assert "Nur beim Anstupsen:" in quelle
    assert "Freihand" not in quelle


# -- E-11: Click-Through nennt die betroffenen Knoepfe ------------------------------

def test_click_through_hinweis_nennt_die_pillenknoepfe(qapp):
    import inspect

    from fleech.ui.settings import overlay

    quelle = inspect.getsource(overlay.build)
    assert "Knöpfe der Pille" in quelle
    assert "✕" in quelle and "✓" in quelle and "Pause" in quelle


# -- E-15: Auto-Hide nur bei Sichtbarkeit "auto_hide" sichtbar ----------------------

def test_auto_hide_zeile_nur_bei_auto_hide_sichtbar(qapp):
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    settings.overlay.visibility = "during_activity"
    panel, _ = _panel(settings=settings)
    form = panel._auto_hide_box.parentWidget().layout()
    # Direkt nach dem Bau: Vorgabe ist NICHT auto_hide -> Zeile versteckt.
    assert not form.isRowVisible(panel._auto_hide_box)

    panel._sichtbarkeit_box.setCurrentIndex(
        panel._sichtbarkeit_box.findData("auto_hide")
    )
    assert form.isRowVisible(panel._auto_hide_box)

    panel._sichtbarkeit_box.setCurrentIndex(
        panel._sichtbarkeit_box.findData("during_activity")
    )
    assert not form.isRowVisible(panel._auto_hide_box)


def test_auto_hide_zeile_startet_sichtbar_wenn_schon_auto_hide(qapp):
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    settings.overlay.visibility = "auto_hide"
    panel, _ = _panel(settings=settings)
    form = panel._auto_hide_box.parentWidget().layout()
    assert form.isRowVisible(panel._auto_hide_box)


# -- E-17: Safe-Word-Platzhalter zeigt den wirksamen Wert ---------------------------

def test_safe_word_platzhalter_zeigt_effektiven_wert(qapp, monkeypatch):
    import types

    cfg = types.SimpleNamespace(command=types.SimpleNamespace(trigger_word="Ananas"))
    monkeypatch.setattr("fleech.config.load_config", lambda *a, **k: cfg)
    panel, _ = _panel()
    assert panel._trigger_field.placeholderText() == "leer = Ananas (aus config.yaml)"


def test_safe_word_platzhalter_faellt_bei_kaputter_config_zurueck(qapp, monkeypatch):
    def kaputt(*a, **k):
        raise RuntimeError("kein Zugriff")

    monkeypatch.setattr("fleech.config.load_config", kaputt)
    panel, _ = _panel()
    assert panel._trigger_field.placeholderText() == "leer = Wert aus config.yaml"


# -- A-2/E-10/E-4: "Adaptive Geschwindigkeit" gibt es gar nicht mehr ----------------

def test_es_gibt_keinen_schalter_fuer_adaptive_geschwindigkeit_mehr(qapp):
    """Bis 5.10.x stand hier ein Schalter, dessen Tooltip ein „kleines, schnelleres
    Modell" versprach — dieser Test prüfte nur noch, dass der Tooltip nicht mehr
    lügt. Befund E-4: Der Schalter stand bei jedem auf „an" und konnte gar nichts
    bewirken, weil `cleanup` und `cleanup_fast` bewusst dasselbe Modell fahren.
    In 5.11.0 ist er entfernt; das Routing läuft fest weiter."""
    import inspect

    from fleech.ui.settings import advanced
    from fleech.usersettings import AdvancedSettings

    quelle = inspect.getsource(advanced.build)
    # Kein Bedienelement mehr (der erklärende Kommentar im Code darf bleiben).
    assert 'form, "Adaptive Geschwindigkeit' not in quelle
    assert "kleines, schnelleres Modell" not in quelle
    assert "kurzen Weg" not in quelle
    assert not hasattr(AdvancedSettings(), "adaptive_cleanup")


# -- A-14/E-16: Warmhaltung-Zahlen auf dem heutigen Stand ---------------------------

def test_warmhaltung_zahlen_sind_aktuell(qapp):
    import inspect

    from fleech.ui.settings import advanced

    quelle = inspect.getsource(advanced.build)
    assert "~8 GB" not in quelle
    assert "3,5 GB" in quelle
    assert "~8 s" not in quelle
