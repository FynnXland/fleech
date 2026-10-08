"""Gesprochene Mathematik → LaTeX, deterministisch und ohne Modell.

Warum ueberhaupt ohne Modell? Weil Formeln die einzige Textsorte sind, bei der ein
Sprachmodell strukturell im Nachteil ist: „x hoch zwei" hat genau EINE richtige
Uebersetzung, und Raten ist dort nicht Kreativitaet, sondern Fehler. Ein Parser ist
schneller (kein Roundtrip), reproduzierbar und kann nichts erfinden.

Der Konverter laeuft VOR dem Cleanup. Erkannte Formeln werden — wie Textbausteine —
durch Platzhalter ersetzt; das Sprachmodell bekommt sie also nie zu sehen und kann
sie weder umformulieren noch zerschreiben. Erst nach allen Ausgabe-Pruefungen tritt
das fertige LaTeX an die Stelle des Platzhalters.

UMGANG MIT MEHRDEUTIGKEIT: Gesprochene Mathematik hat keine Klammern. „Wurzel aus x
Quadrat plus c" kann √(x²)+c oder √(x²+c) heissen — die Pause, die es entscheiden
wuerde, ist im Transkript nicht mehr da. Solche Stellen werden nach den ueblichen
Vorrangregeln uebersetzt UND als geraten gemeldet, damit die Oberflaeche sie
hervorheben kann. Geraten wird also, aber nie stillschweigend. Wer es eindeutig
will, spricht die Klammern mit („Klammer auf … Klammer zu") — dann gilt genau das.
"""

from __future__ import annotations

import logging
import re
from .protokolltext import inhalt


log = logging.getLogger(__name__)

# -- Vokabular ---------------------------------------------------------------------

_GREEK = {
    "alpha": r"\alpha", "beta": r"\beta", "gamma": r"\gamma", "delta": r"\delta",
    "epsilon": r"\epsilon", "zeta": r"\zeta", "eta": r"\eta", "theta": r"\theta",
    "jota": r"\iota", "iota": r"\iota", "kappa": r"\kappa", "lambda": r"\lambda",
    "my": r"\mu", "mu": r"\mu", "ny": r"\nu", "nu": r"\nu", "xi": r"\xi",
    "pi": r"\pi", "rho": r"\rho", "sigma": r"\sigma", "tau": r"\tau",
    "ypsilon": r"\upsilon", "phi": r"\phi", "chi": r"\chi", "psi": r"\psi",
    "omega": r"\omega",
}
_GREEK_UPPER = {
    "gross " + k: v.replace("\\", "\\", 1).replace(v[1], v[1].upper(), 1)
    for k, v in (("lambda", r"\lambda"), ("delta", r"\delta"), ("omega", r"\omega"),
                 ("sigma", r"\sigma"), ("phi", r"\phi"), ("psi", r"\psi"),
                 ("gamma", r"\gamma"), ("theta", r"\theta"))
}

_NUMBERS = {
    "null": "0", "eins": "1", "eine": "1", "ein": "1", "zwei": "2", "drei": "3",
    "vier": "4", "fuenf": "5", "fünf": "5", "sechs": "6", "sieben": "7",
    "acht": "8", "neun": "9", "zehn": "10", "elf": "11", "zwoelf": "12",
    "zwölf": "12", "hundert": "100", "tausend": "1000",
}

_FUNCS = {
    "sinus": r"\sin", "kosinus": r"\cos", "cosinus": r"\cos", "tangens": r"\tan",
    "kotangens": r"\cot", "logarithmus": r"\log", "log": r"\log", "ln": r"\ln",
    "exponential": r"\exp", "limes": r"\lim",
}

# Operatoren: gesprochen → LaTeX. Reihenfolge egal, wird wortweise gematcht.
_OPS = {
    "plus": "+", "minus": "-", "mal": r"\cdot", "geteilt": "/", "gleich": "=",
    "ungleich": r"\neq", "kleiner": "<", "groesser": ">", "größer": ">",
    "identisch": r"\equiv", "unendlich": r"\infty", "pfeil": r"\to",
}


