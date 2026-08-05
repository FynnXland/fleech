"""Wörterbuch-Einträge einsprechen und prüfen.

Man trägt ein Wort ein und weiß nicht, ob es etwas gebracht hat — bis es mitten
im Diktat wieder falsch dasteht. Der Test macht daraus eine Frage von zehn
Sekunden.
"""

import numpy as np
import pytest

from fleech.wortprobe import Ergebnis, bewerte, pruefe_audio

SR = 16000


def audio(sekunden: float = 1.0):
    return np.zeros(int(SR * sekunden), dtype=np.float32)


# -- Bewertung ---------------------------------------------------------------------------


def test_exakter_treffer():
    p = bewerte("Ich nutze PySide6 dafür", "PySide6")
    assert p.ergebnis == Ergebnis.TREFFER
    assert p.geglueckt


def test_wort_allein_gesprochen():
    assert bewerte("PySide6", "PySide6").ergebnis == Ergebnis.TREFFER


def test_satzzeichen_stoeren_nicht():
    """Whisper hängt fast immer einen Punkt an."""
    assert bewerte("PySide6.", "PySide6").ergebnis == Ergebnis.TREFFER


def test_mehrwortiger_begriff():
    assert bewerte("der MCP Server läuft", "MCP Server").ergebnis == Ergebnis.TREFFER


def test_aehnlich_ist_nicht_dasselbe_wie_treffer():
    """Die Unterscheidung ist der Kern: „fast" heißt üben oder Variante eintragen,
    „exakt" heißt fertig. Beides als Erfolg zu zeigen wäre eine Lüge."""
    p = bewerte("Kimunno", "Kimono")
    assert p.ergebnis == Ergebnis.AEHNLICH
    assert not p.geglueckt


def test_etwas_ganz_anderes():
    p = bewerte("Pi Seite sechs", "PySide6")
    assert p.ergebnis == Ergebnis.DANEBEN
    assert not p.geglueckt


def test_nichts_gehoert():
    assert bewerte("", "PySide6").ergebnis == Ergebnis.NICHTS
    assert bewerte("irgendwas", "").ergebnis == Ergebnis.NICHTS


# -- Der Vorschlag ist der eigentliche Nutzen --------------------------------------------


def test_daneben_liefert_eine_fertige_woerterbuch_zeile():
    """Nicht „hat nicht geklappt", sondern die Regel, die es beim nächsten Mal
    richtig macht."""
    p = bewerte("Ollama.", "Olama")
    assert p.ergebnis == Ergebnis.DANEBEN
    assert p.vorschlag == "Ollama => Olama"


def test_kein_vorschlag_bei_ganzen_saetzen():
    """Bei mehreren Wörtern wüsste niemand, welcher Teil ersetzt werden soll."""
    p = bewerte("ich nutze pi seite sechs", "PySide6")
    assert p.ergebnis == Ergebnis.DANEBEN
    assert p.vorschlag == ""


def test_kein_vorschlag_bei_treffer():
    assert bewerte("PySide6", "PySide6").vorschlag == ""


@pytest.mark.parametrize("ergebnis_text", [
    Ergebnis.TREFFER, Ergebnis.AEHNLICH, Ergebnis.DANEBEN, Ergebnis.NICHTS,
])
def test_jedes_ergebnis_hat_einen_satz_fuer_die_oberflaeche(ergebnis_text):
    from fleech.wortprobe import Probe

    text = Probe(ergebnis_text, "irgendwas", "Begriff").als_text()
    assert text and len(text) > 10


# -- Der Weg über Audio -------------------------------------------------------------------


def test_audio_wird_erkannt_und_bewertet():
    p = pruefe_audio(audio(1.0), "PySide6", lambda a: "PySide6", samplerate=SR)
    assert p.ergebnis == Ergebnis.TREFFER


