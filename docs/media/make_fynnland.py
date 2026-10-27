"""Bilder für fynnland.xyz: Kachel, Hintergrund und Medien der Artikelseite.

Lieferformat: `08_Auftritt/fynnland/docs/uebergaben/LIEFERFORMAT.md` (Größen, Regeln).
Baut auf `make_media.py` auf: dieselbe Sandbox (wird beim Import aktiv, VOR jedem
fleech-Import), dieselben echten Qt-Widgets, dieselben erfundenen Beispielsätze aus
`examples.json`. Anders als die README-Medien: keine Beschriftungen, keine Tastenkappe,
kein Mauszeiger. Was im Bild Text ist, zeigt Fleech selbst (Pille, Blase) oder steht im
erfundenen Dokument.

Aufruf aus dem Projektordner, mit dem Python der Fleech-Umgebung:

    python docs/media/make_fynnland.py              # alles
    python docs/media/make_fynnland.py hintergrund  # nur diese Teile

ffmpeg kommt aus dem PATH oder aus der Umgebungsvariable FFMPEG.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_media as mm  # noqa: E402  (setzt die Sandbox, bevor fleech geladen wird)

ZIEL = mm.HIER / "fynnland"
MEDIEN = ZIEL / "media"

# Kachel: das Blau aus dem Verlauf des Logos (assets/logo.svg, #35C0D8 → #256AB0).
# Die Kachel zeigt einen Verlauf von dunkler zu dieser Farbe, darauf die weiße Marke.
TILE_COLOR = "#256AB0"
ACCENT_COLOR = "#35C0D8"     # Akzent der App (fleech/ui/theme.py, ACCENT)


def _ffmpeg(*args: str) -> None:
    subprocess.run([mm._ffmpeg(), "-v", "error", "-y", *args], check=True)


def _webp(png: Path, ziel: Path, qualitaet: int = 86) -> None:
    _ffmpeg("-i", str(png), "-c:v", "libwebp", "-quality", str(qualitaet),
            "-compression_level", "6", str(ziel))
    print(f"  {ziel.relative_to(mm.ROOT)}: {ziel.stat().st_size // 1024} KB")


def _still(img, ziel: Path, qualitaet: int = 86) -> None:
    png = mm._SANDBOX / (ziel.stem + ".png")
    img.convertToFormat(img.Format.Format_RGB32).save(str(png))
    _webp(png, ziel, qualitaet)


def _video(film: "mm.Film", name: str) -> None:
    """WebM (VP9) + MP4 (H.264, faststart) + Poster (erstes Bild), ohne Ton."""
    eingang = ["-framerate", str(film.fps), "-i", str(film.ordner / "f_%05d.png")]
    webm, mp4 = MEDIEN / f"{name}.webm", MEDIEN / f"{name}.mp4"
    _ffmpeg(*eingang, "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "28", "-row-mt", "1",
            "-pix_fmt", "yuv420p", "-an", str(webm))
    _ffmpeg(*eingang, "-c:v", "libx264", "-preset", "slow", "-crf", "19",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", str(mp4))
    for d in (webm, mp4):
        print(f"  {d.relative_to(mm.ROOT)}: {film.n / film.fps:.1f} s, "
              f"{d.stat().st_size // 1024} KB")
    _webp(film.ordner / "f_00000.png", MEDIEN / f"{name}-poster.webp")


# -- Kulisse ---------------------------------------------------------------------------

_KULISSEN: dict = {}
_hintergrund_glatt = mm._hintergrund


def _kulisse(breite: float, hoehe: float):
    """Der Desktop-Verlauf aus make_media, mit festem feinem Rauschen.

    Große dunkle Verläufe brechen beim Komprimieren (WebP, VP9, H.264) in sichtbare
    Stufen. Das Rauschen liegt nur auf dem Verlauf, Fenster und Pille kommen
    unverändert darüber. Es ist in jedem Bild gleich, Videos bleiben dadurch klein."""
    from PySide6.QtGui import QImage

    schluessel = (int(breite), int(hoehe))
    if schluessel not in _KULISSEN:
        img = mm._bild(*schluessel)
        p = mm._maler(img)
        _hintergrund_glatt(p, breite, hoehe)
        p.end()
        glatt = mm._SANDBOX / f"kulisse-{schluessel[0]}x{schluessel[1]}.png"
        rauschen = glatt.with_name(glatt.stem + "-rauschen.png")
        img.save(str(glatt))
        _ffmpeg("-i", str(glatt), "-vf", "noise=alls=3", str(rauschen))
        fertig = QImage(str(rauschen)).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        fertig.setDevicePixelRatio(mm.SKALIERUNG)
        _KULISSEN[schluessel] = fertig
    return _KULISSEN[schluessel]


def _hintergrund_mit_rauschen(p, breite: float, hoehe: float) -> None:
    from PySide6.QtCore import QPointF

    p.drawImage(QPointF(0, 0), _kulisse(breite, hoehe))


mm._hintergrund = _hintergrund_mit_rauschen     # gilt für jede Bühne in diesem Skript


# -- Kachel ---------------------------------------------------------------------------

def teil_kachel() -> None:
    """tile.svg: die Wellenform aus dem Logo, weiß, ohne die Kachel dahinter.

    Die Balken sind exakt die aus assets/logo.svg; nur der Ausschnitt ist enger
    gewählt, damit die Marke auf der kleinen Kachel (62 % von 80 px) groß genug wird."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" '
        'viewBox="36 36 184 184">\n'
        '  <!-- Fleech: Wellenform aus assets/logo.svg, weiß auf transparent -->\n'
        '  <g fill="#ffffff">\n'
        '    <rect x="45"  y="102" width="22" height="52"  rx="11"/>\n'
        '    <rect x="81"  y="86"  width="22" height="85"  rx="11"/>\n'
        '    <rect x="117" y="64"  width="22" height="128" rx="11"/>\n'
        '    <rect x="153" y="86"  width="22" height="85"  rx="11"/>\n'
        '    <rect x="189" y="102" width="22" height="52"  rx="11"/>\n'
        '  </g>\n'
        '</svg>\n'
    )
    (ZIEL / "tile.svg").write_text(svg, encoding="utf-8")
    print("  docs/media/fynnland/tile.svg")
    _kachel_vorschau()