def _is_var(token: str) -> bool:
    """Einzelner Buchstabe = Variable (x, y, f, k …)."""
    return len(token) == 1 and token.isalpha()


def _atom(token: str) -> str | None:
    """Ein Token → LaTeX-Baustein, oder None wenn unbekannt."""
    low = token.lower()
    if low in _GREEK:
        return _GREEK[low]
    if low in _NUMBERS:
        return _NUMBERS[low]
    if low in _FUNCS:
        return _FUNCS[low]
    if token.isdigit():
        return token
    if _is_var(token):
        return token
    return None


# -- Erkennung: wo im Satz steckt ueberhaupt eine Formel? ---------------------------

# Woerter, die eine Formel ANZEIGEN. Ohne mindestens eines davon fassen wir einen
# Textabschnitt gar nicht erst an — „zwei Sachen" ist keine Mathematik.
_SIGNALS = re.compile(
    r"\b(hoch|quadrat|wurzel|bruch|geteilt|durch|plus|minus|mal|gleich|"
    r"integral|summe|ableitung|limes|unendlich|sinus|kosinus|cosinus|tangens|"
    r"logarithmus|" + "|".join(_GREEK) + r")\b",
    re.IGNORECASE,
)

_TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß]+|\d+")

# Whisper schreibt gesprochene Mathematik teilweise schon als SYMBOL: „x hoch zwei"
# wird zu „x²", „minus" zu „-". Diese Zeichen kannte der Tokenizer nicht und hat sie
# STILL VERSCHLUCKT — aus „Wurzel aus x²-1" wurde `\sqrt{x}1`, ohne jede Warnung.
# Sie werden deshalb vor dem Zerlegen in ihre gesprochene Form zurueckuebersetzt.
_SYMBOL_WORDS = {
    "²": " hoch zwei ", "³": " hoch drei ", "⁴": " hoch vier ",
    "½": " eins durch zwei ", "¼": " eins durch vier ",
    "√": " wurzel aus ", "π": " pi ", "∞": " unendlich ",
    "+": " plus ", "−": " minus ", "–": " minus ", "-": " minus ",
    "·": " mal ", "×": " mal ", "*": " mal ", "/": " durch ", ":": " durch ",
    "=": " gleich ", "≠": " ungleich ", "<": " kleiner ", ">": " groesser ",
    "≤": " kleiner ", "≥": " groesser ",
    "(": " klammer auf ", ")": " klammer zu ",
    "α": " alpha ", "β": " beta ", "γ": " gamma ", "δ": " delta ",
    "λ": " lambda ", "μ": " my ", "σ": " sigma ", "φ": " phi ", "ω": " omega ",
    "θ": " theta ", "Δ": " delta ", "Σ": " sigma ", "Λ": " lambda ",
}
_SYMBOL_RE = re.compile("|".join(re.escape(k) for k in _SYMBOL_WORDS))


# Token = Wort, Zahl ODER mathematisches Symbol. Ohne die Symbole verschwanden sie
# spurlos zwischen den Woertern.
_WORD_OR_SYMBOL = re.compile(
    r"[A-Za-zÄÖÜäöüß]+|\d+|" + "|".join(re.escape(k) for k in _SYMBOL_WORDS))


def _expand_tokens(tokens: list[str]) -> list[str]:
    """Symbol-Token in ihre gesprochene Form aufloesen („²" → „hoch", „zwei")."""
    out: list[str] = []
    for tok in tokens:
        if tok in _SYMBOL_WORDS:
            out.extend(_SYMBOL_WORDS[tok].split())
        else:
            out.append(tok)
    return out


def normalize_symbols(text: str) -> str:
    """Mathematische Sonderzeichen in ihre gesprochene Form bringen.

    Damit sieht der Parser dieselbe Struktur, egal ob Whisper „x hoch zwei" oder
    „x²" geschrieben hat — und nichts geht mehr stillschweigend verloren."""
    return _SYMBOL_RE.sub(lambda m: _SYMBOL_WORDS[m.group()], text or "")


