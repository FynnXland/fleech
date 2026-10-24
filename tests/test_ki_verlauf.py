"""Der KI-Austausch je Diktat im Verlauf (`llm/mitschnitt.py`, `kiverlauf.py`).

Anlass (Nutzer, 2026-10-21): Was die KI bekam und zurueckgab, war nach dem Diktat
weg — vor allem die Antwort, die ein Guard verworfen hat. Und wie gross die
Verlaufs-Datenbank ist, stand nirgends.
"""

import time

import pytest

from fleech import kiverlauf
from fleech.history import DictationRecord, HistoryStore
from fleech.llm.frist import FristAbgelaufen, KiFrist, Uebersprungen
from fleech.llm.mitschnitt import KiAufruf, aufrufe_von
from fleech.textutils import wrap_transcript
from fleech.ui.pages.verlaufbestand import bestand_zeile, groesse_text
from pipelinehelpers import AUDIO, CLEAN_NONTRIVIAL, RAW_NONTRIVIAL, FakeLLM, make_pipeline


class _Cfg:
    provider, model = "ollama", "gemma3:4b"


class ModellLLM(FakeLLM):
    cfg = _Cfg()


# -- Mitschnitt ------------------------------------------------------------------------

def test_frist_schneidet_eingabe_und_antwort_mit():
    f = KiFrist()
    f.neues_diktat()
    assert f.frage(ModellLLM(reply="Sauber."), "SYS", "roh") == "Sauber."
    [a] = f.mitschnitt.aufrufe
    assert (a.anbieter, a.modell, a.system, a.eingabe, a.antwort, a.fehler) == \
        ("ollama", "gemma3:4b", "SYS", "roh", "Sauber.", "")


def test_fehler_und_abbrueche_stehen_lesbar_im_mitschnitt():
    f = KiFrist()
    with pytest.raises(RuntimeError):
        f.frage(FakeLLM(error=RuntimeError("HTTP 500")), "S", "u")
    f._ende = time.monotonic() + 0.05

    class Langsam:
        def complete(self, s, u):
            time.sleep(2)
            return "zu spaet"

    with pytest.raises(FristAbgelaufen):
        f.frage(Langsam(), "S", "u")
    f.ueberspringen()          # waehrend die KI rechnet (`_warte`, nicht `frage`)
    with pytest.raises(Uebersprungen):
        f._warte(Langsam(), "S", "u", None)
    assert [a.fehler for a in f.mitschnitt.aufrufe] == [
        "RuntimeError: HTTP 500", "Zeitgrenze überschritten", "Übersprungen (Haken)"]


def test_neues_diktat_beginnt_einen_leeren_mitschnitt():
    f = KiFrist()
    f.frage(FakeLLM(reply="a"), "S", "u")
    f.neues_diktat()
    assert f.mitschnitt.aufrufe == []


def test_pipeline_haelt_auch_die_verworfene_antwort_fest():
    """Der Kern der Sache: Ein Guard verwirft die Antwort, der Rohtext wird
    eingefuegt — im Mitschnitt steht trotzdem, was die KI sagte."""
    erfunden = "Sehr geehrte Damen und Herren, anbei die Unterlagen zur Sitzung."
    p, llm, injector = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply=erfunden))
    p.process(AUDIO, 16000)
    assert injector.injected and erfunden not in injector.injected[-1]
    aufrufe = aufrufe_von(p)
    assert erfunden in [a.antwort for a in aufrufe]
    assert aufrufe[0].system.startswith("SYSTEM")
    assert aufrufe[0].eingabe == llm.calls[0][1]


def test_pipeline_normalfall():
    p, llm, _ = make_pipeline(RAW_NONTRIVIAL, llm=FakeLLM(reply=CLEAN_NONTRIVIAL))
    p.process(AUDIO, 16000)
    [a] = aufrufe_von(p)
    assert a.antwort == CLEAN_NONTRIVIAL
    assert a.eingabe == llm.calls[0][1] and "rohe text" in a.eingabe


def test_befehlsweg_wird_mitgeschnitten():
    import json
    antwort = json.dumps({"replace_scope": "none", "replacement": "", "append_text": "Hallo."})
    command_llm = FakeLLM(reply=antwort)
    p, _, _ = make_pipeline("Redax, schreib Hallo.", command_llm=command_llm)
    p.process(AUDIO, 16000)
    assert any(a.system == "COMMAND-SYSTEM" and a.antwort == antwort
               for a in aufrufe_von(p))


def test_attrappe_ohne_frist_liefert_nichts():
    assert aufrufe_von(object()) == []


# -- Ablage im Verlauf -----------------------------------------------------------------

def _eintrag(ts, *aufrufe):
    return DictationRecord(ts=ts, raw="roh", cleaned="Sauber.", audio_seconds=1.0,
                           ki=list(aufrufe))


def _aufruf(antwort="Sauber.", system="GROSSER PROMPT"):
    return KiAufruf(anbieter="ollama", modell="gemma3:4b", system=system,
                    eingabe=wrap_transcript("roh"), antwort=antwort, ms=1234)


