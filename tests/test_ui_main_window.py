"""Hauptfenster: Navigation, Einstellungen, Home-Liste, Insights, Ratschlaege.

Teil der Qt-Smoke-Tests (offscreen, siehe conftest.py): Widgets bauen, Zustaende
schalten, Persistenz-Callbacks pruefen. Keine Optik-Pruefung.
"""

import pytest

pytest.importorskip("PySide6")

from fleech.usersettings import UserSettings
from uihelpers import make_main_window


def test_settings_panel_builds_all_pages(qapp, tmp_path, monkeypatch):
    _w, panel, _s, _st, _c = make_main_window(tmp_path, monkeypatch)
    from fleech.ui.settings_window import SettingsPanel

    assert panel._pages.count() == len(SettingsPanel.PAGES)

def test_autostart_toggle_warns_but_keeps_wish_when_write_fails(qapp, tmp_path, monkeypatch):
    """Schlaegt das Schreiben fehl (Antivirus blockt den Run-Key), wird gewarnt —
    der WUNSCH bleibt aber gespeichert.

    Frueher sprang die Checkbox zurueck und `general.autostart` wurde False. Das
    war ein selbstverstaerkender Fehler: Beim naechsten Start sah der Abgleich
    „Wunsch = aus, Eintrag da" und loeschte den Eintrag aktiv — ein einziger
    fehlgeschlagener Schreibversuch schaltete den Autostart dauerhaft ab. Real im
    Log nachweisbar gewesen.
    """
    from fleech.ui import autostart

    monkeypatch.setattr(autostart, "set_autostart", lambda enabled: False)
    monkeypatch.setattr(autostart, "is_autostart_enabled", lambda: False)
    monkeypatch.setattr(autostart, "blocked_by_system", lambda: False)

    _w, panel, _s, settings, _c = make_main_window(tmp_path, monkeypatch)
    panel._autostart_cb.setChecked(True)     # Nutzer aktiviert Autostart
    qapp.processEvents()
    assert settings.general.autostart is True         # Wunsch ueberlebt
    assert not panel._autostart_warn.isHidden()       # aber ehrlich gewarnt

def test_autostart_toggle_persists_when_write_succeeds(qapp, tmp_path, monkeypatch):
    from fleech.ui import autostart

    state = {"on": False}
    monkeypatch.setattr(autostart, "set_autostart",
                        lambda enabled: (state.update(on=enabled), True)[1])
    monkeypatch.setattr(autostart, "is_autostart_enabled", lambda: state["on"])

    _w, panel, _s, settings, _c = make_main_window(tmp_path, monkeypatch)
    panel._autostart_cb.setChecked(True)
    qapp.processEvents()
    assert panel._autostart_cb.isChecked() is True
    assert settings.general.autostart is True
    assert panel._autostart_warn.isHidden()           # keine Warnung noetig

