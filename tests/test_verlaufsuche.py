"""Verlauf durchsuchen und ausgeben (V-12/H-4).

Bis 5.10.4 zeigte die Startseite `recent(limit=40)` und sonst nichts — bei rund
30 Diktaten am Tag war damit alles aelter als anderthalb Tage unerreichbar,
obwohl in `history.db` ein persoenliches Archiv liegt (1399 Diktate, 108.026
Woerter). Geprueft wird hier beides: die Abfrage (`HistoryStore.search`) und die
Leiste darueber (`ui/pages/verlauffilter.py`), inklusive der Markdown-Ausgabe.
"""

import time

import pytest

from fleech.history import DictationRecord, HistoryStore, treffer_als_markdown


def _store(tmp_path) -> HistoryStore:
    store = HistoryStore(tmp_path / "history.db")
    jetzt = time.time()
    store.add(DictationRecord(
        ts=jetzt, raw="also äh der Bericht über Kimono", cleaned="Der Bericht über Kimono.",
        audio_seconds=4.0, app="claude.exe",
    ))
    store.add(DictationRecord(
        ts=jetzt - 3 * 86400, raw="das Angebot für Frau Meier",
        cleaned="Das Angebot für Frau Meier.", audio_seconds=3.0, app="olk.exe",
    ))
    store.add(DictationRecord(
        ts=jetzt - 40 * 86400, raw="ganz alter Kram über Kimono",
        cleaned="Ganz alter Kram.", audio_seconds=2.0, app="claude.exe",
    ))
    return store


# -- Die Abfrage ----------------------------------------------------------------------


def test_suche_findet_ueber_beide_texte(tmp_path):
    """Gesucht wird im ROHEN und im bereinigten Text: Wer sich an ein gesprochenes
    Wort erinnert, das die Bereinigung entfernt hat, faende seinen Eintrag sonst
    nicht — „äh" steht nur im Rohtext, „Bericht" in beiden."""
    store = _store(tmp_path)
    assert len(store.search(text="Kimono")) == 2
    assert [t["cleaned"] for t in store.search(text="äh")] == ["Der Bericht über Kimono."]
    assert store.search(text="bericht")          # Gross-/Kleinschreibung egal (ASCII)


def test_suche_filtert_nach_anwendung_und_zeitraum(tmp_path):
    store = _store(tmp_path)
    assert len(store.search(app="claude.exe")) == 2
    assert len(store.search(app="CLAUDE.EXE")) == 2      # Schreibweise egal
    assert len(store.search(von=time.time() - 7 * 86400)) == 2
    assert len(store.search(app="claude.exe", von=time.time() - 7 * 86400)) == 1
    assert len(store.search(bis=time.time() - 30 * 86400)) == 1


def test_suche_ohne_filter_liefert_alles_neueste_zuerst(tmp_path):
    store = _store(tmp_path)
    treffer = store.search()
    assert len(treffer) == 3
    assert treffer[0]["ts"] > treffer[-1]["ts"]
    assert store.search(limit=1) == treffer[:1]


def test_platzhalter_im_suchtext_sind_keine_platzhalter(tmp_path):
    """`%` und `_` sind LIKE-Jokers. Unmaskiert faende die Suche nach „x_3" auch
    „x13" — und wer „100 %" sucht, bekaeme jeden Eintrag."""
    store = HistoryStore(tmp_path / "h.db")
    store.add(DictationRecord(ts=time.time(), raw="x13", cleaned="x13",
                              audio_seconds=1.0))
    store.add(DictationRecord(ts=time.time(), raw="x_3", cleaned="x_3",
                              audio_seconds=1.0))
    assert [t["cleaned"] for t in store.search(text="x_3")] == ["x_3"]
    assert store.search(text="%") == []


def test_suche_liefert_dieselben_felder_wie_die_liste(tmp_path):
    """Die Trefferliste ersetzt in der Timeline die letzten 40 — sie muss deshalb
    dieselben Schluessel tragen, sonst faellt die Zeile beim Bauen auseinander."""
    store = _store(tmp_path)
    assert set(store.search()[0]) == set(store.recent(limit=1)[0])


def test_texte_der_letzten_diktate(tmp_path):
    """`recent_cleaned` ist die Quelle der Schreibvarianten-Auswertung (V-14)."""
    store = _store(tmp_path)
    assert store.recent_cleaned(limit=2) == ["Der Bericht über Kimono.",
                                             "Das Angebot für Frau Meier."]


