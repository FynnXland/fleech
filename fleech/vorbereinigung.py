"""Vorbereinigung: was ohne Sprachmodell sicher aus dem Rohtext heraus kann.

Fuellwoerter („äh", „ähm", „öh", „öhm", auch gedehnt) entfernt diese Datei
deterministisch, und zwar NACH dem Modell (`Pipeline._cleanup`; warum danach,
steht dort). Der Anlass ist gemessen: Im
Verlauf standen 751 solcher Fuellwoerter in den Rohtexten, und seit dem 30.07.
hat das Modell von 564 nur 14 entfernt — die Regel in `prompts/cleanup.md` wirkt
schlicht nicht. Die Regel hier traf auf ALLEN 1926 Rohtexten jedes dieser Woerter
und kein einziges echtes Wort (geprueft: „ähnlich", „während", „ungefähr",
„Fähigkeit", „höher" u. a. bleiben; die Wortfolge ist bis auf die Fuellwoerter
identisch).

Bewusst NICHT entfernt, mit Beleg aus dem Verlauf:
  - „eh" (21×): jedes Mal im Sinn von „ohnehin"
  - „um" (~280×): die Praeposition
  - „hm"/„Mh" (8×): teils als Frage-Anhaengsel („…, hm?")
  - „ah"/„oh" (~90×): Ausrufe

Englisch (seit 6.4.1, nur bei Diktiersprache Englisch): „um", „uh", „uhm", „erm".
gemma3:4b-text liess sie trotz Prompt-Regel in 3 von 10 Testsaetzen stehen. „like"
und „so" bleiben — das sind meist echte Woerter.

Das Komma vor dem Fuellwort (6.4.1): Whisper setzt um fast jedes „äh" zwei
Kommas, meist mitten im Satz („ist, äh, gut") — beide fallen. Gehoert das linke
aber zum Satz, bleibt es (`_linkes_komma_bleibt`). Gemessen an den 831 Stellen
„, äh," in 2369 Rohtexten des Verlaufs: 79 behalten es wie bisher wegen eines
Nebensatz-Einleiters rechts, 27 neu wegen der linken Seite („Okay, …", „…, damit
ich das testen kann, er …"). Davon 17 klar richtig, 7 beides moeglich (Komma vor
„und" + Hauptsatz), 3 strittig (nachgestelltes Glied: „…, dass man den
Unterschied sieht, an der Textur"); kein klarer Fehlgriff.

Eigene Datei, weil `textfilter.py` an seiner Zeilen-Obergrenze steht und weil das
hier keine Qualitaets-PRUEFUNG der Modell-Ausgabe ist, sondern eine Vorbereitung
der Eingabe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def _woerter(*zeilen: str) -> frozenset:
    return frozenset(" ".join(zeilen).split())


@dataclass(frozen=True)
class _Sprache:
    wort: re.Pattern            # das Fuellwort allein (Schnelltest)
    treffer: re.Pattern         # samt Kommas, Ellipse, Satzzeichen
    komma_davor: re.Pattern     # rechts davon: Komma gehoert zum Satz
    beiordnend: frozenset       # links davon: nie ein Komma
    ausrufe: frozenset          # Abschnitt nur aus diesen Woertern: „Ja, …"
    gruesse: frozenset          # Satzanfang mit diesem Wort: „Hallo zusammen, …"
    nebensatz: bool             # geschlossenen Nebensatz pruefen (Verb am Ende)


def _muster(fw: str) -> tuple[re.Pattern, re.Pattern]:
    # Ein Vorkommen samt Umgebung: Komma davor, Leerraum, Fuellwort, Ellipse
    # dahinter, Komma dahinter. Bei „Ähm." als eigenem Satz faengt `p` den Punkt.
    return (re.compile(rf"(?<![\w-]){fw}(?![\w-])", re.UNICODE),
            re.compile(rf"(?P<l>,?)[ \t]*(?<![\w-]){fw}(?![\w-])(?:\.\.\.|…)?"
                       rf"(?P<r>,?)(?P<p>[.!?]*)", re.UNICODE))


_DE = _Sprache(
    *_muster(r"(?:[äÄ]+h+m*|[öÖ]+h+m*)"),
    # Nebensatz-Einleiter: Davor steht im Deutschen grammatisch ein Komma
    # („Ich glaube, ähm, dass …" → „Ich glaube, dass …").
    komma_davor=re.compile(
        r"(?:dass|weil|ob|wenn|falls|obwohl|damit|sodass|während|bevor|nachdem|"
        r"sondern|aber|denn|wie|wo|wobei|womit|wodurch|was|wer|welche[rsnm]?|"
        r"deren|dessen|sprich|bzw|beziehungsweise|und\s+zwar)\b",
        re.IGNORECASE | re.UNICODE),
    beiordnend=_woerter("und oder aber denn sondern also"),
    ausrufe=_woerter("ja jo jap jep jaja nein nee nö ne okay ok okey oke naja na",
                     "ach achso aha oh ah hm hmm mhm genau stimmt klar richtig",
                     "gut super perfekt prima cool top alles"),
    gruesse=_woerter("hallo hi hey moin servus hallöchen liebe lieber liebes",
                     "guten sehr grüß"),
    nebensatz=True,
)

_EN = _Sprache(
    *_muster(r"(?:[uU]+h+m*|[uU]+m+|[eE]+r+m+)"),
    komma_davor=re.compile(r"(?:which|whose|although|though|whereas|i\.e\.|e\.g\.)"
                           r"(?!\w)", re.IGNORECASE),
    beiordnend=_woerter("and or but nor so"),
    ausrufe=_woerter("yes yeah yep yup no nope okay ok well right sure alright",
                     "oh ah hmm thanks"),
    gruesse=_woerter("hi hello hey dear good"),
    nebensatz=False,
)

# Geschlossener Nebensatz: Einleiter … Verb, dann das Fuellwort. Im Deutschen steht
# das Verb im Nebensatz am Ende — danach ist er zu, das Komma gehoert zum Satz
# („…, die die Liste sortiert, äh, die neuesten zuerst"). „der/die/das" zaehlen nur
# nach einem Komma (sonst sind es Artikel: „Die Liste, äh, ist …").
_EINLEITER = _woerter("dass weil ob wenn falls obwohl damit sodass während bevor",
                      "nachdem als sobald solange seit seitdem bis indem sofern",
                      "soweit wo was wer welche welcher welches welchen welchem",
                      "deren dessen denen")
_RELATIV = _woerter("der die das den dem")
_HILFSVERB = _woerter(
    "ist sind war waren wäre wären bin bist seid sein hat habe hast haben hatte",
    "hatten hätte hätten kann kannst können könnte könnten muss musst müssen müsste",
    "soll sollst sollen sollte sollten will willst wollen wollte wird wirst werden",
    "wurde wurden würde würden worden darf darfst dürfen dürfte mag möchte möchtest",
    "möchten lassen gibt geht tut weiß")
# Kleingeschriebene Woerter mit Verb-Endung, die keine Verben sind.
_KEIN_VERB = _woerter(
    "nicht nichts jetzt gut recht echt leicht schlecht vielleicht oft erst zuerst",
    "zuletzt zunächst selbst sonst fast halt meist längst zumindest bereits dort",
    "sofort fort spät weit bereit seit laut konkret direkt perfekt korrekt exakt",
    "komplett explizit absolut bestimmt insgesamt heute bitte morgen gestern oben",
    "unten eben neben gegen zwischen wegen innen außen hinten drinnen draußen",
    "zusammen bisschen den einen keinen meinen deinen seinen ihren unseren euren",
    "diesen allen vielen anderen beiden ihnen denen deswegen weswegen dagegen",
    "hingegen entgegen daneben mit samt statt nebst")

_SATZENDE = ".!?…:"


def _grossschreiben(wort_rest: str) -> str:
    m = re.match(r"([a-zäöüß])(\w*)", wort_rest, re.UNICODE)
    if not m:
        return wort_rest
    if m.group(2)[:1].isupper():  # iPhone, eBay
        return wort_rest
    return m.group(1).upper() + wort_rest[1:]


def _ist_verb(wort: str) -> bool:
    if not wort.isalpha() or not wort.islower() or wort in _KEIN_VERB:
        return False
    return wort in _HILFSVERB or bool(re.search(r"(?:en|ern|eln|t|st|te|ten)$", wort))


def _nebensatz_zu(abschnitt: list[str], nach_komma: bool, folge: str) -> bool:
    """Endet `abschnitt` (Woerter seit dem letzten Komma/Satzanfang) einen
    Nebensatz — und faengt `folge` nichts an, das ihn fortsetzt?"""
    erstes = abschnitt[0].lower()
    if not (erstes in _EINLEITER or (nach_komma and erstes in _RELATIV)):
        return False
    if len(abschnitt) < 3 or not _ist_verb(abschnitt[-1]):
        return False
    naechstes = re.match(r"\w+", folge)
    if not naechstes:
        return False
    naechstes = naechstes.group(0)
    # „…, die ich gesehen, äh, habe" / „…, dass wir die neuen, äh, Sachen …"
    return naechstes not in _HILFSVERB and not naechstes[0].isupper()


def _linkes_komma_bleibt(davor: str, folge: str, s: _Sprache) -> bool:
    """Fuellwort zwischen zwei Kommas: gehoert das linke zum Satz?

    Im Zweifel nein — Whisper setzt um fast jedes Fuellwort zwei Kommas, auch
    mitten im Satz („Das ist, äh, gut").
    """
    grenze = max(davor.rfind(z) for z in ",.!?:;\n")
    abschnitt = re.findall(r"[\w'-]+", davor[grenze + 1:], re.UNICODE)
    if not abschnitt:
        return False
    klein = [w.lower() for w in abschnitt]
    if klein[-1] in s.beiordnend:
        # „Und, ähm, wenn …" → „Und wenn …": hinter einer beiordnenden
        # Konjunktion steht kein Komma, auch nicht vor einem Nebensatz.
        return False
    if s.komma_davor.match(folge):
        return True
    if all(w in s.ausrufe for w in klein) and klein != ["alles"]:
        return True                     # „Ja, äh, das passt."
    nach_komma = grenze >= 0 and davor[grenze] == ","
    if not nach_komma and klein[0] in s.gruesse and len(klein) <= 5:
        return True                     # „Hallo zusammen, ähm, ich …"
    return s.nebensatz and _nebensatz_zu(abschnitt, nach_komma, folge)


def entferne_fuellwoerter(text: str, sprache: str = "de") -> tuple[str, int]:
    """(Text ohne Fuellwoerter, Anzahl entfernter Fuellwoerter).

    `sprache` ist die Diktiersprache: „en…" entfernt um/uh/erm, alles andere
    (auch automatisch erkannt) die deutschen äh/ähm/öh/öhm.

    Von links nach rechts, jede Entscheidung auf dem schon bereinigten Text davor:
      Satz-/Textanfang  „Ähm, ich …"        → „Ich …"   (Grossschreibung)
      eigener Satz      „… gut. Ähm. Dann"  → „… gut. Dann"
      vor Satzende      „und dann, ähm."    → „und dann."
      zwischen Kommas   „ist, äh, gut"      → „ist gut"
                        „glaube, ähm, dass" → „glaube, dass" (linkes Komma gehoert
                        „Ja, äh, das"       → „Ja, das"       zum Satz:
                                                              `_linkes_komma_bleibt`)
      Komma nur davor   „ähnlich, ähm egal" → „ähnlich, egal"
      ohne Kommas       „müssen äh das"     → „müssen das"
    """
    s = _EN if (sprache or "").lower().startswith("en") else _DE
    if not text or not s.wort.search(text):
        return text, 0
    out, n, pos = text, 0, 0
    while True:
        m = s.treffer.search(out, pos)
        if not m:
            break
        n += 1
        l, r, p = m.group("l"), m.group("r"), m.group("p")
        davor = out[: m.start()].rstrip(" \t")
        danach = out[m.end():]
        folge = danach.lstrip(" \t")
        # Nur echte Satzenden: nach „:" oder einer Denkpause „..." geht der Satz weiter.
        satzanfang = not davor or (davor[-1] in ".!?" and not davor.endswith(".."))
        if satzanfang:
            # Alles weg; das naechste Wort beginnt den Satz.
            kopf = davor + (" " if davor and folge else "")
            if p and not folge:
                kopf = davor  # „Okay. Ähm." am Ende
            out = kopf + _grossschreiben(folge)
            pos = len(kopf)
            continue
        if p or not folge or folge[0] in _SATZENDE + ";)":
            # „…, ähm." → „…." / „…, ähm" am Textende → „…"
            ende = p if p else ""
            out = davor + ende + (" " if folge and ende else "") + folge
            pos = len(davor) + len(ende)
            continue
        if l and r:
            trenner = ", " if _linkes_komma_bleibt(davor, folge, s) else " "
        elif l:
            trenner = ", "
        else:
            trenner = " "
        out = davor + trenner + folge
        pos = len(davor) + len(trenner)
    return out.strip(), n