def _parse(tokens: list[str], guessed: list | None = None) -> str | None:
    """Token-Folge → LaTeX. None = gar nicht uebersetzbar.

    `guessed` sammelt Stellen, an denen die Lesart NICHT eindeutig war und nach
    Schulmathematik-Vorrang geraten wurde. Der Aufrufer kann das kennzeichnen —
    geraten wird also, aber nie stillschweigend.

    Bewusst ein kleiner, gut ueberschaubarer Zustandsautomat statt einer echten
    Grammatik: Er deckt die Formen ab, die im Diktat wirklich vorkommen, und sagt
    bei allem anderen ehrlich „nein"."""
    if guessed is None:
        guessed = []
    out: list[str] = []
    i = 0
    n = len(tokens)
    used_signal = False

    while i < n:
        tok = tokens[i]
        low = tok.lower()

        # „wurzel aus X" → \sqrt{X}
        if low == "wurzel":
            j = i + 1
            if j < n and tokens[j].lower() == "aus":
                j += 1
            inner, j = _parse_operand(tokens, j, guessed)
            if inner is None:
                return None
            # MEHRDEUTIG: „wurzel aus x quadrat plus c" kann \sqrt{x^2}+c oder
            # \sqrt{x^2+c} heissen — gesprochen fehlen die Klammern, und die
            # Betonung, die es entscheidet, steht im Transkript nicht mehr.
            # Wir raten dann nach Schulmathematik-Vorrang (die Wurzel bindet nur
            # den naechsten Operanden) und MERKEN UNS, dass geraten wurde.
            if j < n and tokens[j].lower() in _OPS:
                guessed.append("Wurzel — Klammern mitsprechen macht es eindeutig")
            out.append(rf"\sqrt{{{inner}}}")
            i, used_signal = j, True
            continue

        # „X hoch Y" → X^{Y}
        if low == "hoch":
            if not out:
                return None
            base = out.pop()
            exp, j = _parse_operand(tokens, i + 1, guessed)
            if exp is None:
                return None
            # MEHRDEUTIG wie bei der Wurzel: „e hoch lambda x" ist entweder
            # e^{\lambda}x oder e^{\lambda x}. Folgt direkt ein weiteres Symbol,
            # ziehen wir es in den Exponenten — das ist die im Diktat weitaus
            # haeufigere Bedeutung — und merken uns, dass geraten wurde.
            if j < n and _atom(tokens[j]) is not None:
                parts = [exp]
                while j < n and _atom(tokens[j]) is not None:
                    parts.append(_atom(tokens[j]))
                    j += 1
                # Leerzeichen zwischen LaTeX-Befehlen, sonst wird aus
                # „\lambda" + „x" das unbekannte Makro „\lambdax".
                exp = " ".join(parts) if any(p.startswith("\\") for p in parts) \
                    else "".join(parts)
                guessed.append("Exponent — Klammern mitsprechen macht es eindeutig")
            out.append(f"{base}^{{{exp}}}")
            i, used_signal = j, True
            continue

        # „X quadrat" → X^{2}
        if low in ("quadrat", "quadriert"):
            if not out:
                return None
            out.append(f"{out.pop()}^{{2}}")
            i, used_signal = i + 1, True
            continue

        # „X durch Y" / „X geteilt durch Y" → \frac{X}{Y}
        if low in ("durch", "geteilt"):
            if not out:
                return None
            j = i + 1
            if low == "geteilt" and j < n and tokens[j].lower() == "durch":
                j += 1
            denom, j = _parse_operand(tokens, j, guessed)
            if denom is None:
                return None
            # Nur der UNMITTELBAR davorstehende Operand ist der Zaehler — „a plus b
            # durch c" heisst nach Vorrangregeln a + b/c, nicht (a+b)/c. Steht
            # davor etwas anderes als ein Operator, ist die Lesart offen: raten
            # und kennzeichnen.
            numer = out.pop()
            if out and out[-1] not in ("+", "-", "=", r"\cdot", "(", "<", ">"):
                guessed.append("Bruch — Klammern mitsprechen macht es eindeutig")
            out.append(rf"\frac{{{numer}}}{{{denom}}}")
            i, used_signal = j, True
            continue

        # „bruch X durch Y" → dasselbe, nur vorangestellt angesagt
        if low == "bruch":
            i += 1
            continue

        # Operatoren
        if low in _OPS:
            out.append(_OPS[low])
            i, used_signal = i + 1, True
            continue

        # Funktionen: „sinus von x" / „sinus x"
        if low in _FUNCS:
            j = i + 1
            if j < n and tokens[j].lower() == "von":
                j += 1
            arg, j = _parse_operand(tokens, j, guessed)
            if arg is None:
                out.append(_FUNCS[low])
                i += 1
            else:
                out.append(rf"{_FUNCS[low]}({arg})")
                i = j
            used_signal = True
            continue

        # „klammer auf/zu"
        if low == "klammer" and i + 1 < n and tokens[i + 1].lower() in ("auf", "zu"):
            out.append("(" if tokens[i + 1].lower() == "auf" else ")")
            i += 2
            continue

        atom = _atom(tok)
        if atom is None:
            return None                    # unbekanntes Wort → kein Rateversuch
        out.append(atom)
        i += 1

    if not used_signal or not out:
        return None
    return _join(out)