def _kachel_vorschau() -> None:
    """Prüfbild (nicht Teil der Lieferung): die Marke auf der Kachel, wie fynnland sie zeigt."""
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QLinearGradient, QPainterPath
    from PySide6.QtSvg import QSvgRenderer

    img = mm._bild(240, 120, dpr=2)
    p = mm._maler(img)
    for i, groesse in enumerate((80, 40)):
        r = QRectF(20 + i * 120, (120 - groesse) / 2, groesse, groesse)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor(TILE_COLOR).darker(170))
        g.setColorAt(1, QColor(TILE_COLOR))
        pfad = QPainterPath()
        pfad.addRoundedRect(r, groesse * 0.22, groesse * 0.22)
        p.fillPath(pfad, g)
        m = groesse * 0.62
        QSvgRenderer(str(ZIEL / "tile.svg")).render(
            p, QRectF(r.center() - QPointF(m / 2, m / 2), r.center() + QPointF(m / 2, m / 2)))
    p.end()
    vorschau = mm._SANDBOX.parent / "fleech-kachel-vorschau.png"
    img.save(str(vorschau))
    print(f"  Prüfbild (nicht Teil der Lieferung): {vorschau}")


# -- Szenen-Bausteine -------------------------------------------------------------------

def _hero() -> tuple[str, str]:
    daten = mm._lade_beispiele()["hero"]["de"]
    return daten["raw"], daten["text"]


KOPF = [[("Wochen-Update", "fett")], [("", None)]]
TITEL = "Notizen — team-update.txt"


def _buehne(breite: int, hoehe: int, pille, fenster, unten: int):
    b = mm.Buehne(breite, hoehe, pille, platz_unten=unten)
    b.fenster = fenster
    return b


# -- Hintergrund ------------------------------------------------------------------------

def teil_hintergrund() -> None:
    """background.webp 1920 × 1200: ruhiger Editor, darunter die Pille beim Zuhören.

    Alles Wichtige in der Mitte (Telefone zeigen per `cover` nur einen schmalen
    Mittelstreifen), oben und unten Luft für die Abdunklung des Launchers."""
    from PySide6.QtCore import QRectF

    _roh, text = _hero()
    pille = mm._pille_aufnahme(seed=4)
    pille.sprich(30)
    fenster = (QRectF(200, 168, 560, 214), TITEL, KOPF + [[(text, None)], [("", None)]],
               {"px": 15.5})
    b = _buehne(960, 600, pille, fenster, unten=0)
    b.pille_pos.setY(404)
    _still(b.bild(), ZIEL / "background.webp", qualitaet=90)


# -- Ein Diktat als Schleife -------------------------------------------------------------

