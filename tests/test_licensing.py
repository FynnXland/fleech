"""Lizenzschluessel: signiert, offline, faelschungssicher.

Der wichtigste Test hier ist der, der FEHLSCHLAEGT, wenn jemand einen Schluessel
selbst baut: Fleech kennt nur den oeffentlichen Schluessel, mit dem sich pruefen,
aber nicht unterschreiben laesst. Waere das anders, waere die ganze Konstruktion
wertlos.
"""

from datetime import date

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fleech import licensing
from fleech.licensing import LicenseState, sign_payload, verify


@pytest.fixture
def paar():
    privat = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    oeffentlich = privat.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw).hex()
    return privat, oeffentlich


def test_ausgestellter_schluessel_ist_gueltig(paar):
    privat, oeffentlich = paar
    key = sign_payload(privat, "Max Mustermann")
    zustand = verify(key, oeffentlich)
    assert zustand.ok
    assert zustand.name == "Max Mustermann"
    assert zustand.unlimited


def test_fremd_signierter_schluessel_wird_abgelehnt(paar):
    """Jemand mit einem EIGENEN Schluesselpaar kann keine gueltige Lizenz bauen."""
    _, oeffentlich = paar
    fremd = Ed25519PrivateKey.generate()
    zustand = verify(sign_payload(fremd, "Freifahrer"), oeffentlich)
    assert not zustand.ok
    assert "ungültig" in zustand.reason


def test_veraenderter_name_bricht_die_signatur(paar):
    """Nutzdaten umschreiben (z. B. auf den eigenen Namen) macht den Schluessel
    ungueltig — Name und Signatur haengen zusammen."""
    import base64
    import json

    privat, oeffentlich = paar
    key = sign_payload(privat, "Max", expires="")
    kopf, daten, sig = key.split(".", 2)
    roh = json.loads(base64.urlsafe_b64decode(daten + "=="))
    roh["n"] = "Jemand anders"
    neu = base64.urlsafe_b64encode(
        json.dumps(roh, separators=(",", ":")).encode()).decode().rstrip("=")
    assert not verify(f"{kopf}.{neu}.{sig}", oeffentlich).ok


def test_ablaufdatum_wird_geprueft(paar):
    privat, oeffentlich = paar
    key = sign_payload(privat, "Befristet", expires="2026-01-01")
    assert verify(key, oeffentlich, heute=date(2025, 12, 31)).ok
    abgelaufen = verify(key, oeffentlich, heute=date(2026, 6, 1))
    assert not abgelaufen.ok
    assert "abgelaufen" in abgelaufen.reason
    assert abgelaufen.name == "Befristet"        # Name bleibt lesbar fuer die Anzeige


def test_ablauf_am_letzten_tag_gilt_noch(paar):
    privat, oeffentlich = paar
    key = sign_payload(privat, "Genau heute", expires="2026-06-01")
    assert verify(key, oeffentlich, heute=date(2026, 6, 1)).ok


def test_muell_und_leeres_werden_sauber_abgelehnt(paar):
    _, oeffentlich = paar
    for eingabe in ("", "   ", "kein schluessel", "FLEECH-1.", "FLEECH-1.abc",
                    "FLEECH-1.###.###"):
        zustand = verify(eingabe, oeffentlich)
        assert not zustand.ok
        assert zustand.reason                    # immer ein Satz, nie stumm


def test_zeilenumbrueche_und_leerzeichen_stoeren_nicht(paar):
    """Der Schluessel wird per Mail/Chat verschickt und dabei umgebrochen."""
    privat, oeffentlich = paar
    key = sign_payload(privat, "Max")
    zerlegt = key[:40] + "\n  " + key[40:80] + " \r\n" + key[80:]
    assert verify(zerlegt, oeffentlich).ok


def test_hinterlegter_oeffentlicher_schluessel_ist_echt():
    """Der Wert in licensing.py muss ein echter Ed25519-Punkt sein — ein
    Platzhalter wuerde die Pruefung stillschweigend abschalten."""
    assert licensing.PUBLIC_KEY_HEX != "__PLATZHALTER__"
    assert len(bytes.fromhex(licensing.PUBLIC_KEY_HEX)) == 32


def test_ohne_hinterlegten_schluessel_wird_nicht_gesperrt():
    """Entwicklungsbaum ohne Schluessel: arbeitsfaehig bleiben, aber im Log warnen.
    Sperren waere hier nur laestig — ausgeliefert wird immer mit Schluessel."""
    zustand = verify("FLEECH-1.abc.def", "__PLATZHALTER__")
    assert zustand.ok


