"""Leitet aus dem Brand-Design PNG + Windows-ICO ab (Pillow, kein externer Renderer).

Aufruf:  python packaging/make_icons.py   (packaging/build.py ruft es bei jedem Build auf)
Erzeugt: assets/logo_512.png, assets/logo_256.png, assets/logo_128.png,
         assets/fleech.ico (16–256 multi-res).

Die Geometrie entspricht assets/logo.svg (Tile + Verlauf + 5 Waveform-Balken).
Das Skript liegt in packaging/, damit es nicht mit assets/ in die App gebündelt wird.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
RENDER = 1024  # groß rendern, dann sauber herunterskalieren

TOP = (0x35, 0xC0, 0xD8)   # ruhiges Cyan
BOTTOM = (0x25, 0x6A, 0xB0)  # tiefes Blau
BAR = (255, 255, 255)
BAR_HEIGHTS = (0.40, 0.66, 1.00, 0.66, 0.40)


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def render_tile(size: int) -> Image.Image:
    yy, xx = np.mgrid[0:size, 0:size]
    t = (xx + yy) / (2 * (size - 1))
    grad = np.zeros((size, size, 3), dtype=np.uint8)
    for i in range(3):
        grad[..., i] = (TOP[i] + (BOTTOM[i] - TOP[i]) * t).astype(np.uint8)
    img = Image.fromarray(grad, "RGB").convert("RGBA")
    img.putalpha(_rounded_mask(size, int(size * 0.22)))

    draw = ImageDraw.Draw(img)
    n = len(BAR_HEIGHTS)
    bar_w = size * 0.085
    gap = size * 0.055
    total = n * bar_w + (n - 1) * gap
    x0 = (size - total) / 2
    cy = size / 2
    max_h = size * 0.5
    for i, h in enumerate(BAR_HEIGHTS):
        bx = x0 + i * (bar_w + gap)
        bh = max_h * h
        draw.rounded_rectangle(
            [bx, cy - bh / 2, bx + bar_w, cy + bh / 2], radius=bar_w / 2, fill=BAR
        )
    return img


def main() -> None:
    base = render_tile(RENDER)
    for px in (512, 256, 128):
        base.resize((px, px), Image.LANCZOS).save(ASSETS / f"logo_{px}.png")
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    base.resize((256, 256), Image.LANCZOS).save(
        ASSETS / "fleech.ico", sizes=[(s, s) for s in ico_sizes]
    )
    print("Assets geschrieben:", ", ".join(p.name for p in sorted(ASSETS.glob("logo_*.png"))),
          "+ fleech.ico")


if __name__ == "__main__":
    main()