def teil_diktat() -> None:
    """media/diktat: Aufnahme → Rohtext in der Blase → Text steht im Feld (~7 s, nahtlos).

    Erstes und letztes Bild sind gleich: das fertige Diktat. Der Text erscheint auf
    einmal, wie in der App (Fleech fügt ein, es tippt nicht)."""
    from PySide6.QtCore import QRectF

    roh, text = _hero()
    pille = mm.Pille(mm._settings())
    pille.ov.set_profile_color(mm._profilfarbe("Standard"))
    rechteck = QRectF(48, 22, 544, 200)
    leer = (rechteck, TITEL, KOPF + [[("", None)]], {"px": 15})
    fertig = (rechteck, TITEL, KOPF + [[(text, None)]], {"px": 15})
    b = _buehne(640, 400, pille, leer, unten=22)
    film = mm.Film("fynnland-diktat")
    nr = 0

    def bild(mal: int = 1) -> None:
        nonlocal nr
        for _ in range(mal):
            b.caret_an = (nr // 10) % 2 == 0          # Schreibmarke blinkt (1 s)
            film.bild(b.bild())
            nr += 1

    def ergebnis() -> None:
        pille.ov.show_transcript(text)
        pille.zustand("IDLE")
        b.fenster = fertig

    ergebnis()
    bild(30)                                          # 1,5 s: das Ergebnis
    b.fenster = leer
    pille.ov._caption.hide()
    pille.zustand("LISTENING")
    pille.sprich(14)
    for _ in range(50):                               # 2,5 s: sprechen
        pille.sprich()
        bild()
    pille.zustand("PROCESSING")
    for _ in range(4):
        pille.sprich()
        bild()
    pille.ov.show_raw_preview(roh)                    # Rohtext, „Bereinige …“
    pille.ruhe()
    for _ in range(36):                               # 1,8 s
        pille.sprich()
        bild()
    ergebnis()
    bild(20)                                          # 1 s, dann wieder Bild 1
    _video(film, "diktat")


# -- Vorher / nachher ---------------------------------------------------------------------

def teil_vorher_nachher() -> None:
    """media/vorher.webp + nachher.webp (1600 × 1000): Rohtext in der Blase während der
    Bereinigung, danach der eingefügte Text."""
    from PySide6.QtCore import QRectF

    roh, text = _hero()
    rechteck = QRectF(56, 30, 688, 250)
    for name, fenster_text in (("vorher", None), ("nachher", text)):
        pille = mm.Pille(mm._settings(), seed=11)
        pille.ov.set_profile_color(mm._profilfarbe("Standard"))
        bloecke = KOPF + [[(fenster_text or "", None)]]
        b = _buehne(800, 500, pille, (rechteck, TITEL, bloecke, {"px": 17}), unten=30)
        if fenster_text is None:
            pille.zustand("LISTENING")
            pille.sprich(30)
            pille.zustand("PROCESSING")
            pille.ov.show_raw_preview(roh)
        else:
            # Nach dem Einfuegen: Pille aus, der Text steht im Feld. Die Blase mit
            # demselben Text bleibt weg, sonst stuende er zweimal im Bild.
            pille.zustand("IDLE")
            pille.blase_weg()
        pille.ruhe()
        _still(b.bild(), MEDIEN / f"{name}.webp")


# -- Profile ----------------------------------------------------------------------------

def teil_profile() -> None:
    """media/profil-*.webp: dasselbe Diktat in vier Profilen.

    Die Pille steht beim naechsten Diktat: Ring in der Profilfarbe, darueber die
    Namenskapsel, wie die App sie beim Profilwechsel zeigt. Im Ruhezustand waere
    die Pille ausgeblendet und das Profil im Bild nicht zu erkennen."""
    from PySide6.QtCore import QRectF

    daten = mm._lade_beispiele()["profiles"]["de"]
    fenster = {
        "Standard": ("standard", "Notizen — website.txt", {}),
        "E-Mail": ("email", "Neue Nachricht", {"kopf": [("An", "team@example.com"),
                                                         ("Betreff", "Website-Launch")]}),
        "Stichpunkte": ("stichpunkte", "Notizen — todo.md", {}),
        "KI-Prompt": ("ki-prompt", "KI-Chat — neue Unterhaltung", {"art": "chat", "px": 13}),
    }
    for name, (datei, titel, opt) in fenster.items():
        pille = mm.Pille(mm._settings(), seed=5)
        pille.ov.set_profile_color(mm._profilfarbe(name))
        pille.zustand("LISTENING")
        pille.sprich(12, stumm=True)
        pille.ov.show_profile(name)
        pille.ruhe()
        opt = {"px": 15, **opt}            # der KI-Chat setzt eigene, kleinere Schrift
        text = daten["ergebnisse"][name]["text"]
        # Die Namenskapsel haengt UNTER der Pille — dafuer unten Platz lassen.
        b = _buehne(800, 500, pille, (QRectF(56, 20, 688, 318), titel, mm._bloecke(text), opt),
                    unten=78)
        b.caret_an = False
        _still(b.bild(), MEDIEN / f"profil-{datei}.webp")


TEILE = {
    "kachel": teil_kachel,
    "hintergrund": teil_hintergrund,
    "diktat": teil_diktat,
    "vorher-nachher": teil_vorher_nachher,
    "profile": teil_profile,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("teile", nargs="*", help=f"Auswahl aus: {', '.join(TEILE)}")
    args = ap.parse_args()
    unbekannt = [t for t in args.teile if t not in TEILE]
    if unbekannt:
        raise SystemExit(f"Unbekannt: {', '.join(unbekannt)}")
    MEDIEN.mkdir(parents=True, exist_ok=True)
    mm._qt()
    for name in args.teile or TEILE:
        print(f"{name} …")
        TEILE[name]()


if __name__ == "__main__":
    main()