def _parse_operand(tokens: list[str], i: int,
                   guessed: list | None = None) -> tuple[str | None, int]:
    """Ein einzelner Operand ab Position i → (LaTeX, naechste Position)."""
    if guessed is None:
        guessed = []
    n = len(tokens)
    if i >= n:
        return None, i
    low = tokens[i].lower()

    if low == "klammer" and i + 1 < n and tokens[i + 1].lower() == "auf":
        depth, j, inner = 1, i + 2, []
        while j < n and depth:
            t = tokens[j].lower()
            if t == "klammer" and j + 1 < n and tokens[j + 1].lower() == "auf":
                depth += 1
                inner.extend(tokens[j:j + 2])
                j += 2
                continue
            if t == "klammer" and j + 1 < n and tokens[j + 1].lower() == "zu":
                depth -= 1
                j += 2
                if depth == 0:
                    break
                inner.extend(tokens[j - 2:j])
                continue
            inner.append(tokens[j])
            j += 1
        parsed = _parse(inner, guessed) if inner else None
        if parsed is None:
            return None, i
        return f"({parsed})", j

    if low == "wurzel":
        j = i + 1
        if j < n and tokens[j].lower() == "aus":
            j += 1
        inner, j = _parse_operand(tokens, j, guessed)
        if inner is None:
            return None, i
        return rf"\sqrt{{{inner}}}", j

    atom = _atom(tokens[i])
    if atom is None:
        return None, i
    j = i + 1
    # Direkt anschliessendes „hoch Y" gehoert noch zum Operanden.
    if j < n and tokens[j].lower() == "hoch":
        exp, k = _parse_operand(tokens, j + 1, guessed)
        if exp is not None:
            return f"{atom}^{{{exp}}}", k
    if j < n and tokens[j].lower() in ("quadrat", "quadriert"):
        return f"{atom}^{{2}}", j + 1
    return atom, j


def _join(parts: list[str]) -> str:
    """LaTeX-Teile mit sinnvollen Abstaenden verbinden."""
    text = ""
    for part in parts:
        if not text:
            text = part
        elif part in "+-=<>" or part in (r"\cdot", r"\neq", r"\equiv", r"\to"):
            text += f" {part} "
        elif text.rstrip().endswith(("+", "-", "=", "<", ">")) or text.endswith(" "):
            text += part
        else:
            text += part
    return re.sub(r"\s{2,}", " ", text).strip()


def speech_to_latex(text: str) -> tuple[str | None, list[str]]:
    """Ganzen Ausdruck uebersetzen → (LaTeX oder None, Liste der Rate-Stellen).

    Eine leere Liste heisst: eindeutig uebersetzt. Eintraege darin heissen: das
    Ergebnis ist plausibel, aber die gesprochene Fassung liess mehrere Lesarten
    zu — der Aufrufer soll das sichtbar machen."""
    tokens = _expand_tokens(_WORD_OR_SYMBOL.findall(text or ""))
    if not tokens or not _SIGNALS.search(normalize_symbols(text or "")):
        return None, []
    guessed: list[str] = []
    return _parse(tokens, guessed), guessed


