"""Textbausteine: ein gesprochenes Kuerzel wird zu festem Text.

„Baustein Signatur" → die E-Mail-Signatur, „Baustein Adresse" → die Anschrift.
Deterministisch: Kein Modell sieht oder veraendert den Baustein, er landet Zeichen
fuer Zeichen so im Feld, wie er in den Einstellungen steht.

Bis 5.10 gab es das schon einmal, damals ueber Platzhalter ([[B1]]), die das
Sprachmodell unversehrt durchreichen musste — mit eigener Ueberlebens-Pruefung und
eigenen Fehlerfaellen. Diese Fassung kommt ohne Platzhalter aus: Das Diktat wird an
den Kuerzeln zerlegt, nur die Textstuecke dazwischen gehen einzeln durch die
normale Bereinigung (samt allen Pruefungen), und die Bausteine werden danach
unveraendert dazwischengesetzt. Ein Diktat, das nur aus dem Kuerzel besteht,
braucht gar kein Modell.

Eintraege kommen als rohe Zeilen aus den Einstellungen: „Kuerzel => Text". Ein
„\\n" im Text wird zum Zeilenumbruch (der Zeilen-Editor kennt keine mehrzeiligen
Werte).
"""

from __future__ import annotations

import logging
import re
from typing import Callable

log = logging.getLogger(__name__)

# Zwischen den Woertern eines Kuerzels setzt Whisper gern Komma, Punkt oder
# Bindestrich („Baustein, Signatur." / „Baustein-Signatur"). Hinter dem Kuerzel
# faellt dasselbe mit weg, sonst bliebe ein einsames Satzzeichen stehen.
_LUECKE = r"[\s,.:;!?\-–]+"
_NACHLAUF = r"[\s,.:;!?\-–]*"
# Am Ende eines Textstuecks vor einem Baustein: haengendes Komma/Doppelpunkt weg,
# echte Satzenden („." „!" „?") bleiben.
_HAENGEND = re.compile(r"[\s,;:\-–]+$")


def lies(zeilen) -> list[tuple[str, str]]:
    """Rohzeilen → [(Kuerzel, Text)], laengste Kuerzel zuerst.

    Leeres, Kommentare („#…") und Zeilen ohne „=>" werden uebergangen — eine kaputte
    Zeile darf nie ein Diktat reissen. Laengere Kuerzel stehen vorn: „Baustein
    Adresse Buero" muss vor „Baustein Adresse" greifen."""
    gelesen: list[tuple[str, str]] = []
    gesehen: set[str] = set()
    for zeile in zeilen or []:
        zeile = str(zeile).strip()
        if not zeile or zeile.startswith("#") or "=>" not in zeile:
            continue
        kuerzel, _, text = zeile.partition("=>")
        kuerzel = " ".join(kuerzel.split())
        text = text.strip().replace("\\n", "\n")
        if not kuerzel or not text or kuerzel.lower() in gesehen:
            continue
        gesehen.add(kuerzel.lower())
        gelesen.append((kuerzel, text))
    gelesen.sort(key=lambda eintrag: -len(eintrag[0].split()))
    return gelesen


def _muster(kuerzel: str) -> re.Pattern:
    woerter = _LUECKE.join(re.escape(w) for w in kuerzel.split())
    return re.compile(rf"(?<!\w){woerter}(?!\w){_NACHLAUF}", re.IGNORECASE)


def zerlege(roh: str, bausteine: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Diktat → [("text", …) | ("baustein", …)] in Sprechreihenfolge.

    Ohne Treffer genau ein Textstueck — der Aufrufer laeuft dann wie bisher."""
    teile: list[tuple[str, str]] = [("text", roh or "")]
    for kuerzel, wert in bausteine or []:
        muster = _muster(kuerzel)
        neu: list[tuple[str, str]] = []
        for art, inhalt in teile:
            if art != "text":
                neu.append((art, inhalt))
                continue
            rest = 0
            for treffer in muster.finditer(inhalt):
                neu.append(("text", inhalt[rest:treffer.start()]))
                neu.append(("baustein", wert))
                rest = treffer.end()
            neu.append(("text", inhalt[rest:]))
        teile = neu
    # Leere Textstuecke (Kuerzel am Anfang/Ende) und haengende Kommas weg.
    sauber = []
    for art, inhalt in teile:
        if art == "text":
            inhalt = _HAENGEND.sub("", inhalt).strip()
            if not inhalt.strip(" .,;:!?-–"):
                continue
        sauber.append((art, inhalt))
    return sauber


def _naht(links: tuple[str, str], rechts: tuple[str, str]) -> str:
    """Zeilenumbruch neben einem mehrzeiligen Baustein (Signatur), sonst Leerzeichen."""
    mehrzeilig = any(art == "baustein" and "\n" in inhalt
                     for art, inhalt in (links, rechts))
    return "\n" if mehrzeilig else " "


def mit_bausteinen(roh: str, bausteine: list[tuple[str, str]],
                   fertig: Callable[[str], str],
                   bereinige: Callable[[str], tuple[str, bool]]) -> tuple[str, bool]:
    """Bereinigen mit Textbausteinen. (Text, ueber einen Rueckfall?)

    `bereinige(text)` ist die normale Bereinigung (Modell + Pruefungen),
    `fertig(text)` die letzte Stufe (Woerterbuch, gesprochene Zeichen). Beide
    laufen nur ueber die Textstuecke — ein Baustein bleibt, wie er eingetragen ist.
    """
    teile = zerlege(roh, bausteine)
    if all(art == "text" for art, _ in teile):
        text, rueckfall = bereinige(roh)
        return fertig(text), rueckfall

    rueckfall = False
    fertige: list[tuple[str, str]] = []
    for art, inhalt in teile:
        if art == "text":
            text, fb = bereinige(inhalt)
            rueckfall = rueckfall or fb
            text = fertig(text).strip()
            if not text:
                continue
            inhalt = text
        fertige.append((art, inhalt))
    log.info("Textbausteine eingesetzt: %d.", sum(a == "baustein" for a, _ in fertige))
    ergebnis = ""
    for i, teil in enumerate(fertige):
        if i:
            ergebnis += _naht(fertige[i - 1], teil)
        ergebnis += teil[1]
    return ergebnis, rueckfall
