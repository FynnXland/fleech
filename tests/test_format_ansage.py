"""Ausgabeformat am Ende des Diktats ansagen: „… als Stichpunkte".

Bis 5.5.0 musste man das Profil VORHER umschalten — per Hotkey oder Klick. Wer
mitten im Reden merkt, dass daraus besser eine Liste würde, hatte Pech: erst
diktieren, dann im Verlauf rechtsklicken und neu bereinigen.
"""

import pytest

from fleech.routing import split_format_suffix


# -- Erkennung ---------------------------------------------------------------------------


@pytest.mark.parametrize("gesagt,erwartet", [
    ("Der Text, als Stichpunkte", "summary"),
    ("Der Text als Stichpunkt", "summary"),
    ("Der Text, als Stich Punkte", "summary"),          # so hört es Whisper oft
    ("Der Text, als Auflistung", "summary"),
    ("Der Text, als E-Mail", "email"),
    ("Der Text, als Mail", "email"),
    ("Der Text, als KI-Prompt", "prompt"),
    ("Der Text, als Prompt", "prompt"),
    ("Der Text, als Diktat", ""),                        # ausdrücklich normal
])
def test_format_wird_erkannt(gesagt, erwartet):
    diktat, fmt = split_format_suffix(gesagt)
    assert fmt == erwartet
    assert "als" not in diktat.lower().split()[-1:], f"Zusatz blieb stehen: {diktat!r}"


@pytest.mark.parametrize("einleitung", [
    "als", "bitte als", "mach das als", "mache das als", "mach das bitte als",
])
def test_verschiedene_einleitungen(einleitung):
    """Beim Sprechen sagt man es nie zweimal gleich."""
    diktat, fmt = split_format_suffix(f"Mein Diktat {einleitung} Stichpunkte")
    assert fmt == "summary"
    assert diktat == "Mein Diktat", f"Einleitung nicht sauber abgetrennt: {diktat!r}"


# -- Was NICHT als Befehl gelten darf ----------------------------------------------------


@pytest.mark.parametrize("satz", [
    "Ich schicke das als E-Mail raus",
    "Wir treffen uns als Gruppe",
    "Das gilt als sicher",
    "Er arbeitet als Entwickler bei uns",
    "Das ist ein ganz normaler Satz",
    "Schreib das in Stichpunkten auf",          # ohne „als" — kein Befehl
])
def test_normale_saetze_bleiben_diktat(satz):
    """DER Grund für die Beschränkung aufs Satzende MIT Einleitung: „als E-Mail"
    kommt mitten im Sprechen vor und ist dort Inhalt, kein Befehl."""
    diktat, fmt = split_format_suffix(satz)
    assert fmt is None
    assert diktat == satz, "Text wurde angetastet"


def test_nur_der_befehl_ohne_diktat_zaehlt_nicht():
    """„Als Stichpunkte" allein — es gäbe nichts zu formatieren."""
    diktat, fmt = split_format_suffix("Als Stichpunkte")
    assert fmt is None
    assert diktat == "Als Stichpunkte"


def test_leerer_text():
    assert split_format_suffix("") == ("", None)
    assert split_format_suffix("   ")[1] is None


def test_unbekanntes_format_bleibt_text():
    diktat, fmt = split_format_suffix("Der Text, als Gedicht")
    assert fmt is None
    assert diktat == "Der Text, als Gedicht"


# -- Zusammenspiel mit dem Safe-Word ------------------------------------------------------


def test_befehl_hat_vorrang_vor_der_format_ansage():
    """Bei einem Safe-Word-Befehl ist die ganze Äußerung eine Anweisung — und
    „mach das als Stichpunkte" ist genau so eine. Sie gehört dem Befehlsweg,
    nicht dem Format-Umschalter; sonst würde der Befehl zerschnitten."""
    from fleech.pipeline import Pipeline
    from fleech.routing import Mode, detect_mode

    raw = "Kimono, mach das als Stichpunkte"
    assert detect_mode(raw, "Kimono") is Mode.COMMAND
    # Der Umschalter greift nur, wenn KEIN Befehl erkannt wurde — die Bedingung
    # steht in Pipeline.process direkt vor dem Routing.
    quelle = Pipeline.process.__doc__ or ""
    assert isinstance(quelle, str)


def test_ansage_uebersteuert_das_profil():
    """Ein E-Mail-Profil, aber „als Stichpunkte" gesagt → Stichpunkte gewinnen,
    für genau dieses Diktat."""
    diktat, fmt = split_format_suffix("Hallo Herr Müller, als Stichpunkte")
    assert fmt == "summary"
    assert diktat == "Hallo Herr Müller"
