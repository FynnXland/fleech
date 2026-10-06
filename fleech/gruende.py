"""Warum lief ein Diktat nicht glatt? — die Gruende als feste Texte.

Bis 5.10.3 stand jeder dieser Faelle NUR im Protokoll: `status` im Verlauf kennt
zwei Werte, und ein Rueckfall wegen Ollama-Zeitueberschreitung sah aus wie einer
wegen Sinnumkehr (Befunde H-2/F-9). Die Pipeline haelt den Grund jetzt in
`last_reason` fest, der Verlauf speichert ihn, und Detail-Dialog und Insights
zeigen ihn.

Eigene Datei und nicht in `pipeline.py`: Die Texte werden an drei Orten
gebraucht (Pipeline schreibt, Verlauf zaehlt, Oberflaeche zeigt) — und die
Pipeline steht dicht an ihrer Zeilen-Obergrenze (`tests/test_kernstruktur.py`).
Umlaute wie im uebrigen Anzeigetext: Der Nutzer liest diese Saetze.
"""

from __future__ import annotations

# Mehrere Gruende in einem Diktat (z. B. Rohtext gekuerzt UND Rueckfall) stehen in
# EINER Spalte, mit diesem Trenner. Der Verlauf zerlegt daran wieder (`reasons()`).
TRENNER = " · "

# -- KI-Weg: der bereinigte Text kam nicht zustande ----------------------------------
OLLAMA = "Ollama hat nicht geantwortet"
# Cloud-Anbieter (6.1.0): getrennt von Ollama, weil die Abhilfe eine andere ist —
# Schluessel pruefen oder Kontingent aufstocken statt einen Dienst zu starten.
KI_DIENST = "KI-Dienst hat nicht geantwortet"
KI_SCHLUESSEL = "KI-Dienst hat den API-Schlüssel abgelehnt"
KI_KONTINGENT = "KI-Dienst meldet: Kontingent erschöpft"
KONTEXT_VOLL = "Kontextfenster voll — Antwort brach mitten im Satz ab"
LEERE_ANTWORT = "KI-Antwort war leer"
AUSGEFUEHRT = "KI hat das Diktat ausgeführt statt bereinigt"
UMFORMULIERT = "KI hat umformuliert statt bereinigt"
SINN_GEDREHT = "Aussage verändert"          # + Detail, siehe mit_detail()
FORMEL_UNPLAUSIBEL = "Unplausibel viele Formel-Blöcke"
FORMEL_MARKER = "Formel-Platzhalter verloren"
# Je Block geprueft (fleech/bloecke.py) — der Block kam dann als Rohtext.
PROMPT_BEISPIEL = "KI schrieb Beispielsätze aus ihrer Anleitung ins Diktat"
AUSLASSUNG = "KI ließ zu viel vom Gesagten weg"
# `BAUSTEIN_MARKER` ist mit den Text-Bausteinen in 5.11.0 entfallen. Kein Verlauf
# kann ihn tragen: Er entstand nur, wenn Bausteine konfiguriert waren — und das
# waren sie nie.
BEFEHL_GESCHEITERT = "Befehl nicht ausführbar"
FORMAT_GESCHEITERT = "Ausgabeformat lieferte nichts"

# -- Roh-Guards: am Transkript wurde etwas weggeschnitten -----------------------------
ENDE_GEKUERZT = "Ende gekürzt (Wiederholung)"
FREMDE_SCHRIFT = "fremde Schrift entfernt"
WORTSALAT = "Wortsalat entfernt"
DOMINANZ_SCHWANZ = "Dominanz-Schwanz entfernt"
WIEDERHOLUNG_INNEN = "Wiederholung im Text gekürzt"
SCHWANZ_OHNE_TON = "Text ohne Ton am Ende entfernt"

# -- Zustellung: der Text ist fertig, kam aber nicht ins Feld --------------------------
# Spaet fertig und der Nutzer war in einem anderen Fenster (5.13.0): Der Text liegt in
# der Zwischenablage. Gerade DIESE Diktate gehoeren in den Verlauf — dort ist der
# einzige Ort, an dem man sie spaeter noch findet (am 2026-10-02 fehlte eines).
IN_ABLAGE = "Nicht eingefügt — lag nur in der Zwischenablage (spät fertig, anderes Fenster)"

# Etikett fuer die Zaehlzeile der Insights („Rückfälle: 2× Ollama, 1× Sinnumkehr").
# Der volle Satz gehoert in den Einzelfall, nicht in eine Aufzaehlung.
KURZFORM = {
    OLLAMA: "Ollama",
    KI_DIENST: "KI-Dienst",
    KI_SCHLUESSEL: "API-Schlüssel",
    KI_KONTINGENT: "Kontingent",
    KONTEXT_VOLL: "Kontextfenster",
    LEERE_ANTWORT: "leere Antwort",
    AUSGEFUEHRT: "Prompt ausgeführt",
    UMFORMULIERT: "Umformulierung",
    SINN_GEDREHT: "Sinnumkehr",
    FORMEL_UNPLAUSIBEL: "Formel-Ausreißer",
    FORMEL_MARKER: "Formel verloren",
    PROMPT_BEISPIEL: "Prompt-Beispiel",
    AUSLASSUNG: "Auslassung",
    BEFEHL_GESCHEITERT: "Befehl",
    FORMAT_GESCHEITERT: "Ausgabeformat",
    ENDE_GEKUERZT: "Wiederholung",
    FREMDE_SCHRIFT: "fremde Schrift",
    WORTSALAT: "Wortsalat",
    DOMINANZ_SCHWANZ: "Halluzination",
    WIEDERHOLUNG_INNEN: "Wiederholung",
    SCHWANZ_OHNE_TON: "ohne Ton",
    IN_ABLAGE: "nur Zwischenablage",
}


def mit_detail(grund: str, detail: str) -> str:
    """Grund mit Fundstelle („Aussage verändert: 1 Zahl fehlt").

    Ohne das Detail waere die haeufigste Sorte Rueckfall nicht nachpruefbar — man
    saehe, DASS die Aussage kippte, nicht WORAN es lag."""
    detail = (detail or "").strip()
    return f"{grund}: {detail}" if detail else grund


def kurzform(grund: str) -> str:
    """Kurzes Etikett fuer eine Zaehlung ("" bleibt "").

    Vergleicht mit `startswith`, weil Gruende ein Detail tragen koennen
    (`mit_detail`) — sonst faende die Sinnumkehr nie ihr Etikett."""
    grund = (grund or "").strip()
    for voll, kurz in KURZFORM.items():
        if grund.startswith(voll):
            return kurz
    return grund
