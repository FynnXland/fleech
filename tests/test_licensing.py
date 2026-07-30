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
