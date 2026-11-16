"""Die Bestandszeile unter der Home-Timeline: Wie gross ist der Verlauf gerade?

Anlass (Nutzer, 2026-10-21): Seit der Verlauf auch den KI-Austausch je Diktat
aufhebt, waechst die Datei schneller — und es gab keinen Ort, an dem man ihre
Groesse sah. Eine Zeile, ohne Qt, damit der Wortlaut ohne Fenster pruefbar ist.
"""

from __future__ import annotations

from ...i18n import dezimal, tr
from .anzeigetext import ganzzahl


def groesse_text(n: int) -> str:
    """Bytes deutsch formatiert: „812 KB", „2,4 MB", „1,1 GB"."""
    n = max(0, int(n))
    if n < 1024 ** 2:
        return f"{max(1, round(n / 1024)) if n else 0} KB"
    wert, einheit = (n / 1024 ** 2, "MB") if n < 1024 ** 3 else (n / 1024 ** 3, "GB")
    return f"{dezimal(wert, 1)} {einheit}"


def _zahl(n: int) -> str:
    return ganzzahl(n)


def bestand_zeile(bestand: dict, aufbewahrung_tage: int) -> str:
    """„Verlauf-Datenbank: 2,4 MB · 1.234 Diktate · 2.980 KI-Aufrufe · …"."""
    diktate = int(bestand.get("diktate", 0))
    ki = int(bestand.get("ki_aufrufe", 0))
    teile = [
        tr("Verlauf-Datenbank: {groesse}", groesse=groesse_text(bestand.get("bytes", 0))),
        tr("{n} Diktat", n=_zahl(diktate)) if diktate == 1
        else tr("{n} Diktate", n=_zahl(diktate)),
        tr("{n} KI-Aufruf", n=_zahl(ki)) if ki == 1 else tr("{n} KI-Aufrufe", n=_zahl(ki)),
        tr("verschlüsselt"),
    ]
    tage = int(aufbewahrung_tage or 0)
    teile.append(tr("Aufbewahrung {n} Tage", n=tage) if tage > 0
                 else tr("Aufbewahrung unbegrenzt"))
    return " · ".join(teile)
