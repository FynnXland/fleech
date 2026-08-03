"""Design-System-Token und Button-Stile — die unterste Schicht der Oberflaeche.

Bewusst ein eigenes Modul und bewusst OHNE Abhaengigkeiten in die App hinein: Bis
5.4.0 standen diese Werte in `main_window.py`, und sechs andere Module zogen sie
von dort (`licensedialog`, `onboarding`, `profilepicker`, `settings_window`,
`setuppage`, `updatedialog`). Damit hing halb die Oberflaeche am Hauptfenster,
obwohl sie nur eine Farbe brauchte — eine verdrehte Richtung, die jeden Umbau am
Hauptfenster unnoetig gefaehrlich machte.

Hier darf nichts hinein, was Zustand haelt oder Widgets baut. Nur Werte und die
zwei Funktionen, die daraus Stylesheets machen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

# Brand-Farben (Dark) — Design-System-Token (claude.ai/design „Fleech Design System").
BG = "#16181C"
SIDEBAR = "#1A1D22"
CARD = "#22262E"
ACCENT = "#35C0D8"
ACCENT_DIM = "#219FB8"
TEXT = "#E8E8EC"
MUTED = "#8A8A92"
TRACK = "#2E3742"
NAV_ACTIVE_BG = "#243A40"
ROW_HOVER = "#2A2F3A"                       # Zeilen-/Control-Hover (eine Stufe heller)
BORDER_HAIRLINE = "rgba(255,255,255,0.06)"  # Hairline fuer Controls/Trenner
BORDER_CARD = "rgba(255,255,255,0.04)"      # noch dezenter: Karten-Rahmen
ON_ACCENT = "#0E2126"                       # dunkle Glyphe/Schrift AUF Akzentflaeche
DANGER_TEXT = "#E08585"                     # Danger-Buttons (Verlauf löschen)

_STREAK_SHADES = ["#2A313B", "#12525F", "#219FB8", "#35C0D8"]


def button_qss(variant: str = "default") -> str:
    """Button-Stile des Design-Systems: default (Karte + Hairline), primary
    (Akzent, dunkle Schrift), danger (rote Schrift, roter Hover), ghost (nackt)."""
    base = ("QPushButton { font-size: 9.5pt; font-weight: 500; border-radius: 8px;"
            "  padding: 6px 14px; }"
            "QPushButton:disabled { color: rgba(232,232,236,0.35); }")
    variants = {
        "default": (
            f"QPushButton {{ background: {CARD}; color: {TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; }}"
            f"QPushButton:hover {{ background: {ROW_HOVER}; }}"
            f"QPushButton:pressed {{ background: {SIDEBAR}; }}"
        ),
        "primary": (
            f"QPushButton {{ background: {ACCENT_DIM}; color: {ON_ACCENT};"
            f"  border: none; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {ACCENT}; }}"
            f"QPushButton:pressed {{ background: {ACCENT_DIM}; }}"
        ),
        "danger": (
            f"QPushButton {{ background: {CARD}; color: {DANGER_TEXT};"
            f"  border: 1px solid {BORDER_HAIRLINE}; }}"
            f"QPushButton:hover {{ background: rgba(220,90,90,0.16);"
            f"  border-color: rgba(220,90,90,0.4); }}"
        ),
        "ghost": (
            f"QPushButton {{ background: transparent; color: {MUTED}; border: none; }}"
            f"QPushButton:hover {{ background: {CARD}; color: {TEXT}; }}"
        ),
    }
    return base + variants.get(variant, variants["default"])


def style_button(btn: QPushButton, variant: str = "default") -> QPushButton:
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet(button_qss(variant))
    return btn
