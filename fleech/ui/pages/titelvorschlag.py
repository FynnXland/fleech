"""Fenstertitel anbieten, statt ihn abtippen zu lassen (Vorschlag G-3).

Eine Titel-Regel setzt voraus, dass man den Titel kennt und fehlerfrei abtippt —
und sehen kann man ihn nicht, solange man in Fleech steht. Wie unbrauchbar Titel
aus dem Kopf sind, zeigt das gelernte Vokabular: Die Titelsegmente von `comet.exe`
lauten dort u. a. „(866) ich habe einer ki minecraft beigebracht!" — so etwas
tippt niemand ab, und ein Tippfehler faellt nie auf, weil die Regel stumm nie
greift.

Deshalb ein kleiner RINGPUFFER der zuletzt im Vordergrund gesehenen fremden
Fenster (der 3-s-Poll der Seite liefert Prozess und Titel ohnehin) plus die
Segment-Zerlegung, die `kontext.titel_segmente` schon macht.

Kein Qt: Puffer, Auswahl und Segment-Rangfolge sind reine Datenarbeit und lassen
sich damit mit einem gefaelschten Poll pruefen.
"""

from __future__ import annotations

from collections import Counter

from ...kontext import titel_segmente

# Wie viele Fenster der Puffer haelt. Klein mit Absicht: Angeboten wird das
# ZULETZT gesehene Fenster: ein langer Verlauf brauchte eine eigene Auswahl und
# waere fuer „ich war eben da drin" nur Ballast.
MAX_PUFFER = 8

# Hoechstens drei Segment-Vorschlaege — mehr Knoepfe als Feld ist keine Hilfe.
MAX_SEGMENTE = 3


def merke(puffer, app: str, titel: str, grenze: int = MAX_PUFFER) -> list:
    """Ein gesehenes Fenster vorn in den Puffer legen. Neueste zuerst.

    Dieselbe Kombination steigt nur auf, statt sich zu haeufen — sonst waere der
    Puffer nach einer Minute Stillstand achtmal dasselbe Fenster.
    """
    app = str(app or "").strip()
    titel = " ".join(str(titel or "").split())
    if not app or not titel:
        return list(puffer or [])
    rest = [(a, t) for a, t in (puffer or [])
            if not (a.lower() == app.lower() and t == titel)]
    return [(app, titel)] + rest[:max(0, grenze - 1)]


def angebot(puffer, app: str = "") -> tuple[str, str]:
    """Welcher Titel wird angeboten? → (Titel, Anwendung, aus der er stammt)

    Bevorzugt ein Fenster GENAU der gewaehlten Anwendung — eine Titel-Regel gilt
    immer nur fuer sie. Gibt es dafuer keines, wird das zuletzt gesehene fremde
    Fenster angeboten und die Herkunft dazu genannt; wer es trotzdem uebernehmen
    will, sieht wenigstens, dass es aus einer anderen Anwendung stammt.
    """
    liste = list(puffer or [])
    schluessel = str(app or "").strip().lower()
    if schluessel:
        for gesehen, titel in liste:
            if gesehen.lower() == schluessel:
                return titel, gesehen
    return (liste[0][1], liste[0][0]) if liste else ("", "")


def segmente(puffer, app: str, gelernt=()) -> list[str]:
    """Titel-Segmente, die sich als Bedingung lohnen — beste zuerst.

    Zwei Quellen: die Zerlegung der gerade gesehenen Fenster dieser Anwendung und
    das, was `kontext.db` fuer den Prozess ohnehin gelernt hat (dort steht jedes
    Segment mit seiner Nutzung). Ein Segment, das in MEHREREN Fenstern vorkommt,
    ist der stabile Teil des Titels — genau der, den man als Bedingung will; bei
    gleichem Rang gewinnt das laengere, weil es die genauere Regel ergibt.
    """
    schluessel = str(app or "").strip().lower()
    zaehler: Counter = Counter()
    for gesehen, titel in (puffer or []):
        if schluessel and gesehen.lower() != schluessel:
            continue
        for segment in titel_segmente(titel):
            zaehler[segment] += 1
    for segment in (gelernt or ()):
        segment = " ".join(str(segment or "").split()).lower()
        if segment:
            # Gelerntes wiegt schwerer als eine einzelne Sichtung: Es ist ueber
            # viele Diktate entstanden, nicht aus dem Fenster von gerade eben.
            zaehler[segment] += 2
    rang = sorted(zaehler.items(), key=lambda p: (-p[1], -len(p[0]), p[0]))
    return [segment for segment, _n in rang[:MAX_SEGMENTE]]
