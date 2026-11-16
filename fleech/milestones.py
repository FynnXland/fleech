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

from . import i18n
from .i18n import N_, dezimal, tr

# (Wörter, Titel) — aufsteigend. Die Spanne ist bewusst weit: Der erste Eintrag soll
# nach wenigen Wochen fallen, der letzte auch nach Jahren noch etwas hermachen.
# Titel OHNE eigene Anführungszeichen — die setzt die Ausgabe. Sonst entsteht
# „Goethes „Faust I““, was niemand lesen will. Titel mit N_(): englische Ausgaben
# heissen anders, die Wortzahlen bleiben die der deutschen.
WERKE: tuple[tuple[int, str], ...] = (
    (17_000, N_("Der kleine Prinz")),
    (22_000, N_("Die Verwandlung")),
    (27_000, N_("Der alte Mann und das Meer")),
    (30_000, "Faust I"),
    (60_000, "Momo"),
    (77_000, N_("Harry Potter und der Stein der Weisen")),
    (89_000, "1984"),
    (95_000, N_("Der Hobbit")),
    (140_000, N_("Die unendliche Geschichte")),
    (180_000, N_("Die Blechtrommel")),
    (455_000, N_("Der Herr der Ringe")),
    (587_000, N_("Krieg und Frieden")),
    (800_000, N_("Die Bibel")),
    (1_084_000, N_("Harry Potter — alle sieben Bände")),
)


def _zahl(wert: float) -> str:
    """Schreibweise der Oberflaeche: 74.245 / 2,3 deutsch, 74,245 / 2.3 englisch."""
    if wert >= 10:
        text = f"{wert:,.0f}"
        return text.replace(",", ".") if i18n.aktuell() == "de" else text
    return dezimal(wert, 1)


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
        return tr("noch {n} Wörter bis „{titel}“", n=_zahl(fehlt), titel=tr(titel))

    # Aus ALLEN erreichten wählen, nicht nur aus dem größten: Sonst stünde dort
    # monatelang derselbe Titel, und genau die Abwechslung macht den Reiz aus.
    woerter, titel = (rng or random).choice(erreicht)
    faktor = total_words / woerter
    if faktor < 1.05:
        return tr("gerade „{titel}“ überschritten", titel=tr(titel))
    return tr("etwa das {faktor}-Fache von „{titel}“", faktor=_zahl(faktor), titel=tr(titel))
