"""Vorbereinigung: was ohne Sprachmodell sicher aus dem Rohtext heraus kann.

Fuellwoerter („äh", „ähm", „öh", „öhm", auch gedehnt) entfernt diese Datei
deterministisch, BEVOR das Modell den Text sieht. Der Anlass ist gemessen: Im
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

Eigene Datei, weil `textfilter.py` an seiner Zeilen-Obergrenze steht und weil das
hier keine Qualitaets-PRUEFUNG der Modell-Ausgabe ist, sondern eine Vorbereitung
der Eingabe.
"""

from __future__ import annotations

import re

_FW = r"(?:[äÄ]+h+m*|[öÖ]+h+m*)"
_FW_WORT = re.compile(rf"(?<![\w-]){_FW}(?![\w-])", re.UNICODE)

# Ein Vorkommen samt Umgebung: Komma davor, Leerraum, Fuellwort, Ellipse dahinter,
# Komma dahinter. Bei „Ähm." als eigenem Satz faengt `p` den Punkt.
_TREFFER = re.compile(
    rf"(?P<l>,?)[ \t]*(?<![\w-]){_FW}(?![\w-])(?:\.\.\.|…)?(?P<r>,?)(?P<p>[.!?]*)",
    re.UNICODE)

# Nebensatz-Einleiter: Davor steht im Deutschen grammatisch ein Komma. Steht das
# Fuellwort zwischen zwei Kommas VOR so einem Wort („Ich glaube, ähm, dass …"),
# gehoert das linke Komma zum Satz und bleibt.
_KOMMA_DAVOR = re.compile(
    r"(?:dass|weil|ob|wenn|falls|obwohl|damit|sodass|während|bevor|nachdem|"
    r"sondern|aber|denn|wie|wo|wobei|womit|wodurch|was|wer|welche[rsnm]?|"
    r"deren|dessen|sprich|bzw|beziehungsweise|und\s+zwar)\b",
    re.IGNORECASE | re.UNICODE)

_SATZENDE = ".!?…:"


def _grossschreiben(wort_rest: str) -> str:
    m = re.match(r"([a-zäöüß])(\w*)", wort_rest, re.UNICODE)
    if not m:
        return wort_rest
    if m.group(2)[:1].isupper():  # iPhone, eBay
        return wort_rest
    return m.group(1).upper() + wort_rest[1:]


def entferne_fuellwoerter(text: str) -> tuple[str, int]:
    """(Text ohne äh/ähm/öh/öhm, Anzahl entfernter Fuellwoerter).

    Von links nach rechts, jede Entscheidung auf dem schon bereinigten Text davor:
      Satz-/Textanfang  „Ähm, ich …"        → „Ich …"   (Grossschreibung)
      eigener Satz      „… gut. Ähm. Dann"  → „… gut. Dann"
      vor Satzende      „und dann, ähm."    → „und dann."
      zwischen Kommas   „ist, äh, gut"      → „ist gut"
                        „glaube, ähm, dass" → „glaube, dass" (Nebensatz-Einleiter)
      Komma nur davor   „ähnlich, ähm egal" → „ähnlich, egal"
      ohne Kommas       „müssen äh das"     → „müssen das"
    """
    if not text or not _FW_WORT.search(text):
        return text, 0
    out, n, pos = text, 0, 0
    while True:
        m = _TREFFER.search(out, pos)
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
            # „Und, ähm, wenn …" → „Und wenn …": hinter einer beiordnenden
            # Konjunktion steht kein Komma, auch nicht vor einem Nebensatz.
            letztes = re.findall(r"\w+", davor[-12:])
            beiordnend = bool(letztes) and letztes[-1].lower() in (
                "und", "oder", "aber", "denn", "sondern", "also")
            trenner = ", " if _KOMMA_DAVOR.match(folge) and not beiordnend else " "
        elif l:
            trenner = ", "
        else:
            trenner = " "
        out = davor + trenner + folge
        pos = len(davor) + len(trenner)
    return out.strip(), n
