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
    ans_fenster = []
    fake = types.SimpleNamespace(
        _flash_status=gemeldet.append,
        _melde_nachbearbeitung=lambda t, g: ans_fenster.append((t, g)),
    )
    DesktopApp._on_reprocessed(fake, "Sehr geehrte Damen und Herren, …", "E-Mail")
    assert QApplication.clipboard().text().startswith("Sehr geehrte")
    assert "E-Mail" in gemeldet[0]
    # Das Fortschritts-Fenster bekommt denselben Text — ohne diesen Weg blieb der
    # Erfolg unsichtbar (die Pille zeigt ihn nur waehrend einer Verarbeitung).
    assert ans_fenster == [("Sehr geehrte Damen und Herren, …", "")]


def test_gescheiterte_nachbearbeitung_meldet_sich_ehrlich(qapp):
    from fleech.ui.desktop import DesktopApp

    gemeldet = []
    ans_fenster = []
    fake = types.SimpleNamespace(
        _flash_status=gemeldet.append,
        _melde_nachbearbeitung=lambda t, g: ans_fenster.append((t, g)),
    )
    DesktopApp._on_reprocessed(fake, "", "E-Mail", "Die lokale KI antwortet nicht.")
    assert "fehlgeschlagen" in gemeldet[0]
    assert "unverändert" in gemeldet[0]
    # Der GRUND reist mit: „fehlgeschlagen" allein sagt nicht, was zu tun ist.
    assert ans_fenster == [("", "Die lokale KI antwortet nicht.")]


def test_waehrend_eines_diktats_wird_nicht_nachbearbeitet(qapp):
    """Zwei Läufe gleichzeitig würden denselben DocumentTracker beschreiben."""
    import threading

    from fleech.ui.desktop import DesktopApp

    lock = threading.Lock()
    lock.acquire()
    gesendet = []
    bus = types.SimpleNamespace(
        reprocessed=types.SimpleNamespace(emit=lambda *a: gesendet.append(a)))
    fake = types.SimpleNamespace(_process_lock=lock, bus=bus)
    DesktopApp._reprocess_entry(fake, "roh", "email", "E-Mail")
    # Beantwortet wird ueber DASSELBE Signal wie ein Erfolg. Ein stilles `return`
    # liesse das Fortschritts-Fenster endlos laufen — das war der ganze Fehler.
    assert len(gesendet) == 1
    text, name, grund = gesendet[0]
    assert text == "" and name == "E-Mail" and "Diktat läuft" in grund
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
    # Uebersprungen heisst nicht stumm: Wer klickt, erfaehrt warum nichts kommt.
    dialog = seite._nachbearbeitung_dialog
    assert not dialog.isHidden()
    assert "kein Rohtranskript" in dialog._ergebnis.toPlainText()
    dialog.close()


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


# -- Das Fortschritts-Fenster ----------------------------------------------------------

def _dialog(qapp, roh="roher text", name="KI-Prompt"):
    from fleech.ui.nachbearbeitungdialog import NachbearbeitungDialog

    return NachbearbeitungDialog(roh, name, {"ts": 0, "app": "Code.exe"})


def test_fenster_zeigt_sofort_den_rohtext_und_dass_es_laeuft(qapp):
    """Der Kern der Sache: Zwischen Klick und Ergebnis darf der Bildschirm nicht
    schweigen. Vorher lief die Rueckmeldung ueber die Pille, und die zeigt
    Zwischenschritte nur waehrend einer Verarbeitung — beim Nachbearbeiten aus dem
    Verlauf also nie."""
    d = _dialog(qapp)
    assert not d._balken.isHidden()
    assert d._balken.maximum() == 0          # unbestimmt: die Dauer kennt niemand
    assert "wird neu bereinigt" in d._ergebnis.toPlainText()
    assert not d._kopieren.isEnabled()       # es gibt noch nichts zu kopieren
    d.close()


def test_fenster_setzt_das_ergebnis_ein(qapp):
    d = _dialog(qapp)
    d.zeige_ergebnis("Der fertige Prompt.")
    assert d._balken.isHidden()
    assert d._ergebnis.toPlainText() == "Der fertige Prompt."
    assert d._kopieren.isEnabled()
    # Dass automatisch kopiert wurde, muss dastehen — ungesagt war es Teil des Problems.
    assert "Zwischenablage" in d._hinweis.text()
    d.close()


def test_fenster_nennt_den_grund_statt_nur_zu_scheitern(qapp):
    d = _dialog(qapp)
    d.zeige_fehler("Die lokale KI antwortet nicht.")
    assert d._balken.isHidden()
    assert "lokale KI" in d._ergebnis.toPlainText()
    assert not d._kopieren.isEnabled()
    d.close()


def test_fenster_haelt_auch_einen_eintrag_ohne_zeitstempel_aus(qapp):
    """Altbestand hat keinen vollstaendigen Eintrag — das Fenster IST die
    Rueckmeldung und darf daran nicht scheitern."""
    from fleech.ui.nachbearbeitungdialog import NachbearbeitungDialog

    d = NachbearbeitungDialog("roh", "E-Mail", {})
    assert "wird neu bereinigt" in d._ergebnis.toPlainText()
    d.close()


def test_startseite_oeffnet_das_fenster_VOR_dem_auftrag(qapp, tmp_path):
    """Reihenfolge: erst das Fenster, dann die Arbeit. Andersherum koennte eine
    sehr schnelle Antwort da sein, bevor es jemanden gibt, der sie anzeigt."""
    from fleech.history import HistoryStore
    from fleech.ui.main_window import HomePage
    from fleech.usersettings import UserSettings

    reihenfolge = []
    store = HistoryStore(tmp_path / "h.db")

    def auftrag(*_a):
        seite = getattr(page, "_nachbearbeitung_dialog", None)
        reihenfolge.append("fenster" if seite is not None else "kein fenster")

    page = HomePage(UserSettings(), store, on_reprocess=auftrag)
    page.store.raw_text = lambda _id: "roher text"
    page._reprocess({"id": 1, "ts": 0, "cleaned": "Text"}, "prompt", "KI-Prompt")
    assert reihenfolge == ["fenster"]

    # Und das Ergebnis findet den Weg hinein.
    page.melde_nachbearbeitung("Fertig.", "")
    assert page._nachbearbeitung_dialog._ergebnis.toPlainText() == "Fertig."
    page._nachbearbeitung_dialog.close()