def test_check_liest_die_einstellungen(paar):
    privat, oeffentlich = paar
    from fleech.usersettings import UserSettings

    s = UserSettings()
    assert not licensing.check(s).ok              # frisch = gesperrt
    s.general.license_key = sign_payload(privat, "Max")
    # Gegen den ECHTEN hinterlegten Schluessel muss ein fremd signierter scheitern.
    assert not licensing.check(s).ok


def test_state_unlimited_nur_bei_gueltig():
    assert not LicenseState(False).unlimited
    assert LicenseState(True).unlimited
    assert not LicenseState(True, expires="2030-01-01").unlimited


# -- Dialog-Modus (die Datei „Schluessel erstellen.bat" ruft genau diesen Weg) ------


@pytest.fixture
def _issue_key(monkeypatch, paar):
    """`issue_key` importierbar machen und auf ein Test-Schluesselpaar umbiegen."""
    import sys
    from pathlib import Path

    privat, oeffentlich = paar
    wurzel = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(wurzel / "packaging"))
    import issue_key

    monkeypatch.setattr(issue_key, "_laden", lambda: privat)
    monkeypatch.setattr(issue_key, "PUBLIC_KEY_HEX", oeffentlich)
    # Die Zwischenablage im Test nicht anfassen — sie gehoert dem Menschen davor.
    monkeypatch.setattr(issue_key, "_in_zwischenablage", lambda text: False)
    return issue_key, oeffentlich


def _dialog(issue_key, monkeypatch, capsys, eingaben):
    it = iter(eingaben)
    monkeypatch.setattr("builtins.input", lambda *_a: next(it))
    code = issue_key._frage_interaktiv()
    return code, capsys.readouterr().out


def test_dialog_stellt_unbefristeten_schluessel_aus(_issue_key, monkeypatch, capsys):
    issue_key, oeffentlich = _issue_key
    code, aus = _dialog(issue_key, monkeypatch, capsys, ["Max Mustermann", ""])
    assert code == 0
    assert "unbefristet" in aus
    schluessel = next(z for z in aus.splitlines() if z.startswith("FLEECH-1."))
    zustand = verify(schluessel, oeffentlich)
    assert zustand.ok and zustand.name == "Max Mustermann"


def test_dialog_uebernimmt_umlaute_unveraendert(_issue_key, monkeypatch, capsys):
    """Der Name steckt SIGNIERT im Schluessel — eine kaputte Konsolen-Kodierung
    ergaebe einen Schluessel auf einen Namen, den niemand so schreibt."""
    issue_key, oeffentlich = _issue_key
    code, aus = _dialog(issue_key, monkeypatch, capsys, ["Jürgen Groß", ""])
    schluessel = next(z for z in aus.splitlines() if z.startswith("FLEECH-1."))
    assert code == 0
    assert verify(schluessel, oeffentlich).name == "Jürgen Groß"


def test_dialog_befristet_auf_tage(_issue_key, monkeypatch, capsys):
    from datetime import timedelta

    issue_key, oeffentlich = _issue_key
    code, aus = _dialog(issue_key, monkeypatch, capsys, ["Max", "365"])
    schluessel = next(z for z in aus.splitlines() if z.startswith("FLEECH-1."))
    assert code == 0
    zustand = verify(schluessel, oeffentlich)
    assert zustand.ok
    assert zustand.expires == (date.today() + timedelta(days=365)).isoformat()


@pytest.mark.parametrize("eingaben,erwartet", [
    ([""], "Kein Name"),                       # nichts eingetippt
    (["   ", ], "Kein Name"),                  # nur Leerzeichen
    (["Max", "bald"], "keine Anzahl Tage"),    # Wort statt Zahl
    (["Max", "0"], "keine Anzahl Tage"),       # 0 Tage waere sofort abgelaufen
    (["Max", "-5"], "keine Anzahl Tage"),
])
def test_dialog_bricht_bei_unsinn_ab_ohne_schluessel(_issue_key, monkeypatch, capsys,
                                                    eingaben, erwartet):
    """Lieber abbrechen als einen Schluessel ausstellen, der nicht gemeint war —
    einmal verschickt bekommt man ihn nicht zurueck (es gibt keine Sperrliste)."""
    issue_key, _oeffentlich = _issue_key
    code, aus = _dialog(issue_key, monkeypatch, capsys, eingaben)
    assert code == 1
    assert erwartet in aus
    assert "FLEECH-1." not in aus


