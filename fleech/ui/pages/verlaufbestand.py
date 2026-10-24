"""Die Bestandszeile unter der Home-Timeline: Wie gross ist der Verlauf gerade?

Anlass (Nutzer, 2026-10-21): Seit der Verlauf auch den KI-Austausch je Diktat
aufhebt, waechst die Datei schneller — und es gab keinen Ort, an dem man ihre
Groesse sah. Eine Zeile, ohne Qt, damit der Wortlaut ohne Fenster pruefbar ist.
"""

from __future__ import annotations


def groesse_text(n: int) -> str:
    """Bytes deutsch formatiert: „812 KB", „2,4 MB", „1,1 GB"."""
    n = max(0, int(n))
    if n < 1024 ** 2:
        return f"{max(1, round(n / 1024)) if n else 0} KB"
    wert, einheit = (n / 1024 ** 2, "MB") if n < 1024 ** 3 else (n / 1024 ** 3, "GB")
    return f"{wert:.1f} {einheit}".replace(".", ",")


def _zahl(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


def bestand_zeile(bestand: dict, aufbewahrung_tage: int) -> str:
    """„Verlauf-Datenbank: 2,4 MB · 1.234 Diktate · 2.980 KI-Aufrufe · …"."""
    diktate = int(bestand.get("diktate", 0))
    ki = int(bestand.get("ki_aufrufe", 0))
    teile = [
        f"Verlauf-Datenbank: {groesse_text(bestand.get('bytes', 0))}",
        f"{_zahl(diktate)} {'Diktat' if diktate == 1 else 'Diktate'}",
        f"{_zahl(ki)} {'KI-Aufruf' if ki == 1 else 'KI-Aufrufe'}",
        "verschlüsselt",
    ]
    tage = int(aufbewahrung_tage or 0)
    teile.append(f"Aufbewahrung {tage} Tage" if tage > 0 else "Aufbewahrung unbegrenzt")
    return " · ".join(teile)