def test_aufrufe_landen_im_verlauf_und_der_prompt_nur_einmal(tmp_path):
    store = HistoryStore(tmp_path / "h.db")
    store.add(_eintrag(time.time(), _aufruf("A"), _aufruf("B", system="ANDERER")))
    store.add(_eintrag(time.time(), _aufruf("C")))
    eid = store.recent(10)[-1]["id"]
    erste = store.ki_aufrufe(eid)
    assert [a["antwort"] for a in erste] == ["A", "B"]
    assert [a["system"] for a in erste] == ["GROSSER PROMPT", "ANDERER"]
    assert erste[0]["ms"] == 1234 and erste[0]["modell"] == "gemma3:4b"
    with store._connect() as con:
        assert con.execute("SELECT COUNT(*) FROM ki_prompts").fetchone()[0] == 2


def test_loeschen_nimmt_den_ki_austausch_mit(tmp_path):
    store = HistoryStore(tmp_path / "h.db", aufbewahrung_tage=30)
    store.add(_eintrag(time.time(), _aufruf("neu")))   # pflegt die Frist (leer)
    store.add(_eintrag(time.time(), _aufruf("weg")))
    store.add(_eintrag(time.time() - 40 * 86400, _aufruf("alt", system="NUR ALT")))
    assert store.bestand()["ki_aufrufe"] == 3
    store.aufbewahren()
    assert store.bestand()["ki_aufrufe"] == 2
    with store._connect() as con:
        prompts = {z[0] for z in con.execute("SELECT text FROM ki_prompts")}
    assert prompts == {"GROSSER PROMPT"}        # verwaister Prompt ist weg
    weg = store.recent(10)[0]["id"]
    store.delete(weg)
    assert store.bestand()["ki_aufrufe"] == 1
    store.clear()
    assert store.bestand()["ki_aufrufe"] == 0
    with store._connect() as con:
        assert con.execute("SELECT COUNT(*) FROM ki_prompts").fetchone()[0] == 0


def test_bestehende_datenbank_bekommt_die_tabellen(tmp_path):
    pfad = tmp_path / "h.db"
    HistoryStore(pfad)
    with HistoryStore(pfad)._connect() as con:
        con.execute("DROP TABLE ki_aufrufe")
        con.execute("DROP TABLE ki_prompts")
    store = HistoryStore(pfad)
    store.add(_eintrag(time.time(), _aufruf()))
    assert store.bestand()["ki_aufrufe"] == 1


def test_bestand_zaehlt_datei_und_zeilen(tmp_path):
    store = HistoryStore(tmp_path / "h.db")
    store.add(_eintrag(time.time(), _aufruf()))
    b = store.bestand()
    assert b["diktate"] == 1 and b["ki_aufrufe"] == 1 and b["bytes"] > 0


def test_ohne_ki_entsteht_kein_aufruf(tmp_path):
    store = HistoryStore(tmp_path / "h.db")
    store.add(_eintrag(time.time()))
    assert store.ki_aufrufe(store.recent(1)[0]["id"]) == []


def test_speichere_ohne_system_prompt(tmp_path):
    store = HistoryStore(tmp_path / "h.db")
    store.add(_eintrag(time.time(), _aufruf(system="")))
    [a] = store.ki_aufrufe(store.recent(1)[0]["id"])
    assert a["system"] == "" and a["antwort"] == "Sauber."
    assert kiverlauf.SCHEMA.count("CREATE TABLE") == 2


# -- Anzeige ---------------------------------------------------------------------------

def test_groesse_deutsch_formatiert():
    assert groesse_text(0) == "0 KB"
    assert groesse_text(300) == "1 KB"
    assert groesse_text(812 * 1024) == "812 KB"
    assert groesse_text(int(2.4 * 1024 ** 2)) == "2,4 MB"
    assert groesse_text(int(1.1 * 1024 ** 3)) == "1,1 GB"


def test_bestandszeile():
    zeile = bestand_zeile({"bytes": 3 * 1024 ** 2, "diktate": 1234, "ki_aufrufe": 1},
                          90)
    assert zeile == ("Verlauf-Datenbank: 3,0 MB · 1.234 Diktate · 1 KI-Aufruf · "
                     "verschlüsselt · Aufbewahrung 90 Tage")
    assert bestand_zeile({}, 0).endswith("Aufbewahrung unbegrenzt")


def test_dialoge_zeigen_den_austausch(qapp):
    from PySide6.QtWidgets import QPushButton

    from fleech.ui.dialogs import TranscriptDetailDialog
    from fleech.ui.kiaustauschdialog import KiAustauschDialog, kopfzeile

    eintrag = {"id": 1, "ts": time.time(), "cleaned": "Sauber.", "words": 1}
    ohne = TranscriptDetailDialog(eintrag)
    mit = TranscriptDetailDialog(eintrag, ki_anzahl=2)
    def knoepfe(d):
        return [b.text() for b in d.findChildren(QPushButton)]

    assert "KI-Austausch …" not in knoepfe(ohne)
    assert "KI-Austausch …" in knoepfe(mit)

    aufruf = {"nr": 1, "anbieter": "ollama", "modell": "gemma3:4b", "system": "SYS",
              "eingabe": "roh", "antwort": "", "fehler": "Zeitgrenze überschritten",
              "ms": 6100, "abgeschnitten": 0}
    assert kopfzeile(aufruf, 2) == "Aufruf 1 von 2 · gemma3:4b (ollama) · 6,1 s"
    dlg = KiAustauschDialog([aufruf])
    [feld] = dlg._prompt_felder
    assert feld.isHidden()