def test_dialog_meldet_fehlenden_signaturschluessel(_issue_key, monkeypatch, capsys):
    issue_key, _oeffentlich = _issue_key
    monkeypatch.setattr(issue_key, "_laden", lambda: None)
    code, aus = _dialog(issue_key, monkeypatch, capsys, ["Max", ""])
    assert code == 1
    assert "Kein privater Signaturschluessel" in aus
    assert "FLEECH-1." not in aus


# -- Ladefehler richtig einordnen ------------------------------------------------------


def test_gesunde_datei_wird_als_gesund_erkannt(_issue_key):
    """Real passiert: Das Laden scheiterte bei voellig intakter Datei (die
    Krypto-Bibliothek wurde im Nebenlauf gerade von PyInstaller eingepackt). Der
    rohe Traceback las sich wie „dein Signaturschluessel ist zerstoert" — die
    teuerste Fehldiagnose, die dieses Programm anbieten kann."""
    issue_key, _oeff = _issue_key

    # WEGWERF-Schluessel, eigens fuer diesen Test erzeugt und nirgends sonst
    # verwendet. Hier NIE echtes Schluesselmaterial einsetzen: Ein Test wird
    # committet, und damit stuende das Geheimnis dauerhaft in der Historie —
    # genau das ist beim Schreiben dieses Tests einmal passiert.
    echt = (b"-----BEGIN PRIVATE KEY-----\n"
            b"MC4CAQAwBQYDK2VwBCIEIIzirvgOnS8y0+AKi1o+Ag+OrGfqw/0EIGboInluATyx\n"
            b"-----END PRIVATE KEY-----\n")
    assert issue_key._sieht_gesund_aus(echt)
    assert issue_key._sieht_gesund_aus(echt.replace(b"\n", b"\r\n"))   # Windows


@pytest.mark.parametrize("kaputt", [
    b"",
    b"   \n",
    b"-----BEGIN PRIVATE KEY-----\n",                    # abgeschnitten
    b"MC4CAQAwBQYDK2VwBCIEIMqS6VDErxtC7GWCnyBF83IQ\n",   # nur der Rumpf
    b"\x00\x00\x00\x00",
])
def test_kaputte_datei_wird_als_kaputt_erkannt(_issue_key, kaputt):
    issue_key, _oeff = _issue_key
    assert not issue_key._sieht_gesund_aus(kaputt)


def test_laden_wiederholt_bevor_es_aufgibt(monkeypatch, tmp_path, capsys):
    """Ein voruebergehender Fehler darf nicht sofort zum Abbruch fuehren."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
    import issue_key

    datei = tmp_path / "key.pem"
    datei.write_bytes(b"-----BEGIN PRIVATE KEY-----\nMC4=\n-----END PRIVATE KEY-----\n")
    monkeypatch.setattr(issue_key, "KEY_PATH", datei)
    monkeypatch.setattr("time.sleep", lambda _s: None)

    versuche = []

    def flaky(roh, password=None):
        versuche.append(1)
        if len(versuche) < 3:
            raise ValueError("MalformedFraming")
        return "geladen"

    monkeypatch.setattr(
        "cryptography.hazmat.primitives.serialization.load_pem_private_key", flaky)
    assert issue_key._laden() == "geladen"
    assert len(versuche) == 3


def test_dauerfehler_meldet_dass_nichts_verloren_ist(monkeypatch, tmp_path, capsys):
    """Bleibt es beim Fehler, MUSS dastehen, dass die Datei in Ordnung ist —
    sonst stellt jemand in Panik ein neues Schluesselpaar aus und entwertet damit
    alle bereits verschickten Lizenzen."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
    import issue_key

    datei = tmp_path / "key.pem"
    datei.write_bytes(b"-----BEGIN PRIVATE KEY-----\nMC4=\n-----END PRIVATE KEY-----\n")
    monkeypatch.setattr(issue_key, "KEY_PATH", datei)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setattr(
        "cryptography.hazmat.primitives.serialization.load_pem_private_key",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("MalformedFraming")))

    with pytest.raises(SystemExit):
        issue_key._laden()
    aus = capsys.readouterr().out
    assert "NICHTS verloren" in aus
    assert "nochmal" in aus
    assert "--init" not in aus          # NICHT zum Neuausstellen raten


def test_fehlende_datei_bleibt_ein_stiller_none(monkeypatch, tmp_path):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))
    import issue_key

    monkeypatch.setattr(issue_key, "KEY_PATH", tmp_path / "gibtsnicht.pem")
    assert issue_key._laden() is None
