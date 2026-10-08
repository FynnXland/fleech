"""Der Tresor: Umschlag, Schluessel, SQLCipher, Umstellung von Klartext (6.3.0).

Die Ablage des Schluessels ist hier immer der Testspeicher aus conftest — kein
Test beruehrt DPAPI-Block oder Schluesselbund des Nutzers. Der echte DPAPI-Weg
wird einmal gegen ein Wegwerf-Verzeichnis geprueft.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys

import pytest

from fleech import tresor
from fleech.tresor import datei, datenbank, schluessel, umstellung


def _klartext_db(pfad, zeilen=3, wal=False):
    con = sqlite3.connect(pfad)
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE dictations (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL,"
                " raw TEXT, cleaned TEXT)")
    for i in range(zeilen):
        con.execute("INSERT INTO dictations (ts, raw, cleaned) VALUES (?,?,?)",
                    (1.0 * i, f"GEHEIMNIS roh {i}", f"GEHEIMNIS sauber {i}"))
    con.commit()
    return con   # offen lassen = WAL bleibt ungeschrieben (bei wal=True)


# -- Umschlag ---------------------------------------------------------------------


def test_umschlag_hin_und_zurueck_und_ohne_klartext():
    roh = tresor.schuetze(b'{"name": "Erika Mustermann"}', tresor.EINSTELLUNGEN)
    assert datei.ist_umschlag(roh)
    assert b"Mustermann" not in roh
    assert tresor.oeffne(roh, tresor.EINSTELLUNGEN) == b'{"name": "Erika Mustermann"}'


def test_zwei_umschlaege_desselben_inhalts_sind_verschieden():
    """Zufaellige Nonce: Gleicher Inhalt verraet sich nicht durch gleiche Bytes."""
    a = tresor.schuetze(b"gleich", tresor.EINSTELLUNGEN)
    b = tresor.schuetze(b"gleich", tresor.EINSTELLUNGEN)
    assert a != b


def test_veraenderter_umschlag_faellt_auf():
    roh = bytearray(tresor.schuetze(b"wichtig", tresor.EINSTELLUNGEN))
    roh[-1] ^= 0x01
    with pytest.raises(tresor.Unlesbar):
        tresor.oeffne(bytes(roh), tresor.EINSTELLUNGEN)


def test_umschlag_laesst_sich_nicht_fuer_einen_anderen_zweck_oeffnen():
    roh = tresor.schuetze(b"x", tresor.EINSTELLUNGEN)
    with pytest.raises(tresor.Unlesbar):
        datei.entschluessele(roh, schluessel.teilschluessel(tresor.VERLAUF),
                             tresor.EINSTELLUNGEN)


def test_klartext_geht_unveraendert_durch():
    """Eine settings.json von vor 6.3.0 bleibt lesbar — sie wird erst beim
    naechsten Speichern verschluesselt."""
    assert tresor.oeffne(b'{"a": 1}', tresor.EINSTELLUNGEN) == b'{"a": 1}'


# -- Schluessel ---------------------------------------------------------------------


def test_schluessel_entsteht_einmal_und_bleibt(tresor_ablage):
    k = schluessel.hauptschluessel()
    assert len(k) == 32 and tresor_ablage.wert == k
    schluessel.vergiss()
    assert schluessel.hauptschluessel() == k


def test_teilschluessel_sind_verschieden_und_nicht_der_hauptschluessel():
    teile = {z: schluessel.teilschluessel(z)
             for z in (tresor.VERLAUF, tresor.KONTEXT, tresor.EINSTELLUNGEN)}
    assert len(set(teile.values())) == 3
    assert schluessel.hauptschluessel() not in teile.values()


def test_kein_neuer_schluessel_neben_verschluesselten_daten(tmp_path, tresor_ablage):
    """Der gefaehrlichste Fehler: Schluessel fehlt, Daten sind verschluesselt — und
    Fleech erzeugt still einen neuen. Danach oeffnete der Code nur noch die Haelfte."""
    ordner = tmp_path / "appdata"
    ordner.mkdir(exist_ok=True)
    (ordner / "settings.json").write_bytes(tresor.schuetze(b"{}", tresor.EINSTELLUNGEN))
    tresor_ablage.wert = None
    schluessel.vergiss()
    with pytest.raises(schluessel.SchluesselFehlt):
        schluessel.hauptschluessel()
    assert tresor_ablage.wert is None
    assert schluessel.fehlt()


def test_unlesbarer_schluesselblock_wird_nicht_ueberschrieben(monkeypatch):
    class Kaputt:
        gespeichert = False

        def lies(self):
            raise OSError("anderes Konto")

        def speichere(self, k):
            self.gespeichert = True

        def beschreibung(self):
            return "kaputt"

    kaputt = Kaputt()
    monkeypatch.setattr(schluessel, "ablage", lambda: kaputt)
    schluessel.vergiss()
    assert schluessel.fehlt()
    assert not kaputt.gespeichert


def test_wiederherstellungscode_hin_und_zurueck():
    k = schluessel.hauptschluessel()
    code = schluessel.code_aus(k)
    assert len(code.split("-")) == 11
    assert schluessel.schluessel_aus(code) == k
    # Kleinschreibung, Leerzeichen statt Bindestrich, 0 statt O: alles egal.
    locker = code.lower().replace("-", " ").replace("o", "0")
    assert schluessel.schluessel_aus(locker) == k


def test_tippfehler_im_code_wird_erkannt():
    code = schluessel.code_aus(schluessel.hauptschluessel())
    falsch = ("B" if code[0] != "B" else "C") + code[1:]
    with pytest.raises(ValueError):
        schluessel.schluessel_aus(falsch)
    with pytest.raises(ValueError):
        schluessel.schluessel_aus(code[:20])


def test_code_passt_nur_zu_den_eigenen_daten(tmp_path):
    from fleech.history import DictationRecord, HistoryStore

    ordner = tmp_path / "appdata"
    store = HistoryStore(ordner / "history.db")
    store.add(DictationRecord(ts=1.0, raw="a", cleaned="b", audio_seconds=1.0))
    assert schluessel.passt_zu_daten(schluessel.hauptschluessel(), ordner)
    assert not schluessel.passt_zu_daten(b"\x01" * 32, ordner)


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI gibt es nur unter Windows")
def test_dpapi_ablage_schuetzt_den_schluessel(tmp_path):
    from fleech.tresor.ablage import DpapiAblage

    ablage = DpapiAblage(tmp_path)
    assert ablage.lies() is None
    k = bytes(range(32))
    ablage.speichere(k)
    assert ablage.pfad.read_bytes().find(k) == -1   # nicht im Klartext abgelegt
    assert DpapiAblage(tmp_path).lies() == k


# -- SQLCipher ------------------------------------------------------------------------


def test_verlauf_liegt_verschluesselt_auf_der_platte(tmp_path):
    from fleech.history import DictationRecord, HistoryStore

    pfad = tmp_path / "history.db"
    store = HistoryStore(pfad)
    store.add(DictationRecord(ts=1.0, raw="Kontonummer GEHEIMNIS", cleaned="GEHEIMNIS",
                              audio_seconds=1.0, app="bank.exe", title="Bankportal"))
    roh = pfad.read_bytes()
    assert not roh.startswith(datenbank.SQLITE_KOPF)
    for wort in (b"GEHEIMNIS", b"bank.exe", b"Bankportal", b"dictations"):
        assert wort not in roh
    assert store.recent()[0]["cleaned"] == "GEHEIMNIS"
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(pfad).execute("SELECT * FROM dictations").fetchall()


def test_falscher_schluessel_oeffnet_die_datenbank_nicht(tmp_path):
    from fleech.history import HistoryStore

    pfad = tmp_path / "history.db"
    HistoryStore(pfad)
    assert datenbank.oeffnet_mit(pfad, schluessel.teilschluessel(tresor.VERLAUF))
    assert not datenbank.oeffnet_mit(pfad, schluessel.teilschluessel(tresor.KONTEXT))


# -- Umstellung -------------------------------------------------------------------------


def _alter_datenordner(ordner):
    """So sah %APPDATA%\\Fleech bis 6.2 aus — alles im Klartext."""
    ordner.mkdir(parents=True, exist_ok=True)
    _klartext_db(ordner / "history.db", zeilen=5).close()
    offen = _klartext_db(ordner / "kontext.db", zeilen=4, wal=True)
    eintrag = json.dumps({"general": {"display_name": "Erika"}}).encode()
    (ordner / "settings.json").write_bytes(eintrag)
    (ordner / "settings.json.bak").write_bytes(eintrag)
    (ordner / "sicherungen").mkdir()
    (ordner / "sicherungen" / "settings-20261001-120000-build.json").write_bytes(eintrag)
    (ordner / "fleech.log").write_text("Eingefuegt: GEHEIMNIS\n", encoding="utf-8")
    (ordner / "fleech.log.1").write_text("STT: GEHEIMNIS\n", encoding="utf-8")
    (ordner / "fleech-cli.log").write_text("GEHEIMNIS\n", encoding="utf-8")
    return offen


def test_umstellung_verschluesselt_alles_und_tilgt_die_protokolle(tmp_path):
    ordner = tmp_path / "appdata"
    offen = _alter_datenordner(ordner)
    offen.close()   # wie beim Start: niemand haelt die Dateien offen
    assert umstellung.noetig(ordner)

    bericht = umstellung.fuehre_aus(ordner)

    assert bericht.zeilen == {"history.db": 5, "kontext.db": 4}
    assert bericht.dateien == 3 and bericht.protokolle == 3
    assert not umstellung.noetig(ordner)
    for datei_ in ordner.rglob("*"):
        if datei_.is_file():
            assert b"GEHEIMNIS" not in datei_.read_bytes(), datei_.name
            assert b"Erika" not in datei_.read_bytes(), datei_.name
    assert not list(ordner.glob("*.klartext")) and not list(ordner.glob("*.neu"))
    assert not (ordner / "kontext.db-wal").exists()
    # … und alles ist mit dem Tresor weiter lesbar.
    con = tresor.verbinde(ordner / "history.db", tresor.VERLAUF)
    assert con.execute("SELECT count(*) FROM dictations").fetchone()[0] == 5
    from tresorhelfer import lies_json
    assert lies_json(ordner / "sicherungen" / "settings-20261001-120000-build.json") \
        == {"general": {"display_name": "Erika"}}


def test_umstellung_uebernimmt_auch_noch_nicht_geschriebene_wal_eintraege(tmp_path):
    """kontext.db laeuft im WAL-Modus: Die juengsten Begriffe stehen nur in der
    -wal-Datei. Ohne Checkpoint vor dem Export waeren sie verloren."""
    import shutil

    quelle = tmp_path / "quelle"
    quelle.mkdir()
    offen = _klartext_db(quelle / "kontext.db", zeilen=7, wal=True)
    offen.execute("PRAGMA wal_autocheckpoint = 0")
    offen.execute("INSERT INTO dictations (ts, raw, cleaned) VALUES (9, 'WAL', 'WAL')")
    offen.commit()
    # Abzug WAEHREND die Verbindung offen ist: Hauptdatei + -wal, wie nach einem
    # harten Ende von Fleech. Schliessen wuerde vorher alles zurueckschreiben.
    pfad = tmp_path / "kontext.db"
    shutil.copy(quelle / "kontext.db", pfad)
    shutil.copy(quelle / "kontext.db-wal", tmp_path / "kontext.db-wal")
    offen.close()
    assert (tmp_path / "kontext.db-wal").stat().st_size > 0
    zaehlung = datenbank.umstellen(pfad, schluessel.teilschluessel(tresor.KONTEXT))
    assert zaehlung["dictations"] == 8
    assert not (tmp_path / "kontext.db-wal").exists()


def test_umstellung_ist_wiederholbar(tmp_path):
    ordner = tmp_path / "appdata"
    _alter_datenordner(ordner).close()
    umstellung.fuehre_aus(ordner)
    zweiter = umstellung.fuehre_aus(ordner)
    assert not zweiter.etwas_getan and zweiter.protokolle == 0


def test_abbruch_vor_dem_tausch_legt_das_original_zurueck(tmp_path):
    """Original schon nach .klartext verschoben, Kopie noch nicht an seinem Platz:
    Der naechste Start holt das Original zurueck und stellt erneut um."""
    pfad = tmp_path / "history.db"
    _klartext_db(pfad, zeilen=2).close()
    pfad.replace(pfad.with_name("history.db.klartext"))
    zaehlung = datenbank.umstellen(pfad, schluessel.teilschluessel(tresor.VERLAUF))
    assert zaehlung["dictations"] == 2
    assert datenbank.ist_verschluesselt(pfad)
    assert not pfad.with_name("history.db.klartext").exists()


def test_abbruch_nach_dem_tausch_tilgt_den_klartext_rest(tmp_path):
    pfad = tmp_path / "history.db"
    _klartext_db(pfad, zeilen=2).close()
    datenbank.umstellen(pfad, schluessel.teilschluessel(tresor.VERLAUF))
    rest = pfad.with_name("history.db.klartext")
    rest.write_bytes(b"SQLite format 3\x00 GEHEIMNIS")
    assert umstellung.noetig(tmp_path)
    datenbank.umstellen(pfad, schluessel.teilschluessel(tresor.VERLAUF))
    assert not rest.exists()


def test_protokolle_tilgen_schliesst_den_eigenen_handler_und_schreibt_weiter(tmp_path):
    ordner = tmp_path
    handler = logging.FileHandler(ordner / "fleech.log", encoding="utf-8")
    wurzel = logging.getLogger()
    wurzel.addHandler(handler)
    try:
        logging.getLogger("fleech.test").warning("Eingefuegt: GEHEIMNIS")
        handler.flush()
        assert umstellung.protokolle_tilgen(ordner) == 1
        logging.getLogger("fleech.test").warning("danach")
        handler.flush()
        inhalt = (ordner / "fleech.log").read_text(encoding="utf-8")
        assert "GEHEIMNIS" not in inhalt and "danach" in inhalt
    finally:
        wurzel.removeHandler(handler)
        handler.close()


def test_beiseitelegen_verschiebt_statt_zu_loeschen(tmp_path, tresor_ablage):
    from fleech.history import DictationRecord, HistoryStore

    ordner = tmp_path / "appdata"
    HistoryStore(ordner / "history.db").add(
        DictationRecord(ts=1.0, raw="a", cleaned="b", audio_seconds=1.0))
    (ordner / "settings.json").write_bytes(tresor.schuetze(b"{}", tresor.EINSTELLUNGEN))
    tresor_ablage.wert = None
    schluessel.vergiss()
    assert schluessel.fehlt()

    ziel = umstellung.beiseitelegen(ordner)

    assert (ziel / "history.db").exists() and (ziel / "settings.json").exists()
    assert not (ordner / "history.db").exists()
    assert not schluessel.fehlt()          # frischer Anfang mit neuem Schluessel


# -- Struktur ---------------------------------------------------------------------------


def test_niemand_oeffnet_sqlite_am_tresor_vorbei():
    """Eine einzige `sqlite3.connect`-Zeile genuegt, und eine Datenbank liegt
    wieder im Klartext — oder laesst sich nicht mehr lesen."""
    from pathlib import Path

    kern = Path(__file__).resolve().parents[1] / "fleech"
    verdaechtig = [str(p.relative_to(kern)) for p in kern.rglob("*.py")
                   if "tresor" not in p.parts
                   and ("sqlite3.connect" in p.read_text(encoding="utf-8")
                        or "import sqlite3" in p.read_text(encoding="utf-8"))]
    assert verdaechtig == []


def test_plattformweiche_nur_in_der_ablage():
    from pathlib import Path

    ordner = Path(tresor.__file__).parent
    mit_weiche = sorted(p.name for p in ordner.glob("*.py")
                        if "sys.platform" in p.read_text(encoding="utf-8"))
    assert mit_weiche == ["ablage.py"]
