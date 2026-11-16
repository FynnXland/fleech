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

from ...profiles import (
    PROFILE_FORMATS, profil_fuer_app, profile_mode, profile_sprache, profile_zielsprache,
)
from ...i18n import N_, tr
from ...profiles import anzeigename as profilname
from ...uebersetzung import anzeigename

# Fenstertitel werden lang (ganze Dateipfade, ganze Chat-Eingaben). Fuer die Zeile
# reicht der Anfang — sie soll eine Zeile bleiben und nicht die halbe Seite fuellen.
_MAX_TITEL = 48

_EINGRIFF = {"minimal": N_("Minimal"), "standard": N_("Standard"), "strong": N_("Stark")}
_SPRACHEN = {"de": N_("Deutsch"), "en": N_("Englisch"), "auto": N_("automatisch erkannt")}
# Die Formatnamen stammen aus `profiles.PROFILE_FORMATS` — übersetzt beim Anzeigen.
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
                return item, tr("von Hand gewählt")
        return None, tr("von Hand gewählt, aber gelöscht")
    treffer, regel = profil_fuer_app(items, app, titel)
    if treffer is None:
        return None, ""
    if regel:
        return treffer, tr("Regel: {regel}", regel=regel)
    return treffer, tr("Standardprofil")


def beschreibe_jetzt(settings, app: str, titel: str, fleech_selbst: bool = False) -> str:
    """Ein Satz: Ziel-App, aufgeloestes Profil samt Grund, und was es bewirkt."""
    if not getattr(settings.profiles, "enabled", True):
        return tr("Profile sind ausgeschaltet — für jedes Diktat gilt, was unter "
                  "Einstellungen → KI & Text steht.")

    if fleech_selbst:
        ziel_text = tr("(Fleech selbst) · zuletzt {app}",
                       app=app or tr("keine Anwendung"))
    elif app:
        ziel_text = app
    else:
        return tr("Wenn du jetzt diktierst: keine Anwendung erkennbar.")
    if titel:
        ziel_text += " · " + tr("„{titel}“", titel=_kurz(titel))
    kopf = tr("Wenn du jetzt diktierst: {ziel}", ziel=ziel_text)

    profil, herkunft = _profil_und_herkunft(settings, app, titel)
    if profil is None:
        return kopf + " " + (tr("→ kein Profil ({grund})", grund=herkunft) if herkunft
                             else tr("→ kein Profil"))

    teile = [tr("Ausgabe: {format}", format=tr(
        _FORMATE.get(profile_mode(profil), _FORMATE.get("", "Diktat (Standard)"))))]
    eingriff = str(profil.get("intervention", "") or "")
    global_eingriff = tr(_EINGRIFF.get(
        str(getattr(settings.output, "intervention", "") or ""), _EINGRIFF["standard"]))
    teile.append(tr("Eingriff: {wert}", wert=tr(_EINGRIFF[eingriff]) if eingriff in _EINGRIFF
                    else tr("wie Einstellungen ({wert})", wert=global_eingriff)))
    sprache = profile_sprache(profil)
    global_sprache = tr(_SPRACHEN.get(
        str(getattr(settings.general, "language", "") or ""), _SPRACHEN["de"]))
    teile.append(tr("Sprache: {wert}", wert=tr(_SPRACHEN[sprache]) if sprache in _SPRACHEN
                    else tr("wie Einstellungen ({wert})", wert=global_sprache)))
    ziel = profile_zielsprache(profil)
    if ziel:
        teile.append(tr("übersetzt in: {sprache}", sprache=anzeigename(ziel)))
    if profil.get("auto_send"):
        # Das Ueberraschendste, was ein Profil tun kann — es drueckt Enter.
        teile.append(tr("schickt direkt ab"))

    name = profilname(str(profil.get("name", "") or "")) or tr("Profil")
    return (tr("{kopf} → Profil {name} ({grund})", kopf=kopf, name=name, grund=herkunft)
            + "  ·  " + "  ·  ".join(teile))
