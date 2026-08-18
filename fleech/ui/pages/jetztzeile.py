"""„Wenn du jetzt diktierst, passiert das" — eine Zeile, die die Regeln vorführt.

Vorschlag G-2 (Befunde G-B4, G-B7, G-B9): Es gab keinen Ort, an dem man nachsehen
konnte, OB eine App-Zuordnung greift, WELCHE greift und was sie bewirkt. Ein
Tippfehler in einer Titel-Bedingung fiel deshalb nie auf — die Regel griff stumm
einfach nie.

Bewusst ein eigenes Modul ohne Qt: Der Satz ist reine Formulierung ueber
`profiles`, laesst sich damit ohne Fenster pruefen, und die Apps-Seite bleibt die
Seite und wird nicht zusaetzlich zum Texter.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ...profiles import PROFILE_FORMATS, profil_fuer_app, profile_mode, profile_sprache

# Fenstertitel werden lang (ganze Dateipfade, ganze Chat-Eingaben). Fuer die Zeile
# reicht der Anfang — sie soll eine Zeile bleiben und nicht die halbe Seite fuellen.
_MAX_TITEL = 48

_EINGRIFF = {"minimal": "Minimal", "standard": "Standard", "strong": "Stark"}
_SPRACHEN = {"de": "Deutsch", "en": "Englisch", "auto": "automatisch erkannt"}
_FORMATE = dict(PROFILE_FORMATS)


def ist_fleech_selbst(prozess: str) -> bool:
    """Ist das der eigene Prozess? Dann ist der Vordergrund nicht das Diktat-Ziel.

    Wer auf der Apps-Seite steht, hat Fleech im Vordergrund — die Zeile zeigte
    sonst dauerhaft „Fleech.exe" statt der Anwendung, um die es geht."""
    name = (prozess or "").strip().lower()
    if not name:
        return False
    eigen = {"fleech.exe", Path(sys.executable).name.lower()}
    return name in eigen


def _kurz(titel: str) -> str:
    titel = " ".join((titel or "").split())
    if len(titel) <= _MAX_TITEL:
        return titel
    return titel[:_MAX_TITEL - 1].rstrip() + "…"


def _profil_und_herkunft(settings, app: str, titel: str) -> tuple[dict | None, str]:
    """(Profil-Eintrag, woher es kommt) — dieselbe Reihenfolge wie beim Diktat.

    Von Hand gewaehlt sticht die Zuordnung; sonst entscheidet die Regel; sonst
    das Standardprofil. Genau die Reihenfolge, die `_app_profile_overrides`
    spaeter geht — sonst zeigte die Zeile etwas anderes, als passiert.
    """
    prof = settings.profiles
    items = [i for i in (prof.items or []) if isinstance(i, dict)]
    gewaehlt = str(getattr(prof, "active", "") or "")
    if gewaehlt:
        for item in items:
            if str(item.get("name", "")) == gewaehlt:
                return item, "von Hand gewählt"
        return None, "von Hand gewählt, aber gelöscht"
    treffer, regel = profil_fuer_app(items, app, titel)
    if treffer is None:
        return None, ""
    if regel:
        return treffer, f"Regel: {regel}"
    return treffer, "Standardprofil"


def beschreibe_jetzt(settings, app: str, titel: str, fleech_selbst: bool = False) -> str:
    """Ein Satz: Ziel-App, aufgeloestes Profil samt Grund, und was es bewirkt."""
    if not getattr(settings.profiles, "enabled", True):
        return ("Profile sind ausgeschaltet — für jedes Diktat gilt, was unter "
                "Einstellungen → Ausgabe steht.")

    kopf = "Wenn du jetzt diktierst: "
    if fleech_selbst:
        kopf += "(Fleech selbst) · zuletzt " + (app or "keine Anwendung")
    elif app:
        kopf += app
    else:
        return kopf + "keine Anwendung erkennbar."
    if titel:
        kopf += f" · „{_kurz(titel)}“"

    profil, herkunft = _profil_und_herkunft(settings, app, titel)
    if profil is None:
        return kopf + " → kein Profil" + (f" ({herkunft})" if herkunft else "")

    teile = [f"Ausgabe: {_FORMATE.get(profile_mode(profil), 'Diktat (Standard)')}"]
    eingriff = str(profil.get("intervention", "") or "")
    global_eingriff = _EINGRIFF.get(
        str(getattr(settings.output, "intervention", "") or ""), "Standard")
    teile.append("Eingriff: " + (_EINGRIFF.get(eingriff)
                                 or f"wie Einstellungen ({global_eingriff})"))
    sprache = profile_sprache(profil)
    global_sprache = _SPRACHEN.get(
        str(getattr(settings.general, "language", "") or ""), "Deutsch")
    teile.append("Sprache: " + (_SPRACHEN.get(sprache)
                                or f"wie Einstellungen ({global_sprache})"))
    if profil.get("auto_send"):
        # Das Ueberraschendste, was ein Profil tun kann — es drueckt Enter.
        teile.append("schickt direkt ab")

    name = str(profil.get("name", "") or "Profil")
    return (f"{kopf} → Profil {name} ({herkunft})  ·  " + "  ·  ".join(teile))