# -- Formelstellen im Fliesstext finden --------------------------------------------

# Woerter, die einen Formelabschnitt beenden (normaler Satzfluss geht weiter).
_STOP = frozenset({
    "und", "oder", "aber", "dann", "also", "weil", "dass", "das", "ist", "sind",
    "wir", "ich", "du", "es", "der", "die", "den", "dem", "ein", "eine", "haben",
    "hat", "wird", "wurde", "kann", "soll", "muss", "noch", "hier", "da", "so",
    "jetzt", "mal", "auch", "nur", "schon", "immer", "wieder", "sehr",
})

_MIN_FORMULA_TOKENS = 3

# Ein Bindestrich MITTEN in einem Wort ist kein Minus. Ohne diese Pruefung wurden
# zusammengesetzte Woerter zerrissen — real eingefuegt:
#   „3D-Model"           → `$3D -$Model`
#   „Combat-Log-Dummy"   → `Combat$-\log -$Dummy`
#   „1.21-Jar"           → `$121 -$Jar`
#   „schl-a-gen"         → `schl$-a -$gen`
# In allen Faellen lieferte der Bindestrich das Operator-Token, das aus zwei
# harmlosen Zeichen eine „Formel" machte. Gesprochenes Minus kommt als WORT
# („minus") an; der Strich stammt fast immer aus Whispers Schreibweise.
def _is_compound_hyphen(text: str, start: int, end: int) -> bool:
    """Steht der Strich ohne Leerzeichen zwischen zwei WORTzeichen?

    Mathematische Sonderzeichen zaehlen NICHT als Wortzeichen: In „x²-1" ist das
    hochgestellte Zwei fuer Python zwar alphanumerisch, der Strich danach ist aber
    ein echtes Minus (real gemeldeter Fall). Nur Buchstaben und normale Ziffern
    binden den Strich ans Wort.
    """
    davor = text[start - 1] if start > 0 else " "
    danach = text[end] if end < len(text) else " "
    return all(z.isalnum() and z not in _SYMBOL_WORDS for z in (davor, danach))


# Ein Abschnitt braucht mindestens EIN echtes Mathe-Signal, das nicht der
# Bindestrich ist: entweder ein gesprochenes Mathe-Wort oder ein anderes Symbol.
# Genau daran scheitern die Faelle oben — „3D-Model" hat als einziges „Signal"
# den Strich. Bewusst KEINE Pruefung des ganzen Diktats: Formeln stehen meistens
# mitten im Fliesstext (Nutzer-Fall: „…, von der die Determinante t+2 zum Quadrat
# …"), eine Gesamt-Einordnung wuerde genau die verwerfen.
_SUBSTANZ_WOERTER = frozenset(
    list(_FUNCS) + list(_OPS) + list(_GREEK) + list(_NUMBERS)
    + ["hoch", "quadrat", "quadriert", "wurzel", "bruch", "durch", "geteilt",
       "klammer", "integral", "summe", "ableitung"]
) - {"minus"}          # „minus" allein traegt keine Formel


# Ein alleinstehendes Minus reicht als Signal erst ab dieser Zahl von Operanden.
# Gemessen am echten Verlauf (1137 Diktate): darunter liegen „Seite 3 - 4",
# „2 - 1", „A - 1" — darueber die echten Zeilenumformungen „Z2 - 3Z1". Zwei nackte
# Zahlen mit einem Strich dazwischen sind meistens keine Rechnung.
_MINUS_MIN_OPERANDEN = 4