def test_zu_kurze_aufnahme_gilt_als_nichts():
    """Aus kurzen Fetzen halluziniert Whisper zuverlässig Unsinn — den würde man
    sonst als „daneben" werten und eine sinnlose Regel vorschlagen."""
    p = pruefe_audio(audio(0.2), "PySide6", lambda a: "Achtung", samplerate=SR)
    assert p.ergebnis == Ergebnis.NICHTS


def test_leeres_audio():
    assert pruefe_audio(None, "X", lambda a: "X").ergebnis == Ergebnis.NICHTS
    assert pruefe_audio(audio(0), "X", lambda a: "X").ergebnis == Ergebnis.NICHTS


def test_fehler_in_der_erkennung_reisst_nichts_mit():
    def kaputt(_a):
        raise RuntimeError("Modell weg")

    p = pruefe_audio(audio(1.0), "PySide6", kaputt, samplerate=SR)
    assert p.ergebnis == Ergebnis.NICHTS


# -- Verdrahtung in der App --------------------------------------------------------------


def test_laufendes_diktat_hat_vorrang():
    """Zwei Aufnahmen auf demselben Mikrofon waeren ein Geraetekonflikt — und das
    laufende Diktat ist wichtiger als ein Test."""
    import types

    from fleech.ui.desktop import DesktopApp

    gestartet = []
    fake = types.SimpleNamespace(
        controller=types.SimpleNamespace(active=True),
        recorder=types.SimpleNamespace(start=lambda: gestartet.append(1)),
    )
    p = DesktopApp.wortprobe(fake, "PySide6", sekunden=0.5)
    assert p.ergebnis == Ergebnis.NICHTS
    assert gestartet == [], "Aufnahme trotz laufendem Diktat gestartet"


def test_probe_nutzt_das_woerterbuch_priming():
    """Ohne den `initial_prompt` wuerde der Test messen, wie gut Whisper das Wort
    OHNE Wörterbuch versteht — also das Gegenteil der Frage."""
    import types

    from fleech.ui.desktop import DesktopApp

    gesehen = {}

    def transcribe(audio, rate, initial_prompt=None):
        gesehen["prompt"] = initial_prompt
        return "PySide6"

    class Lock:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake = types.SimpleNamespace(
        pipeline=types.SimpleNamespace(
            _stt_lock=Lock(), _vocab_prompt="Begriffe: PySide6.",
            stt=types.SimpleNamespace(transcribe=transcribe)),
        config=types.SimpleNamespace(audio=types.SimpleNamespace(samplerate=SR)),
    )
    text = DesktopApp._erkenne_probe(fake, audio(1.0))
    assert text == "PySide6"
    assert gesehen["prompt"] == "Begriffe: PySide6."


def test_dialog_zeigt_ergebnis_und_bietet_die_variante_an(qapp):
    from fleech.ui.dialogs import WortprobeDialog
    from fleech.wortprobe import bewerte

    dlg = WortprobeDialog("Olama", lambda b, s, z=None: bewerte("Ollama.", b))
    assert dlg._uebernehmen_btn.isHidden()
    dlg._starten()
    assert "Ollama" in dlg._meldung.text()
    assert dlg.vorschlag == "Ollama => Olama"
    assert not dlg._uebernehmen_btn.isHidden(), "Vorschlag wird nicht angeboten"
    dlg.deleteLater()


def test_dialog_bei_treffer_ohne_variante(qapp):
    from fleech.ui.dialogs import WortprobeDialog
    from fleech.wortprobe import bewerte

    dlg = WortprobeDialog("PySide6", lambda b, s, z=None: bewerte("PySide6", b))
    dlg._starten()
    assert "greift" in dlg._meldung.text()
    assert dlg.vorschlag == ""
    assert dlg._uebernehmen_btn.isHidden()
    dlg.deleteLater()


def test_dialog_ueberlebt_einen_fehler_bei_der_aufnahme(qapp):
    from fleech.ui.dialogs import WortprobeDialog

    def kaputt(_b, _s):
        raise OSError("Mikrofon belegt")

    dlg = WortprobeDialog("X", kaputt)
    dlg._starten()                      # darf nicht werfen
    assert "nicht möglich" in dlg._meldung.text()
    assert dlg._start_btn.isEnabled(), "Knopf bleibt tot — kein zweiter Versuch möglich"
    dlg.deleteLater()


