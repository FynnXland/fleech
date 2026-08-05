"""Masse, Farben und Zeiten der Pille — an EINER Stelle.

Eigenes Modul, damit die Teilgebiete (`geometrie`, `einblendungen`, `zustand`)
sie teilen koennen, ohne `overlay_qt` zu importieren — das importiert sie ja
gerade, um daraus das Fenster zu bauen.
"""

from __future__ import annotations

from PySide6.QtGui import QColor

# Pillen-Optik: die groessere, randlose „cleane" Pille (bewusste Nutzer-Entscheidung
# NACH dem Design-Import — das Konzept mit Punkt/Buttons bleibt, nur die Kapseln
# tragen KEINEN neutralen Rahmen und die Basishoehe bleibt bei 44).
PILL_WIDTH, PILL_HEIGHT = 272, 44
_BG = QColor(24, 24, 28, 235)
_BG_ARMED = QColor(16, 44, 52, 240)   # Befehls-Modus erkannt: dunkles Cyan
_BG_PROMPT = QColor(56, 42, 16, 240)  # KI-Prompting aktiv: dunkles Amber
_BG_PAUSED = QColor(30, 30, 34, 235)  # Pause: sichtbar matter als die Aufnahme
_PROMPT_ACCENT = QColor(232, 161, 60)  # #E8A13C — Prompting-Akzent (Rahmen + Punkt)
# Auto-Gain der Waveform (rein optisch, beeinflusst die Erkennung NICHT):
# FLOOR = leiseste Lautstaerke, die noch als „da spricht jemand" gilt — darunter
# wird nicht hochskaliert, sonst zappelt Stille auf Vollausschlag.
# DECAY = wie schnell der gemerkte Spitzenwert wieder faellt (pro 50-ms-Tick),
# damit die Anzeige nach einem lauten Wort nicht dauerhaft klein bleibt.
_AGC_FLOOR = 0.035
_AGC_DECAY = 0.985
_AGC_MAX_FACTOR = 45.0

_BAR = QColor(232, 232, 236)
_BAR_DIM = QColor(150, 150, 158)
_ACCENT = QColor(53, 192, 216)  # #35C0D8 — Brand-Akzent (✓, Edit-Modus-Rahmen)
_MARGIN = 24  # Abstand zum Bildschirmrand fuer die Presets
_FALLBACK_FLASH_MS = 3000  # so lange bleibt der Haken nach einem Fallback amber
# Formel-Vorschau: laenger als das normale Transkript, weil man eine Formel
# tatsaechlich LESEN muss — aber ohne Bestaetigungsklick, der den Fluss braeche.
_FORMULA_PREVIEW_MS = 5000

# Einrasten beim Ziehen: Innerhalb dieses Abstands springt die Pille auf eine
# ausgezeichnete Linie (Bildschirmmitte, Standard-Rand). Von Hand exakt zu treffen
# ist unmoeglich — „ein bisschen daneben" sieht man dafuer sofort. 18 px sind eng
# genug, dass eine bewusst schraege Position moeglich bleibt.
_SNAP_PX = 18

# Groessen-Presets: skalieren Pille, Buttons und Icons gemeinsam.
SIZE_FACTORS = {"compact": 0.85, "normal": 1.0, "large": 1.2}

# Positions-Presets: Schluessel → Anzeigename. "custom" = frei gezogen.
OVERLAY_PRESETS = [
    ("right_center", "Rechts"),
    ("left_center", "Links"),
    ("top_center", "Oben"),
    ("bottom_center", "Unten"),
]
