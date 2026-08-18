"""Schreibvarianten desselben Begriffs finden — die Quelle fuer Vokabular-Fragen.

Warum es das gibt (V-14/H-6, Befunde H-B1 und H-B3): Die Vorschlagskarte der
Insights speist sich aus dem Diff „roh gegen bereinigt". Der findet Grammatik
(„kann → koennen"), nicht Eigennamen. Was der Nutzer wirklich braucht, steht
woanders: In 1399 echten Diktaten stand „Cloud-Code" 18-mal und „Claude Code"
10-mal — derselbe Begriff, zwei Schreibweisen, und das Projekt-Gedaechtnis hat
die falsche gelernt und beim naechsten Diktat zurueckgeprimt.

Das Verfahren in drei Schritten:

1. **Kandidaten** sind Woerter mit Eigennamen-Form (Grossbuchstabe, Bindestrich
   oder Ziffer, mindestens fuenf Zeichen) — dazu Paare aus zwei aufeinander
   folgenden grossgeschriebenen Woertern. Ohne diese Paare fiele ausgerechnet der
   Hauptfall durch: „Claude Code" sind zwei Tokens, „Cloud-Code" ist eines.
2. **Verglichen** wird ueber einen Normalschluessel ohne Trennzeichen
   (`cloud-code` und `Cloud Code` sind dieselbe Schreibweise, nur anders
   getrennt) und mit Editier-Distanz <= 2 — bei verschiedenem Anfangsbuchstaben
   nur <= 1.
3. **Gemeldet** wird nur, wenn beide Schreibweisen mindestens zweimal vorkommen,
   mindestens eine davon eine „harte" Eigennamen-Form hat (Binnenversal,
   Bindestrich, Ziffer), und keine die Zusammensetzung der anderen ist
   („KI-Prompt" neben „Prompt" ist kein Fehler).

Diese drei Bedingungen sind am echten Bestand kalibriert (1399 Diktate,
`kontext.db` mit 808 Begriffen). Mit ihnen kommen genau die Fehler heraus, um
die es geht — „Cloud-Code"/„Claude-Code", „Cloud-Design"/„Claude-Design",
„Live-Transkription"/„Live-Transcription". Laesst man eine davon weg, fuellen
sich dieselben Plaetze mit „Datei"/„Daten", „Pille"/„Rolle", „Sachen"/„Machen".
Der Preis ist ein blinder Fleck: Zwei weiche Schreibungen desselben Namens
(„Fleece"/„Fleech") werden nicht gefunden. Das ist bewusst so — eine Karte,
deren erste Frage Unsinn ist, wird nie wieder gelesen.

**Immer Frage, nie Automatik.** Ein Cluster kann echte verschiedene Begriffe
zusammenziehen („MP3-Datei"/„MP4-Datei"). Deshalb liefert dieses Modul eine
Frage mit zwei Haeufigkeiten und keine Entscheidung — und die Oberflaeche fragt,
statt zu ersetzen.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .dictionary import levenshtein

# Mindestlaenge eines Kandidaten. Kuerzere Woerter liegen bei Distanz 2 fast
# zufaellig beieinander („Haus"/„Maus") — dort waere jede Frage Rauschen.
MIN_LAENGE = 5

# Mindestlaenge je Wort in einem Zweiwort-Kandidaten („Claude Code").
MIN_TEIL_LAENGE = 3

# Ab wie vielen Vorkommen eine Schreibweise zaehlt. Einmal-Treffer sind
# ueberwiegend Erkennungsfehler; zweimal dasselbe ist eine Schreibweise.
MIN_VORKOMMEN = 2

# Hoechstabstand innerhalb eines Clusters (dieselbe Schwelle, die das
# selbstlernende Woerterbuch fuer lange Woerter nutzt).
MAX_DISTANZ = 2

# Wortkerne: Buchstaben, Ziffern, Bindestrich, Punkt im Wortinneren.
_WORT = re.compile(r"[A-Za-zÄÖÜäöüß][\wÄÖÜäöüß.\-]{2,}")

# Was im Normalschluessel wegfaellt: Trennzeichen. „MCP-Server", „MCP Server"
# und „MCP_Server" sind dieselbe Schreibweise in drei Schreibungen.
_TRENNER = re.compile(r"[-_.\s]+")

# Deutsche Beugungs-Endungen. Zwei Formen desselben Wortes („Diktate"/
# „Diktaten") sind KEINE Schreibvarianten — danach zu fragen waere Unsinn und
# eine uebernommene Regel wuerde die Beugung kaputt ersetzen.
_ENDUNGEN = ("n", "e", "s", "en", "er", "es", "em", "ne", "ns")


@dataclass(frozen=True)
class Variantenfrage:
    """Zwei Schreibweisen desselben Begriffs mit ihren Haeufigkeiten.

    `haeufig` ist die oefter gesehene Form — sie steht in der Frage vorn, ist
    aber ausdruecklich KEIN Vorschlag: Bei „Cloud-Code 18× · Claude Code 10×"
    ist gerade die haeufigere die falsche.
    """

    haeufig: str
    haeufig_anzahl: int
    selten: str
    selten_anzahl: int


def normalschluessel(wort: str) -> str:
    """Vergleichsform: klein, ohne Trennzeichen."""
    return _TRENNER.sub("", (wort or "").strip().strip(".-,;:!?").lower())


def ist_eigenname_form(wort: str) -> bool:
    """Sieht das Wort nach Eigenname/Fachbegriff aus statt nach normaler Sprache?

    Drei Signale, wie im Projekt-Gedaechtnis (`kontext._ist_fachbegriff`), plus
    der Grossbuchstabe am Wortanfang: Im Deutschen traegt den zwar jedes
    Substantiv, aber die eigentliche Filterung macht ohnehin erst das Cluster —
    ein Wort ohne zweite Schreibweise wird nie gemeldet.
    """
    kern = (wort or "").strip(".-")
    if len(kern) < MIN_LAENGE or kern.isdigit():
        return False
    return kern[:1].isupper() or ist_harte_form(kern)


def ist_harte_form(form: str) -> bool:
    """Binnenversal, Bindestrich oder Ziffer — eine Schreibung, die so nur als
    Fachbegriff oder Eigenname vorkommt.

    Je Wort geprueft, nicht ueber die ganze Form: Sonst waere jedes Zweiwort-Paar
    hart, weil das zweite Wort gross anfaengt („Das Team").
    """
    for teil in str(form or "").split():
        kern = teil.strip(".-")
        if (any(c.isupper() for c in kern[1:]) or "-" in kern
                or any(c.isdigit() for c in kern)):
            return True
    return False


def _nur_beugung(a: str, b: str) -> bool:
    """Unterscheiden sich die beiden nur um eine deutsche Beugungs-Endung?"""
    kurz, lang = sorted((a.lower(), b.lower()), key=len)
    if not lang.startswith(kurz):
        return False
    return lang[len(kurz):] in _ENDUNGEN


def kandidaten_im_text(text: str) -> list[str]:
    """Die Schreibweisen EINES Textes — Einzelwoerter und Zweiwort-Namen.

    Zweiwort-Kandidaten nur bei zwei grossgeschriebenen Nachbarn: „Claude Code"
    ja, „nutzen Kimono" nein. Dass dabei auch harmlose Paare wie „Der Bericht"
    entstehen, ist verkraftbar — gemeldet wird erst, was eine zweite, aehnliche
    Schreibweise HAT und wovon eine Seite hart ist.
    """
    woerter = [w.strip(".-,;:!?") for w in _WORT.findall(str(text or ""))]
    gefunden = [w for w in woerter if ist_eigenname_form(w)]
    for links, rechts in zip(woerter, woerter[1:]):
        if (len(links) >= MIN_TEIL_LAENGE and len(rechts) >= MIN_TEIL_LAENGE
                and links[:1].isupper() and rechts[:1].isupper()):
            gefunden.append(f"{links} {rechts}")
    return gefunden


def zaehle_kandidaten(texte) -> Counter:
    """{Schreibweise: Anzahl} aus fertigen Texten. Je Text zaehlt jede Schreibweise
    nur EINMAL — sonst gewinnt ein einzelnes Diktat, das denselben Begriff
    zwanzigmal nennt, gegen zwanzig Diktate mit der anderen Schreibweise."""
    zaehler: Counter = Counter()
    for text in texte or []:
        for form in set(kandidaten_im_text(text)):
            zaehler[form] += 1
    return zaehler


def zaehle_gedaechtnis(zeilen) -> Counter:
    """{Schreibweise: Anzahl} aus dem Projekt-Gedaechtnis (`kontext.db`).

    `zeilen`: [(begriff, treffer), …] — dort stehen die Varianten samt
    Trefferzahl bereits fertig, das ist die zweite und deutlichere Quelle."""
    zaehler: Counter = Counter()
    for begriff, treffer in zeilen or []:
        kern = str(begriff or "").strip(".-")
        if ist_eigenname_form(kern):
            zaehler[kern] += max(1, int(treffer or 1))
    return zaehler


def finde_varianten(zaehler: Counter, limit: int = 3) -> list[Variantenfrage]:
    """Aus einem Haeufigkeits-Zaehler die Fragen bilden (staerkste zuerst).

    Zusammengefasst wird ueber den Normalschluessel: „Fleech"/„fleech" ist
    dieselbe Schreibweise in zwei Saetzen, „MCP-Server"/„MCP Server" dieselbe
    mit anderem Trennzeichen. Je Begriff wird hoechstens EINE Frage gestellt —
    drei Varianten desselben Wortes wuerden sonst dreimal fragen.
    """
    # Gleiche Schreibweise, andere Gross-/Kleinschreibung oder Trennung:
    # zusammenzaehlen und die haeufigste Form als Vertreter behalten.
    nach_schluessel: dict[str, Counter] = {}
    for wort, anzahl in zaehler.items():
        nach_schluessel.setdefault(normalschluessel(wort), Counter())[wort] += anzahl
    kandidaten = []
    for schluessel, formen in nach_schluessel.items():
        summe = sum(formen.values())
        if schluessel and summe >= MIN_VORKOMMEN:
            kandidaten.append((schluessel, formen.most_common(1)[0][0], summe))
    kandidaten = _ohne_ueberfluessige_paare(kandidaten)
    # Bei gleicher Haeufigkeit gewinnt das Einzelwort: „Die Matrize" und
    # „Matrize" stehen gleich oft da, gefragt werden soll aber nach dem Begriff.
    kandidaten.sort(key=lambda k: (-k[2], " " in k[1], k[0]))

    fragen: list[Variantenfrage] = []
    vergeben: set[str] = set()
    for i, (schl_a, form_a, n_a) in enumerate(kandidaten):
        if schl_a in vergeben:
            continue
        for schl_b, form_b, n_b in kandidaten[i + 1:]:
            if schl_b in vergeben or schl_a == schl_b:
                continue
            if _nur_beugung(schl_a, schl_b) or _ist_zusammensetzung(schl_a, schl_b):
                continue
            # Mindestens EINE Seite muss eine harte Form sein (Binnenversal,
            # Bindestrich, Ziffer). Am echten Bestand nachgemessen (1399 Diktate):
            # Mit dieser Bedingung kommen genau die Fehler heraus, um die es geht
            # — „Cloud-Code"/„Claude-Code", „Cloud-Design"/„Claude-Design",
            # „Live-Transkription"/„Live-Transcription". Ohne sie stehen dieselben
            # Plaetze voller Unsinn: „Datei"/„Daten", „Pille"/„Rolle",
            # „Sachen"/„Machen". Im Deutschen ist jedes Substantiv gross, zwei
            # beliebige davon liegen schnell zwei Schritte auseinander — und eine
            # Karte, deren erste Frage Unsinn ist, wird nie wieder gelesen.
            if not (ist_harte_form(form_a) or ist_harte_form(form_b)):
                continue
            # Zwei Schritte Abstand nur bei gleichem Anfangsbuchstaben. Sonst
            # reicht einer („Kosinus"/„Cosinus"). Auch das ist gemessen: Mit
            # freiem Anfang kamen „Datei"/„LaTeX" und „E-Mail"/„Detail" durch —
            # beides Woerter, die nichts miteinander zu tun haben.
            grenze = MAX_DISTANZ if schl_a[:1] == schl_b[:1] else 1
            if levenshtein(schl_a, schl_b, grenze) > grenze:
                continue
            vergeben.update((schl_a, schl_b))
            fragen.append(Variantenfrage(form_a, n_a, form_b, n_b))
            break
        if len(fragen) >= max(1, limit):
            break
    return fragen[:max(1, limit)]


def _ist_zusammensetzung(a: str, b: str) -> bool:
    """Steckt der eine Schluessel vollstaendig am Anfang oder Ende des anderen?

    Dann ist es eine Zusammensetzung, keine zweite Schreibweise: „KI-Prompt" und
    „Prompt", „AP-Account" und „Account" sind beide richtig, und eine Regel
    daraus wuerde jedes „Prompt" zu „KI-Prompt" machen. Am echten Bestand waren
    das drei der acht staerksten Fundstellen.
    """
    kurz, lang = sorted((a, b), key=len)
    return len(kurz) < len(lang) and (lang.startswith(kurz) or lang.endswith(kurz))


def _ohne_ueberfluessige_paare(kandidaten: list) -> list:
    """Zweiwort-Kandidaten wegwerfen, deren zweites Wort schon fuer sich zaehlt.

    „Die Matrize" kommt genauso oft vor wie „Matrize" — das Paar traegt nichts
    bei und wuerde die Frage nur um ein Fuellwort verlaengern. Uebrig bleiben die
    Paare, die als Ganzes ein Begriff sind („Claude Code": „Code" allein ist zu
    kurz, um Kandidat zu sein).
    """
    einzeln = {schl: n for schl, form, n in kandidaten if " " not in form}
    return [k for k in kandidaten
            if " " not in k[1]
            or not any(k[0] != s and k[0].endswith(s) and k[2] <= n
                       for s, n in einzeln.items())]


def vorschlaege(store, gedaechtnis=None, diktate: int = 300,
                limit: int = 3) -> list[Variantenfrage]:
    """Die fertigen Fragen aus Verlauf UND Projekt-Gedaechtnis.

    Fehler sind hier kein Ereignis: Eine ausgefallene Auswertung kostet einen
    Vorschlag, nicht ein Diktat — deshalb faellt sie still auf „nichts zu
    fragen" zurueck.
    """
    zaehler: Counter = Counter()
    try:
        zaehler += zaehle_kandidaten(store.recent_cleaned(limit=diktate))
    except Exception:
        pass
    if gedaechtnis is not None:
        try:
            zaehler += zaehle_gedaechtnis(gedaechtnis.alle_begriffe())
        except Exception:
            pass
    return finde_varianten(zaehler, limit=limit)