# -- Startwort-Probe (Freihand) ----------------------------------------------------------


def test_startwort_zaehlt_aehnlich_als_erfolg():
    """DER Unterschied zum Wörterbuch: Freihand vergleicht bewusst unscharf, weil
    das Prüfmodell Wörter zerreisst („Kimu", „Gimo", „Kimo no" — alle echt).
    Wenn Freihand darauf startet, muss die Probe „geht" sagen, nicht „fast"."""
    from fleech.wortprobe import Ergebnis, bewerte

    probe = bewerte("Kimu", "Kimono", zweck="startwort")
    assert probe.ergebnis == Ergebnis.AEHNLICH
    assert probe.geglueckt is True
    assert "würde starten" in probe.als_text()

    # Fürs Wörterbuch bleibt dasselbe Ergebnis eine Aufforderung zum Üben.
    woerterbuch = bewerte("Kimu", "Kimono")
    assert woerterbuch.geglueckt is False
    assert "Fast" in woerterbuch.als_text()


def test_startwort_daneben_nennt_die_konsequenz():
    """„Hat nicht geklappt" hilft niemandem — es muss dastehen, was zu tun ist."""
    from fleech.wortprobe import Ergebnis, bewerte

    probe = bewerte("Vielen Dank.", "Kimono", zweck="startwort")
    assert probe.ergebnis == Ergebnis.DANEBEN
    assert probe.geglueckt is False
    text = probe.als_text()
    assert "NICHT" in text and "kein gutes Startwort" in text


def test_startwort_bietet_keine_woerterbuch_regel_an():
    """Ein Startwort repariert man nicht per Ersetzungsregel — man wählt ein
    anderes. Ein „eintragen"-Knopf wäre hier schlicht falsch."""
    from fleech.wortprobe import bewerte

    assert bewerte("Kino", "Kimono", zweck="startwort").vorschlag == ""
    # Fürs Wörterbuch ist genau das der Sinn der Sache.
    assert bewerte("Kino", "Kimono").vorschlag == "Kino => Kimono"


def test_startwort_probe_nutzt_den_laufenden_erkenner():
    """Nicht den Diktat-Weg: Der hört ungleich besser. Ein Test, der besteht,
    während der Alltag scheitert, ist schlimmer als keiner."""
    import types

    from fleech.ui.desktop import DesktopApp

    gerufen = []
    lauscher = types.SimpleNamespace(
        erkenner=lambda audio: gerufen.append("freihand") or "Kimono")
    fake = types.SimpleNamespace(_freihand=types.SimpleNamespace(lauscher=lauscher))
    assert DesktopApp._erkenne_startwort(fake, np.zeros(16000, dtype=np.float32)) == "Kimono"
    assert gerufen == ["freihand"]


def test_startwort_probe_pausiert_freihand():
    """Sonst löst die Probe das eigene Startwort aus — mitten im Test, auf
    demselben Mikrofon."""
    import inspect

    from fleech.ui.desktop import DesktopApp

    quelle = inspect.getsource(DesktopApp.wortprobe)
    assert "pausiere(True)" in quelle and "pausiere(False)" in quelle
    assert quelle.index("pausiere(True)") < quelle.index("recorder.start()")


def test_dialog_fuer_startwort_bietet_kein_eintragen(qapp):
    from fleech.ui.dialogs import WortprobeDialog
    from fleech.wortprobe import bewerte

    dlg = WortprobeDialog(
        "Kimono", lambda b, s, z: bewerte("Kino", b, z), zweck="startwort")
    dlg._starten()
    assert "NICHT" in dlg._meldung.text()
    assert dlg._uebernehmen_btn.isHidden()
    assert dlg.vorschlag == ""