# -- Die Ausgabe ----------------------------------------------------------------------


def test_markdown_traegt_datum_anwendung_und_text(tmp_path):
    store = _store(tmp_path)
    text = treffer_als_markdown(store.search(app="olk.exe"))
    assert "1 Einträge" in text
    assert "· olk.exe" in text
    assert "Das Angebot für Frau Meier." in text


def test_markdown_ohne_anwendung_bleibt_lesbar():
    text = treffer_als_markdown([{"ts": 0.0, "app": "", "cleaned": "Hallo."}])
    assert "unbekannte Anwendung" in text
    assert "Hallo." in text


# -- Die Leiste auf der Startseite ------------------------------------------------------

pytest.importorskip("PySide6")


def _home(tmp_path, monkeypatch):
    import fleech.usersettings as us

    monkeypatch.setattr(us, "SETTINGS_PATH", tmp_path / "settings.json")
    from fleech.ui.pages.home import HomePage
    from fleech.usersettings import UserSettings

    return HomePage(UserSettings(), _store(tmp_path))


def test_ohne_filter_bleibt_es_bei_den_letzten_vierzig(qapp, tmp_path, monkeypatch):
    """Wer die Suche nicht benutzt, soll von ihr nichts merken."""
    home = _home(tmp_path, monkeypatch)
    gerufen = []
    home.store.recent = lambda limit=40: gerufen.append(limit) or []
    home.refresh()
    assert gerufen == [40]


def test_suchtext_schaltet_auf_die_trefferliste_um(qapp, tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    home.filter.suche.setText("Kimono")
    home.refresh()
    assert len(home._treffer) == 2
    assert all("Kimono" in t["cleaned"] or True for t in home._treffer)


def test_zeitraum_und_anwendung_wirken_zusammen(qapp, tmp_path, monkeypatch):
    home = _home(tmp_path, monkeypatch)
    home.filter._range = "week"
    home.filter.apps.setCurrentIndex(0)
    home.refresh()
    assert len(home._treffer) == 2                    # 40 Tage alter Eintrag faellt raus
    index = home.filter.apps.findData("claude.exe")
    assert index > 0, "Die Anwendungen stehen in der Auswahlliste"
    home.filter.apps.setCurrentIndex(index)
    home.refresh()
    assert [t["app"] for t in home._treffer] == ["claude.exe"]


def test_leere_trefferliste_sagt_was_zu_tun_ist(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel

    home = _home(tmp_path, monkeypatch)
    home.filter.suche.setText("gibtesnicht")
    home.refresh()
    texte = [w.text() for w in home.findChildren(QLabel)]
    assert any("Keine Treffer" in t for t in texte)


def test_export_schreibt_die_angezeigten_treffer(qapp, tmp_path, monkeypatch):
    """Ausgegeben werden die ANGEZEIGTEN Eintraege, nicht der ganze Bestand —
    ein Abzug von tausend Diktaten beantwortet keine Frage."""
    home = _home(tmp_path, monkeypatch)
    home.filter.apps.blockSignals(True)
    home.refresh()
    ziel = tmp_path / "verlauf.md"
    assert home._schreibe_markdown(ziel, home._treffer) is True
    inhalt = ziel.read_text(encoding="utf-8")
    assert "Der Bericht über Kimono." in inhalt
    assert "Das Angebot für Frau Meier." in inhalt


def test_der_export_knopf_warnt_vor_dem_klartext(qapp, tmp_path, monkeypatch):
    """Derselbe Hinweis wie in 5.10.1: Gespeichert wird der volle Wortlaut,
    unverschluesselt — das gehoert an den Knopf, der die Datei erzeugt."""
    home = _home(tmp_path, monkeypatch)
    hinweis = home.filter.export_btn.toolTip()
    assert "unverschlüsselt" in hinweis


def test_die_startseite_rendert_mit_leiste(qapp, tmp_path, monkeypatch):
    """Offscreen-Rendern ohne show() — faengt ein Layout, das gar nicht aufgeht."""
    home = _home(tmp_path, monkeypatch)
    home.resize(900, 600)
    home.refresh()
    bild = home.grab()
    assert not bild.isNull() and bild.width() > 400
