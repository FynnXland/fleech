"""F3 — ein gespeichertes Diktat nachträglich anders bereinigen.

Der Anlass: falsches Profil erwischt. Statt neu zu diktieren wird das ROHTRANSKRIPT
noch einmal durch dieselbe Pipeline geschickt — inklusive aller Guards.
"""

import types

import pytest

from fleech.pipeline import Pipeline


def _pipe(**kw):
    """Pipeline-Attrappe mit genau den Feldern, die reprocess anfasst."""
    fake = types.SimpleNamespace(
        _finalize=lambda t: t,
        _cleanup=lambda raw, *a, **k: (f"bereinigt:{raw}", False),
        _format_text=lambda raw, fmt: f"{fmt}:{raw}",
    )
    for k, v in kw.items():
        setattr(fake, k, v)
    return fake


# -- Der Kern: es wird auf dem ROHTEXT aufgesetzt --------------------------------------


def test_neu_bereinigen_nutzt_das_rohtranskript():
    fake = _pipe()
    assert Pipeline.reprocess(fake, "das ist der rohe text", "email") == \
        "email:das ist der rohe text"


def test_standardformat_laeuft_ueber_das_normale_cleanup():
    fake = _pipe()
    assert Pipeline.reprocess(fake, "roher text", "") == "bereinigt:roher text"


def test_unbekanntes_format_faellt_auf_cleanup_zurueck():
    """Ein Profil kann gelöscht worden sein — dann darf nichts hängen."""
    fake = _pipe()
    assert Pipeline.reprocess(fake, "roher text", "gibtsnicht") == "bereinigt:roher text"


def test_gescheitertes_format_verliert_den_text_nicht():
    """Modell weg, Prompt-Datei fehlt: dann kommt das normale Cleanup — nie nichts."""
    fake = _pipe(_format_text=lambda raw, fmt: "")
    assert Pipeline.reprocess(fake, "roher text", "email") == "bereinigt:roher text"


def test_leerer_rohtext_gibt_leer_zurueck():
    fake = _pipe()
    assert Pipeline.reprocess(fake, "", "email") == ""
    assert Pipeline.reprocess(fake, "   ", "email") == ""
    assert Pipeline.reprocess(fake, None, "email") == ""


def test_ausnahme_wird_gefangen():
    """Ein Fehler in der Nachbearbeitung darf die App nicht mitreißen — der
    Verlaufseintrag bleibt ohnehin unangetastet."""
    def kaputt(*a, **k):
        raise RuntimeError("Modell weg")

    fake = _pipe(_cleanup=kaputt, _format_text=kaputt)
    assert Pipeline.reprocess(fake, "roher text", "email") == ""


def test_reprocess_fuegt_nichts_ein():
    """Der entscheidende Unterschied zum Diktat: Das Ergebnis geht NICHT ins
    Zielfeld. Wer im Verlauf rechtsklickt, steht im Fleech-Fenster — blind ins
    zuletzt benutzte Feld zu schreiben ist die Fehlerklasse, aus der die
    Cursor-Regeln stammen."""
    eingefuegt = []
    fake = _pipe(_inject_append=eingefuegt.append,
                 injector=types.SimpleNamespace(inject=eingefuegt.append))
    Pipeline.reprocess(fake, "roher text", "email")
    assert eingefuegt == []


# -- Die Oberfläche --------------------------------------------------------------------


def test_ergebnis_landet_in_der_zwischenablage(qapp, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from fleech.ui.desktop import DesktopApp

    gemeldet = []
    fake = types.SimpleNamespace(_flash_status=gemeldet.append)
    DesktopApp._on_reprocessed(fake, "Sehr geehrte Damen und Herren, …", "E-Mail")
    assert QApplication.clipboard().text().startswith("Sehr geehrte")
    assert "E-Mail" in gemeldet[0]


def test_gescheiterte_nachbearbeitung_meldet_sich_ehrlich(qapp):
    from fleech.ui.desktop import DesktopApp

    gemeldet = []
    fake = types.SimpleNamespace(_flash_status=gemeldet.append)
    DesktopApp._on_reprocessed(fake, "", "E-Mail")
    assert "fehlgeschlagen" in gemeldet[0]
    assert "unverändert" in gemeldet[0]


def test_waehrend_eines_diktats_wird_nicht_nachbearbeitet(qapp):
    """Zwei Läufe gleichzeitig würden denselben DocumentTracker beschreiben."""
    import threading

    from fleech.ui.desktop import DesktopApp

    lock = threading.Lock()
    lock.acquire()
    gemeldet = []
    fake = types.SimpleNamespace(_process_lock=lock, _flash_status=gemeldet.append)
    DesktopApp._reprocess_entry(fake, "roh", "email", "E-Mail")
    assert gemeldet == ["Ein Diktat läuft noch"]
    lock.release()


def test_eintrag_ohne_rohtranskript_wird_uebersprungen(qapp, tmp_path, monkeypatch):
    """Alte Einträge können ohne `raw` in der Datenbank stehen."""
    from fleech.ui.main_window import HomePage
    from fleech.history import HistoryStore
    from fleech.usersettings import UserSettings

    gerufen = []
    store = HistoryStore(tmp_path / "h.db")
    seite = HomePage(UserSettings(), store, on_reprocess=lambda *a: gerufen.append(a))
    monkeypatch.setattr(store, "raw_text", lambda _id: "")
    seite._reprocess({"id": 1, "cleaned": "Text"}, "email", "E-Mail")
    assert gerufen == []


def test_kontextmenue_bietet_die_ausgabeformate(qapp, tmp_path):
    """Angeboten werden die FORMATE, nicht die Profilnamen: Zwei Profile mit
    demselben Format ergäben denselben Text — eine Auswahl ohne Unterschied."""
    from PySide6.QtWidgets import QMenu

    from fleech.history import HistoryStore
    from fleech.ui.main_window import HomePage
    from fleech.usersettings import UserSettings

    store = HistoryStore(tmp_path / "h.db")
    seite = HomePage(UserSettings(), store, on_reprocess=lambda *a: None)
    # Gebaut, nicht geöffnet — `exec` startet eine Event-Loop.
    haupt = seite._baue_eintrag_menue({"id": 1, "ts": 0, "cleaned": "Text"})
    menues = seite.findChildren(QMenu)
    beschriftungen = [a.text() for a in haupt.actions() if a.text()]
    assert "Neu bereinigen als …" in beschriftungen
    assert "Rohtext kopieren" in beschriftungen
    assert "Eintrag löschen" in beschriftungen

    unter = next(m for m in menues
                 if m is not haupt and any("E-Mail" == a.text() for a in m.actions()))
    formate = [a.text() for a in unter.actions()]
    assert "E-Mail" in formate and "Stichpunkte" in formate
    # „Formeln" gehört nicht dazu: Der Formel-Parser braucht das Audio-Timing,
    # nachträglich aus dem Rohtext ergäbe das keinen sinnvollen Lauf.
    assert "Formeln" not in formate


def test_kopieren_legt_text_in_die_zwischenablage(qapp, tmp_path):
    from PySide6.QtWidgets import QApplication

    from fleech.history import HistoryStore
    from fleech.ui.main_window import HomePage
    from fleech.usersettings import UserSettings

    seite = HomePage(UserSettings(), HistoryStore(tmp_path / "h.db"))
    seite._kopiere("Der bereinigte Text")
    assert QApplication.clipboard().text() == "Der bereinigte Text"
