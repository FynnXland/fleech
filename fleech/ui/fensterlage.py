"""Wo das Hauptfenster beim Start hin darf — ohne Qt, damit es sich prüfen lässt.

Der Anlass: Das Fenster öffnete sich mit der Titelleiste oben außerhalb des
Bildschirms. Ursache war ein Widerspruch zwischen Speichern und Wiederherstellen
(`main_window.closeEvent` speicherte die Rahmen-Ecke, `setGeometry` setzte daraus
die Innenfläche). Jeder Neustart rückte das Fenster um die Titelleistenhöhe
nach oben — nachgemessen: 79 → 48 → 17 → −14. Ab dem dritten Start war die
Leiste weg, und nur ein Griff an die Fenstergröße holte es zurück.

Der Widerspruch ist behoben. Diese Datei ist das zweite Netz: Sie prüft beim Start,
ob die gespeicherte Lage überhaupt sichtbar wäre — gegen Werte, die schon auf der
Platte stehen, gegen einen abgesteckten Monitor und gegen alles, was sonst noch
eine Position ins Aus schiebt.
"""

from __future__ import annotations

# Höhe der Windows-Titelleiste in logischen Pixeln (gemessen: 31 bei 100 %).
# Etwas großzügiger, weil sie bei anderen Skalierungen wächst — ein Fenster, das
# dadurch ein paar Pixel tiefer startet, ist harmlos; eines ohne Titelleiste nicht.
TITELLEISTE = 32

# So viel des Fensters muss waagerecht auf dem Bildschirm liegen, damit man es
# noch greifen kann.
GREIFBAR = 150


def _ueberlappung(a: tuple, b: tuple) -> int:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    breite = min(ax + aw, bx + bw) - max(ax, bx)
    hoehe = min(ay + ah, by + bh) - max(ay, by)
    return max(0, breite) * max(0, hoehe)


def sichtbare_lage(x: int, y: int, breite: int, hoehe: int,
                   bildschirme: list) -> tuple | None:
    """Position der Innenfläche so zurechtrücken, dass die Titelleiste sichtbar ist.

    `bildschirme`: nutzbare Flächen als (links, oben, breite, höhe) — unter Qt die
    `availableGeometry()` jedes Bildschirms, also ohne Taskleiste.

    Rückgabe (x, y), oder None, wenn das Fenster auf KEINEM Bildschirm liegt (zum
    Beispiel, weil der Monitor abgesteckt ist). Dann soll der Aufrufer das
    Fenster von Qt platzieren lassen, statt es irgendwohin zu schieben.

    Gewählt wird der Bildschirm mit der größten Überlappung, nicht der primäre:
    Ein Fenster auf dem linken Zweitmonitor gehört dorthin zurück, nicht auf den
    Hauptbildschirm.
    """
    rahmen = (x, y - TITELLEISTE, breite, hoehe + TITELLEISTE)
    flaechen = [(s, _ueberlappung(rahmen, s)) for s in bildschirme]
    flaechen = [(s, f) for s, f in flaechen if f > 0]
    if not flaechen:
        return None
    links, oben, sb, sh = max(flaechen, key=lambda t: t[1])[0]

    # Oben: Die Titelleiste muss vollständig unterhalb der Bildschirmkante liegen.
    y = max(y, oben + TITELLEISTE)
    # Unten: Die Titelleiste darf nicht unter den Bildschirm rutschen.
    y = min(y, oben + sh - GREIFBAR)
    # Seitlich: Ein greifbares Stück muss auf diesem Bildschirm bleiben.
    x = max(x, links - breite + GREIFBAR)
    x = min(x, links + sb - GREIFBAR)
    return x, y