def _hat_substanz(tokens: list) -> bool:
    """Genug Mathematik fuer eine Formel — oder nur Zahlen mit Strichen dazwischen?

    Ein Signal, das NICHT der Strich ist (Mathe-Wort oder anderes Symbol), plus
    zwei Operanden — das ist der Normalfall. „3D -" hat zwar zwei Operanden, aber
    kein Signal; „- a -" hat ein Signal, aber nur einen Operanden.

    Das Minus ist der Sonderfall: als einziges Signal traegt es eine Formel erst,
    wenn wirklich gerechnet aussieht, was dasteht (siehe Konstante oben).
    """
    signal = False
    nur_minus = False
    operanden = 0
    for tok in tokens:
        low = tok.lower()
        if low in _SUBSTANZ_WOERTER:
            signal = True
        elif tok in _SYMBOL_WORDS or low == "minus":
            if tok in ("-", "–", "−") or low == "minus":
                nur_minus = True
            else:
                signal = True
        if _atom(tok) is not None and low not in _FUNCS:
            operanden += 1
    if signal:
        return operanden >= 2
    return nur_minus and operanden >= _MINUS_MIN_OPERANDEN


def find_formulas(text: str) -> list[tuple[int, int, str, list]]:
    """[(start, ende, latex, rate_hinweise)] aller uebersetzbaren Stellen im Text.

    Sucht zusammenhaengende Abschnitte aus Mathe-Vokabular und uebersetzt sie.
    Ein Abschnitt endet an Satzzeichen oder an einem klaren Fliesstext-Wort."""
    if not text or not _SIGNALS.search(normalize_symbols(text)):
        return []

    found: list[tuple[int, int, str]] = []
    # Satzzeichen trennen Abschnitte — ABER NICHT das Komma. Whisper setzt beim
    # Diktieren von Formeln staendig Kommas („Wurzel aus, Klammer auf, x plus c,
    # Klammer zu"); daran zerriss die Erkennung frueher ausgerechnet die Formeln,
    # die der Nutzer sorgfaeltig mit Klammern gesprochen hatte. Der Rest der Formel
    # ging dann ans Sprachmodell — und dessen Dollarzeichen landeten INEINANDER.
    for chunk in re.finditer(r"[^.;:!?]+", text):
        segment = chunk.group()
        if not _SIGNALS.search(normalize_symbols(segment)):
            continue
        # Symbole zaehlen als eigene Token — sonst faellt „x²-1" auf „x" und „1"
        # zusammen und der Parser liefert stillschweigend `\sqrt{x}1`. Die
        # Positionen bleiben dabei die des ORIGINALTEXTS; uebersetzt wird erst
        # beim Parsen (`_expand_tokens`).
        words = list(_WORD_OR_SYMBOL.finditer(segment))
        run: list = []

        def flush(run_words):
            if len(run_words) < _MIN_FORMULA_TOKENS:
                return
            roh = [w.group() for w in run_words]
            if not _hat_substanz(roh):
                return
            guessed: list[str] = []
            latex = _parse(_expand_tokens(roh), guessed)
            if not latex:
                return
            start = chunk.start() + run_words[0].start()
            end = chunk.start() + run_words[-1].end()
            found.append((start, end, latex, guessed))

        for word in words:
            low = word.group().lower()
            if word.group() in ("-", "–", "−") and _is_compound_hyphen(
                    segment, word.start(), word.end()):
                # Wort-Bindestrich: trennt zwei Woerter, ist aber kein Operator.
                flush(run)
                run = []
                continue
            known = (word.group() in _SYMBOL_WORDS
                     or _atom(word.group()) is not None or low in _OPS
                     or low in ("hoch", "quadrat", "quadriert", "wurzel", "aus",
                                "durch", "geteilt", "bruch", "klammer", "auf",
                                "zu", "von"))
            if known and low not in _STOP:
                run.append(word)
            else:
                flush(run)
                run = []
        flush(run)
    return found


