"""Diktierte Wörter greifbar machen: „das 2,3-Fache von Goethes Faust I".

Eine Zahl wie „74.245 Wörter" sagt niemandem etwas. Ein Vergleich mit einem Buch,
das man kennt, schon. Gezeigt wird immer ein Werk, das bereits ÜBERSCHRITTEN ist —
und zufällig gewählt, damit die Karte nicht monatelang dasselbe behauptet.

Die Wortzahlen sind gerundete Richtwerte gängiger deutscher Ausgaben; sie schwanken
je nach Übersetzung und Zählweise um einige Prozent. Für einen Größenvergleich
genügt das — deshalb steht in der Anzeige „etwa".
"""

from __future__ import annotations

import random

# (Wörter, Titel) — aufsteigend. Die Spanne ist bewusst weit: Der erste Eintrag soll
# nach wenigen Wochen fallen, der letzte auch nach Jahren noch etwas hermachen.
# Titel OHNE eigene Anführungszeichen — die setzt die Ausgabe. Sonst entsteht
# „Goethes „Faust I““, was niemand lesen will.
WERKE: tuple[tuple[int, str], ...] = (
    (17_000, "Der kleine Prinz"),
    (22_000, "Die Verwandlung"),
    (27_000, "Der alte Mann und das Meer"),
    (30_000, "Faust I"),
    (60_000, "Momo"),
    (77_000, "Harry Potter und der Stein der Weisen"),
    (89_000, "1984"),
    (95_000, "Der Hobbit"),
    (140_000, "Die unendliche Geschichte"),
    (180_000, "Die Blechtrommel"),
    (455_000, "Der Herr der Ringe"),
    (587_000, "Krieg und Frieden"),
    (800_000, "Die Bibel"),
    (1_084_000, "Harry Potter — alle sieben Bände"),
)


def _zahl(wert: float) -> str:
    """Deutsche Schreibweise: Komma als Dezimaltrenner, Punkt als Tausender."""
    if wert >= 10:
        return f"{wert:,.0f}".replace(",", ".")
    return f"{wert:.1f}".replace(".", ",")


def word_milestone(total_words: int, rng: random.Random | None = None) -> str:
    """Eine Zeile für die Wörter-Karte. Leer, wenn noch nichts zu vergleichen ist.

    `rng` injizierbar, damit Tests nicht auf Zufall angewiesen sind.
    """
    if not total_words or total_words < 0:
        return ""
    erreicht = [(w, titel) for w, titel in WERKE if total_words >= w]
    if not erreicht:
        # Noch keins geschafft — dann zeigt die Karte das nächste Ziel. Das ist
        # nützlicher als gar nichts und stachelt beim Einstieg ein wenig an.
        woerter, titel = WERKE[0]
        fehlt = woerter - total_words
        return f"noch {_zahl(fehlt)} Wörter bis „{titel}“"

    # Aus ALLEN erreichten wählen, nicht nur aus dem größten: Sonst stünde dort
    # monatelang derselbe Titel, und genau die Abwechslung macht den Reiz aus.
    woerter, titel = (rng or random).choice(erreicht)
    faktor = total_words / woerter
    if faktor < 1.05:
        return f"gerade „{titel}“ überschritten"
    return f"etwa das {_zahl(faktor)}-Fache von „{titel}“"