def test_settings_save_button_and_commit(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLineEdit

    _w, panel, _s, settings, _c = make_main_window(tmp_path, monkeypatch)
    # Anzeigename-Feld finden und Text setzen OHNE editingFinished auszuloesen.
    name_field = None
    for le in panel.findChildren(QLineEdit):
        if le.placeholderText().startswith("leer = Windows"):
            name_field = le
            break
    assert name_field is not None
    name_field.setText("Alex")
    assert settings.general.display_name == ""   # noch nicht committet

    panel._save_now()                            # Speichern-Button
    assert settings.general.display_name == "Alex"   # commit() hat uebernommen
    assert "Gespeichert" in panel._save_status.text()

def test_main_window_close_saves_geometry_and_goes_to_tray(qapp, tmp_path, monkeypatch):
    window, _p, _st, settings, changed = make_main_window(tmp_path, monkeypatch)
    window.close()  # closeEvent → Geometrie gespeichert + Tray-Callback
    qapp.processEvents()
    assert "tray" in changed
    assert settings.window.width > 0
    assert (tmp_path / "settings.json").is_file()

def test_main_window_navigation_and_refresh(qapp, tmp_path, monkeypatch):
    window, _p, _st, _s, _c = make_main_window(tmp_path, monkeypatch, with_data=True)
    window.show_page("insights")
    assert window._stack.currentIndex() == 1
    assert window.insights._words_value.text() != "0"   # Daten kamen an
    window.show_page("home")
    assert window._stack.currentIndex() == 0
    assert "Willkommen zurück" in window.home._welcome.text()
    # Verlauf enthaelt Eintraege (mehr Widgets als nur der Stretch)
    assert window.home._timeline.count() > 2
    window.show_page("profiles")
    assert window._stack.currentIndex() == 2
    window.show_page("apps")
    assert window._stack.currentIndex() == 3
    window.show_page("settings")
    assert window._stack.currentIndex() == 4

def test_main_window_empty_store_shows_hint(qapp, tmp_path, monkeypatch):
    window, _p, _st, _s, _c = make_main_window(tmp_path, monkeypatch, with_data=False)
    window.show_page("home")     # darf ohne Daten nicht crashen
    window.show_page("insights")
    assert window.insights._words_value.text() == "0"

def _accent_fraction(pixmap, y: int, accent_hex: str, tol: int = 30) -> float:
    """Anteil (0..1) der Bildbreite bei Zeile y, der in Akzentfarbe gemalt ist —
    fuer Pixel-genaue Fuellstands-Checks statt Vermutungen ueber Widget-Geometrie."""
    from PySide6.QtGui import QColor

    img = pixmap.toImage()
    accent = QColor(accent_hex)

    def close(c):
        return (abs(c.red() - accent.red()) < tol and abs(c.green() - accent.green()) < tol
                and abs(c.blue() - accent.blue()) < tol)

    w = img.width()
    filled = 0
    for x in range(w):
        if close(img.pixelColor(x, y)):
            filled = x + 1
        elif filled and x - filled > 3:  # Rest ist TRACK-Farbe → Fuellkante gefunden
            break
    return filled / w

def test_usage_bar_fill_proportional_to_share(qapp):
    """Regression: der fruehere QFrame+qlineargradient-Hack loeste die Stop-Position
    manchmal VOR der finalen Layout-Breite auf und fror die Fuellung auf einen
    winzigen, share-unabhaengigen Streifen ein. UsageBar malt selbst bei jedem
    paintEvent anhand der AKTUELLEN Breite — muss fuer jeden Anteil proportional
    bleiben, auch bei sehr kleinen Prozentwerten (2 %, 1 %)."""
    from fleech.ui.main_window import ACCENT_DIM, UsageBar

    bar = UsageBar()
    bar.resize(200, bar.height())  # Hoehe ist fixiert (6px, Design-System)
    for share, lo, hi in ((0.73, 0.65, 0.80), (0.13, 0.08, 0.20), (0.02, 0.02, 0.12)):
        bar.set_share(share)
        frac = _accent_fraction(bar.grab(), bar.height() // 2, ACCENT_DIM)
        assert lo <= frac <= hi, f"share={share}: gefuellt={frac:.2f}"

def test_insights_usage_bars_stay_proportional_with_tiny_shares(qapp, tmp_path, monkeypatch):
    """Wie oben, aber End-to-End durch die echte InsightsPage.refresh()-Verdrahtung
    (Store → app_usage-Shares → UsageBar.set_share). Die Balkenbreite wird explizit
    gesetzt statt vom Stretch-Layout erwartet — unter der Offscreen-Testplattform
    loest QHBoxLayout-Stretch keine realistische Breite auf (bleibt bei wenigen px,
    unabhaengig vom Fix); das ist eine Plattform-Eigenheit, keine Regression.
    WICHTIG: setFixedWidth() statt resize() — ein reines resize() auf einem Kind
    eines LIVE Stretch-Layouts kann von grab() (loest intern einen Layout-Pass aus)
    wieder ueberschrieben werden; setFixedWidth aendert die Size Policy und bleibt
    ueber grab()-Aufrufe hinweg stabil (empirisch verifiziert)."""
    import time

    from fleech.history import DictationRecord
    from fleech.ui.main_window import ACCENT_DIM, UsageBar

    window, _p, store, _s, _c = make_main_window(tmp_path, monkeypatch)
    now = time.time()
    for i, (app_name, words) in enumerate(
        [("Code.exe", 73), ("comet.exe", 13), ("Discord.exe", 11), ("javaw.exe", 3)]
    ):
        text = " ".join(["wort"] * words)
        store.add(DictationRecord(ts=now - i, raw=text, cleaned=text,
                                  audio_seconds=words / 2.0, app=app_name))
    window.show_page("insights")

    fractions = []
    for row in window.insights._usage_rows:
        bar = row.findChild(UsageBar)
        bar.setFixedWidth(200)
        frac = _accent_fraction(bar.grab(), bar.height() // 2, ACCENT_DIM)
        fractions.append(round(frac, 2))
    # Absteigend nach Anteil (Code 73 % > comet 13 % > Discord 11 % > javaw 3 %) —
    # der urspruengliche Bug zeigte hier ueberall fast denselben (falschen) Wert.
    assert fractions[0] > fractions[1] > fractions[2] > fractions[3]
    assert fractions[0] > 0.6   # Code: deutlich mehr als die Haelfte gefuellt
    assert fractions[3] < 0.25  # javaw (3 %): klar erkennbar als kleinster Balken

def test_home_delete_single_entry(qapp, tmp_path, monkeypatch):
    window, _p, store, _s, _c = make_main_window(tmp_path, monkeypatch, with_data=True)
    window.show_page("home")
    before = store.recent(limit=50)
    assert len(before) == 3
    victim_id = before[0]["id"]

    window.home._delete_entry(victim_id)
    after = store.recent(limit=50)
    assert len(after) == 2
    assert victim_id not in [e["id"] for e in after]
    # Insights zog automatisch mit (kein Crash, Store konsistent)
    assert window.insights._words_value.text() != ""

def test_home_entry_rows_are_clickable_and_open_full_text(qapp, tmp_path, monkeypatch):
    from fleech.history import DictationRecord
    from fleech.ui.main_window import HistoryEntryRow

    window, _p, store, _s, _c = make_main_window(tmp_path, monkeypatch)
    long_text = "Dies ist ein sehr langer Diktattext, " + "wort " * 80 + "Schluss."
    store.add(DictationRecord(ts=1_700_000_000.0, raw="roh", cleaned=long_text,
                              audio_seconds=20.0, app="Code.exe"))
    window.show_page("home")

    rows = window.home.findChildren(HistoryEntryRow)
    assert len(rows) == 1

    opened = []
    # Nicht-modal: _open_entry ruft .show() (nicht .exec()) — Referenz landet in
    # window.home._detail_dialog.
    monkeypatch.setattr("fleech.ui.main_window.TranscriptDetailDialog.show",
                        lambda self: opened.append(self))
    rows[0].clicked.emit()
    assert len(opened) == 1
    dlg = window.home._detail_dialog
    # Der Dialog haelt den VOLLEN (nicht abgeschnittenen) Text.
    assert dlg._text == long_text
    assert "…" not in dlg._edit.toPlainText()

def test_transcript_detail_dialog_copies_to_clipboard(qapp):
    from PySide6.QtWidgets import QApplication

    from fleech.ui.main_window import TranscriptDetailDialog

    entry = {"id": 1, "ts": 1_700_000_000.0, "cleaned": "Der Report ist fertig.",
             "app": "Code.exe", "words": 4}
    dlg = TranscriptDetailDialog(entry)
    assert "Der Report ist fertig." in dlg._edit.toPlainText()
    dlg._copy()
    assert QApplication.clipboard().text() == "Der Report ist fertig."
    assert "Kopiert" in dlg._copy_btn.text()
    dlg.close()

def test_transcript_detail_dialog_closes_on_deactivate(qapp):
    from PySide6.QtCore import QEvent

    from fleech.ui.main_window import TranscriptDetailDialog

    entry = {"id": 1, "ts": 1_700_000_000.0, "cleaned": "Text.", "app": "", "words": 1}
    dlg = TranscriptDetailDialog(entry)
    closed = []
    dlg.close = lambda: closed.append(1)  # Spy: deterministisch, unabhaengig vom Offscreen-Fokus

    # Guard: Deactivate OHNE vorherige Aktivierung wird ignoriert (kein Sofort-Schliessen).
    dlg.event(QEvent(QEvent.WindowDeactivate))
    assert closed == []
    # Nach Aktivierung schliesst ein Klick daneben (WindowDeactivate) das Fenster.
    dlg.event(QEvent(QEvent.WindowActivate))
    dlg.event(QEvent(QEvent.WindowDeactivate))
    assert closed == [1]

def test_history_delete_and_recent_has_id(tmp_path):
    import time

    from fleech.history import DictationRecord, HistoryStore

    store = HistoryStore(tmp_path / "h.db")
    for i in range(3):
        store.add(DictationRecord(ts=time.time() - i, raw="a b c",
                                  cleaned=f"Eintrag {i}.", audio_seconds=2.0))
    rows = store.recent()
    assert all("id" in r for r in rows)
    store.delete(rows[0]["id"])
    assert len(store.recent()) == 2
    store.delete(999999)  # nicht vorhanden → kein Fehler
    assert len(store.recent()) == 2

def test_word_detail_dialog_shows_words_beyond_top_five(qapp, tmp_path):
    import time

    from PySide6.QtWidgets import QLabel

    from fleech.history import DictationRecord, HistoryStore
    from fleech.ui.main_window import WordDetailDialog

    store = HistoryStore(tmp_path / "h.db")
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta"]
    for i, w in enumerate(words):
        text = " ".join([w] * (len(words) - i))  # absteigende Haeufigkeit
        store.add(DictationRecord(ts=time.time() - i, raw=text, cleaned=text,
                                  audio_seconds=2.0))

    dlg = WordDetailDialog(store)
    labels = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    # "zeta"/"eta" haetten auf den Top 5 der Karte keinen Platz mehr — im Dialog schon.
    assert "zeta" in labels
    assert "eta" in labels
    dlg.close()

def test_word_detail_dialog_empty_store_shows_hint(qapp, tmp_path):
    from PySide6.QtWidgets import QLabel

    from fleech.history import HistoryStore
    from fleech.ui.main_window import WordDetailDialog

    dlg = WordDetailDialog(HistoryStore(tmp_path / "h.db"))
    labels = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    assert "Noch keine Daten." in labels
    dlg.close()

def test_insights_word_card_open_detail_is_wired(qapp, tmp_path, monkeypatch):
    window, _p, _st, _s, _c = make_main_window(tmp_path, monkeypatch)
    from fleech.ui import main_window as mw

    opened = []
    monkeypatch.setattr(mw.WordDetailDialog, "exec", lambda self: opened.append(True))
    window.insights._open_word_detail()
    assert opened == [True]

def test_interface_toggles_hide_cards(qapp, tmp_path, monkeypatch):
    window, _p, _st, settings, _c = make_main_window(tmp_path, monkeypatch, with_data=True)
    ui = settings.interface
    # Default: alles sichtbar (nicht explizit versteckt)
    assert not window.insights._streak_frame.isHidden()
    assert not window.home._stats_frame.isHidden()

    ui.insights_show_streak = False
    ui.insights_show_app_usage = False
    ui.insights_show_top_words = False
    ui.insights_show_patterns = False
    ui.home_show_stats = False
    ui.home_show_welcome = False
    window.apply_interface()
    assert window.insights._streak_frame.isHidden()
    assert window.insights._usage_frame.isHidden()
    assert window.insights._words_freq_frame.isHidden()
    assert window.insights._pattern_frame.isHidden()
    assert window.home._stats_frame.isHidden()
    assert window.home._welcome.isHidden()
    # Metrik-Karten blieben unangetastet
    assert not window.insights._wpm_frame.isHidden()

    ui.insights_show_streak = True
    window.apply_interface()
    assert not window.insights._streak_frame.isHidden()

def test_interface_settings_roundtrip(tmp_path):
    import fleech.usersettings as us

    path = tmp_path / "settings.json"
    settings = UserSettings()
    settings.interface.insights_show_streak = False
    settings.interface.home_show_stats = False
    settings.save(path)
    loaded = us.UserSettings.load(path)
    assert loaded.interface.insights_show_streak is False
    assert loaded.interface.home_show_stats is False
    assert loaded.interface.insights_show_wpm is True  # Default unangetastet

def test_insights_advice_offers_one_click_rule(qapp, tmp_path, monkeypatch):
    """Insights waren rein deskriptiv. Aus „kimano wurde 3x zu Kimono korrigiert"
    wird jetzt per Klick eine Woerterbuch-Regel — ohne Umweg ueber die Einstellungen."""
    import time

    from PySide6.QtWidgets import QPushButton

    from fleech.history import DictationRecord

    window, panel, store, settings, _changed = make_main_window(tmp_path, monkeypatch)
    now = time.time()
    for i in range(3):
        store.add(DictationRecord(
            ts=now - i, raw="wir nutzen kimano dafuer",
            cleaned="wir nutzen Kimono dafuer", audio_seconds=5.0, app="Test.exe",
            mode="cleanup", tier="simple", status="ok", stt_ms=200, llm_ms=900,
        ))
    window.show_page("insights")
    qapp.processEvents()
    # isHidden() statt isVisible(): ohne gezeigtes Fenster ist Letzteres immer False.
    assert not window.insights._advice_frame.isHidden()

    buttons = [b for b in window.insights._advice_frame.findChildren(QPushButton)
               if b.text().startswith("Als Regel")]
    assert buttons, "kein Ein-Klick-Vorschlag erzeugt"
    buttons[0].click()
    qapp.processEvents()
    assert "kimano => Kimono" in settings.output.dictionary
    # Der Editor in den Einstellungen zieht mit (sonst erst nach Neustart sichtbar).
    assert "kimano => Kimono" in panel._dictionary_editor.toPlainText()
    # Zweiter Klick darf keine Dublette anlegen.
    window._add_dictionary_rule("kimano", "Kimono")
    assert settings.output.dictionary.count("kimano => Kimono") == 1

def test_karten_ausblenden_und_zurueckholen(qapp, tmp_path, monkeypatch):
    """Die Seite „Oberflaeche" mit zwoelf Checkboxen ist entfallen: Ausblenden
    passiert per Rechtsklick an der Karte, Zurueckholen sammelt ein Knopf."""
    from dataclasses import fields

    from fleech.usersettings import InterfaceSettings

    from fleech.ui.settings_window import SettingsPanel

    assert "Oberfläche" not in SettingsPanel.PAGES

    _w, panel, _st, settings, changed = make_main_window(tmp_path, monkeypatch)
    # Wie ein Rechtsklick-Ausblenden: mehrere Karten aus.
    settings.interface.insights_show_wpm = False
    settings.interface.home_show_stats = False

    panel._restore_cards()

    # Nur die Sichtbarkeits-Felder: „profiles_advanced" ist ein Bedien-Schalter,
    # keine Karte — der Knopf darf ihn nicht mit umlegen.
    assert all(getattr(settings.interface, f.name) for f in fields(InterfaceSettings)
               if "_show_" in f.name)
    assert settings.interface.profiles_advanced is False
    assert "interface" in changed
    assert "2 Karte(n)" in panel._cards_hint.text()

def test_karte_ausblenden_schreibt_die_einstellung(qapp, tmp_path, monkeypatch):
    """Das Kontextmenue setzt das Feld, versteckt die Karte und meldet es."""
    _w, panel, _st, settings, changed = make_main_window(tmp_path, monkeypatch)
    frame = _w.insights._wpm_frame
    assert frame.property("hide_attr") == "insights_show_wpm"

    # Menue-Ausfuehrung ist nicht testbar (blockierendes exec) — die Wirkung schon.
    setattr(settings.interface, frame.property("hide_attr"), False)
    settings.save()
    frame.hide()
    panel._on_changed("interface")

    assert settings.interface.insights_show_wpm is False
    assert frame.isHidden()
    assert "interface" in changed

def test_streak_calendar_and_gauge_render(qapp, tmp_path, monkeypatch):
    import datetime as dt

    window, _p, _st, _s, _c = make_main_window(tmp_path, monkeypatch, with_data=True)
    window.insights.refresh()
    window.insights._calendar.set_data({dt.date.today().isoformat(): 5})
    assert not window.insights._calendar.grab().isNull()
    window.insights._gauge.set_wpm(97)
    assert not window.insights._gauge.grab().isNull()

def test_woerter_karte_zeigt_einen_buchvergleich():
    """Die Zeile unter „Wörter diktiert" trug bis v3.7.3 den Lokal-Anteil. Seit es
    gar keinen Cloud-Pfad mehr gibt (v3.6.0), konnte sie nichts anderes mehr sagen
    als „100 % lokal" — tote Fläche. Jetzt steht dort ein Größenvergleich."""
    from fleech.milestones import word_milestone

    assert "Fache von" in word_milestone(74_245)
    assert word_milestone(0) == ""

def _advice_page(tmp_path, settings, pairs):
    """InsightsPage mit vorbereiteter Historie voller Korrektur-Paare."""
    import time as _t

    from fleech.history import DictationRecord, HistoryStore
    from fleech.ui.main_window import InsightsPage

    store = HistoryStore(tmp_path / "advice.db")
    now = _t.time()
    for i, (wrong, right) in enumerate(pairs):
        for n in range(3):          # min_count=2 → mindestens zweimal noetig
            store.add(DictationRecord(
                ts=now - (i * 10 + n), raw=f"wir nutzen {wrong} heute",
                cleaned=f"Wir nutzen {right} heute.", audio_seconds=5.0,
                app="Code.exe", mode="cleanup", tier="simple", status="ok",
                stt_ms=200, llm_ms=800))
    taken: list = []
    page = InsightsPage(store, on_add_rule=lambda w, r: taken.append((w, r)),
                        settings=settings)
    page.refresh()
    return page, taken

def _advice_labels(page):
    from PySide6.QtWidgets import QLabel

    out = []
    for row in page._advice_rows:
        label = row if isinstance(row, QLabel) else row.findChild(QLabel)
        if label is not None:
            out.append(label.text())
    return out

def test_uebernommene_regel_verschwindet_dauerhaft(qapp, tmp_path):
    """Der Fehler, den der Nutzer gemeldet hat: Die Korrektur-Paare bleiben in der
    Historie, also kam der Vorschlag nach dem Übernehmen zurück."""
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    page, _taken = _advice_page(tmp_path, settings, [("playside", "PySide")])
    assert any("playside" in t for t in _advice_labels(page))

    # Regel wie beim Ein-Klick-Übernehmen eintragen …
    settings.output.dictionary.append("playside => PySide")
    page.refresh()
    assert not any("playside" in t for t in _advice_labels(page))

    # … und nach dem Löschen der Regel darf der Vorschlag zu Recht wiederkommen.
    settings.output.dictionary.clear()
    page.refresh()
    assert any("playside" in t for t in _advice_labels(page))

def test_ignorieren_wirkt_ueber_die_sichtbare_liste(qapp, tmp_path, monkeypatch):
    """Ignoriert = Eintrag in dictionary_ignores (sichtbar unter Woerterbuch).
    Zeile loeschen holt den Vorschlag zurueck — genau deshalb darf es dauerhaft sein."""
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    page, _taken = _advice_page(tmp_path, settings, [("kimano", "Kimono")])
    assert any("kimano" in t for t in _advice_labels(page))

    settings.output.dictionary_ignores = ["kimano => kimono"]
    page.refresh()
    assert not any("kimano" in t for t in _advice_labels(page))

    # Zeile im Editor geloescht → Vorschlag kommt zurueck.
    settings.output.dictionary_ignores = []
    page.refresh()
    assert any("kimano" in t for t in _advice_labels(page))

def test_ignorieren_knopf_schreibt_in_die_ignorier_liste(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    monkeypatch.setattr(UserSettings, "save", lambda self, path=None: None)
    notified: list = []
    page, _taken = _advice_page(tmp_path, settings, [("kimano", "Kimono")])
    page._on_ignored = lambda: notified.append(True)

    buttons = page._advice_rows[0].findChildren(QPushButton)
    ignore = [b for b in buttons if b.text() == "Ignorieren"]
    assert ignore, "Ignorieren-Knopf fehlt"
    ignore[0].click()

    assert "kimano => kimono" in settings.output.dictionary_ignores
    assert notified                       # Woerterbuch-Editor wurde benachrichtigt
    assert not any("kimano" in t for t in _advice_labels(page))
    assert settings.output.dictionary_ignores.count("kimano => kimono") == 1

def test_migration_advice_dismissed_nach_dictionary_ignores(tmp_path):
    """Kurzlebiges v1.10.1-Feld advice_dismissed wandert in die sichtbare Liste."""
    import json

    from fleech.usersettings import UserSettings

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"output": {
        "dictionary_ignores": ["alt => bestand"],
        "advice_dismissed": {"kimano => kimono": 123.0, "ALT => BESTAND": 5.0},
    }}), encoding="utf-8")
    settings = UserSettings.load(path)
    assert "kimano => kimono" in settings.output.dictionary_ignores
    # Case-insensitives Duplikat wird nicht doppelt uebernommen.
    assert len([i for i in settings.output.dictionary_ignores
                if i.lower() == "alt => bestand"]) == 1

def test_weitere_vorschlaege_ruecken_nach(qapp, tmp_path):
    """Sind die vordersten Paare erledigt, darf die Karte nicht leer bleiben."""
    from fleech.usersettings import UserSettings

    settings = UserSettings()
    # Echte Wortpaare: top_corrections ueberspringt reine Gross-/Kleinschreibung.
    pairs = [("playside", "PySide"), ("kimano", "Kimono"), ("gitthub", "GitHub"),
             ("pyton", "Python"), ("kosinus", "Cosinus")]
    page, _taken = _advice_page(tmp_path, settings, pairs)
    assert len(_advice_labels(page)) == 3

    for wrong, right in pairs[:3]:
        settings.output.dictionary.append(f"{wrong} => {right}")
    page.refresh()
    # Die drei erledigten sind weg, dahinterliegende ruecken nach.
    labels = _advice_labels(page)
    assert labels and not any("playside" in t for t in labels)

def test_dauer_waehlt_die_passende_einheit():
    """„0,05 h" sagt niemandem etwas, „906 min" auch nicht mehr."""
    from fleech.ui.main_window import _dauer

    assert _dauer(0) == "0 s"
    assert _dauer(46) == "46 s"          # Ø je Diktat — nicht auf „1 min" runden
    assert _dauer(59) == "59 s"
    assert _dauer(60) == "1 min"
    assert _dauer(3600) == "1 h"         # nicht „1 h 0 min"
    assert _dauer(3900) == "1 h 5 min"
    assert _dauer(54360) == "15,1 Stunden"
    assert _dauer(None) == "0 s" and _dauer(-5) == "0 s"

def test_diktierzeit_kommt_aus_der_echten_sprechzeit():
    """Nicht aus Woertern/WPM gerechnet — das waere ein Zirkelschluss (WPM stammt
    aus denselben zwei Zahlen) und wuerde Pausen und Verworfenes unterschlagen."""
    import types

    from fleech.ui.main_window import _diktierzeit_text

    text = _diktierzeit_text(types.SimpleNamespace(
        total_audio_seconds=54360, total_dictations=1174))
    assert "15,1 Stunden gesprochen" in text
    assert "Ø 46 s je Diktat" in text

    leer = _diktierzeit_text(types.SimpleNamespace(
        total_audio_seconds=0, total_dictations=0))
    assert "Noch keine" in leer