def apply_formulas(text: str) -> tuple[str, list[str], list[bool]]:
    """(Text mit Platzhaltern, [LaTeX-Formeln], [war unsicher?]).

    Die dritte Liste sagt je Formel, ob die gesprochene Fassung mehrdeutig war und
    nach Vorrangregeln geraten wurde. Der Aufrufer macht das sichtbar — geraten
    wird, aber nie stillschweigend.

    Ohne Treffer kommt der Text unveraendert zurueck — der Aufrufer laeuft dann
    exakt wie bisher."""
    spots = find_formulas(text)
    if not spots:
        return text, [], []
    out, formulas, uncertain, last = [], [], [], 0
    for start, end, latex, guessed in spots:
        if start < last:
            continue                        # Ueberlappung: erste Fassung gewinnt
        out.append(text[last:start])
        out.append(formula_marker(len(formulas)))
        formulas.append(latex)
        uncertain.append(bool(guessed))
        if guessed:
            log.info("Formel GERATEN (%s): %s", guessed[0], inhalt(latex, 60))
        last = end
    out.append(text[last:])
    log.info("Formeln erkannt: %d (%d davon geraten)", len(formulas), sum(uncertain))
    return re.sub(r"[ \t]{2,}", " ", "".join(out)).strip(), formulas, uncertain


def formula_marker(index: int) -> str:
    return f"[[M{index + 1}]]"


def restore_formulas(text: str, formulas: list[str]) -> str:
    """Platzhalter → `$latex$`.

    Setzt KEINE eigenen Dollarzeichen, wenn der Platzhalter bereits innerhalb
    eines Mathe-Bereichs steht. Real passiert: Der Parser erkannte nur einen Teil
    („x + c"), das Sprachmodell machte aus dem gesprochenen Rest ein `\\sqrt{…}`
    samt Dollarzeichen — und beim Zuruecksetzen entstand `$ \\sqrt{$x + c$} $`,
    also kaputtes LaTeX. Jetzt gewinnt der aeussere Mathe-Bereich.
    """
    for i, latex in enumerate(formulas):
        marker = formula_marker(i)
        while marker in text:
            pos = text.index(marker)
            inside_math = text.count("$", 0, pos) % 2 == 1
            replacement = latex if inside_math else f"${latex}$"
            text = text[:pos] + replacement + text[pos + len(marker):]
    return text


def markers_survived(before: str, after: str, count: int) -> bool:
    return not any(formula_marker(i) in before and formula_marker(i) not in after
                   for i in range(count))


# -- Lesbare Kurzform fuer die Warnung ---------------------------------------------

_SUPERSCRIPT = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_READABLE_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "theta": "θ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "phi": "φ", "chi": "χ", "psi": "ψ",
    "omega": "ω", "infty": "∞", "cdot": "·", "neq": "≠", "equiv": "≡", "to": "→",
    "sin": "sin", "cos": "cos", "tan": "tan", "log": "log", "ln": "ln",
}


def readable(latex: str) -> str:
    """LaTeX → lesbare Kurzform fuer die Warnblase.

    In der Pille ist `\\sqrt{x} - c + \\frac{c}{2}` schwer zu pruefen — genau dort
    muss man aber auf einen Blick sehen, ob die geratene Lesart stimmt. Fuer die
    ANZEIGE wird deshalb in Symbole uebersetzt (√, ², Bruchstrich); eingefuegt
    wird selbstverstaendlich weiterhin das echte LaTeX."""
    text = latex or ""
    for _ in range(4):                      # verschachtelte Ausdruecke aufloesen
        before = text
        text = re.sub(r"\\sqrt\{([^{}]*)\}",
                      lambda m: "√" + _wrap(m.group(1)), text)
        text = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}",
                      lambda m: f"{_wrap(m.group(1))}/{_wrap(m.group(2))}", text)
        text = re.sub(r"\^\{([^{}]*)\}",
                      lambda m: (m.group(1).translate(_SUPERSCRIPT)
                                 if m.group(1).isdigit() else "^" + m.group(1)), text)
        if text == before:
            break
    text = re.sub(r"\\([a-zA-Z]+)",
                  lambda m: _READABLE_GREEK.get(m.group(1), m.group(1)), text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _wrap(inner: str) -> str:
    """Klammern nur, wo sie noetig sind: √x statt √(x), aber √(x + c)."""
    inner = inner.strip()
    if inner.startswith("(") and inner.endswith(")"):
        return inner
    return inner if len(inner) <= 2 and " " not in inner else f"({inner})"

