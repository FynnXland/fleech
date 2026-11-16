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

Gespeichert wird immer der deutsche Satz (Verlauf-DB, Zaehlung, Vergleiche in der
Pipeline); die Oberflaeche zeigt ihn ueber `anzeige()` bzw. `kurzform()` in ihrer
Sprache (6.6.0).
"""

from __future__ import annotations

import re

from .i18n import N_, tr

# Mehrere Gruende in einem Diktat (z. B. Rohtext gekuerzt UND Rueckfall) stehen in
# EINER Spalte, mit diesem Trenner. Der Verlauf zerlegt daran wieder (`reasons()`).
TRENNER = " · "

# -- KI-Weg: der bereinigte Text kam nicht zustande ----------------------------------
OLLAMA = N_("Ollama hat nicht geantwortet")
# Ollama lief, scheiterte aber beim Laden oder Rechnen (HTTP 5xx) — am 2026-10-08
# ein CUDA-„out of memory" neben einem Spiel. „Hat nicht geantwortet" schickte auf
# die Suche nach einem gestoppten Dienst; die Ursache steht jetzt im Protokoll.
OLLAMA_FEHLER = N_("Ollama ist mit einem Fehler abgebrochen")
# Cloud-Anbieter (6.1.0): getrennt von Ollama, weil die Abhilfe eine andere ist —
# Schluessel pruefen oder Kontingent aufstocken statt einen Dienst zu starten.
KI_DIENST = N_("KI-Dienst hat nicht geantwortet")
KI_SCHLUESSEL = N_("KI-Dienst hat den API-Schlüssel abgelehnt")
KI_KONTINGENT = N_("KI-Dienst meldet: Kontingent erschöpft")
KONTEXT_VOLL = N_("Kontextfenster voll — Antwort brach mitten im Satz ab")
LEERE_ANTWORT = N_("KI-Antwort war leer")
AUSGEFUEHRT = N_("KI hat das Diktat ausgeführt statt bereinigt")
UMFORMULIERT = N_("KI hat umformuliert statt bereinigt")
SINN_GEDREHT = N_("Aussage verändert")          # + Detail, siehe mit_detail()
FORMEL_UNPLAUSIBEL = N_("Unplausibel viele Formel-Blöcke")
FORMEL_MARKER = N_("Formel-Platzhalter verloren")
# Je Block geprueft (fleech/bloecke.py) — der Block kam dann als Rohtext.
PROMPT_BEISPIEL = N_("KI schrieb Beispielsätze aus ihrer Anleitung ins Diktat")
AUSLASSUNG = N_("KI ließ zu viel vom Gesagten weg")
# `BAUSTEIN_MARKER` ist mit den Text-Bausteinen in 5.11.0 entfallen. Kein Verlauf
# kann ihn tragen: Er entstand nur, wenn Bausteine konfiguriert waren — und das
# waren sie nie.
BEFEHL_GESCHEITERT = N_("Befehl nicht ausführbar")
FORMAT_GESCHEITERT = N_("Ausgabeformat lieferte nichts")
# Zielsprache je Profil (6.5.0, `fleech/uebersetzung.py`): Der Text kam in der
# Diktiersprache, weil die Uebersetzung eine Pruefung nicht bestand (+ Detail).
NICHT_UEBERSETZT = N_("Nicht übersetzt")
# Zeitgrenze und Ueberspringen (6.4.0, `fleech/llm/frist.py`): Die KI war zu
# langsam — meist, weil andere Programme Grafikkarte oder Speicher belegten.
KI_FRIST = N_("KI zu langsam — Zeitgrenze erreicht")
UEBERSPRUNGEN = N_("KI übersprungen (per Haken in der Pille)")
# Kein Fehler, aber der Nutzer soll sehen, dass dieser Text die Cloud gesehen hat.
AUSGEWICHEN = N_("Lokale KI zu langsam — in der Cloud bereinigt")

# -- Roh-Guards: am Transkript wurde etwas weggeschnitten -----------------------------
ENDE_GEKUERZT = N_("Ende gekürzt (Wiederholung)")
FREMDE_SCHRIFT = N_("fremde Schrift entfernt")
WORTSALAT = N_("Wortsalat entfernt")
DOMINANZ_SCHWANZ = N_("Dominanz-Schwanz entfernt")
WIEDERHOLUNG_INNEN = N_("Wiederholung im Text gekürzt")
SCHWANZ_OHNE_TON = N_("Text ohne Ton am Ende entfernt")

# -- Zustellung: der Text ist fertig, kam aber nicht ins Feld --------------------------
# Spaet fertig und der Nutzer war in einem anderen Fenster (5.13.0): Der Text liegt in
# der Zwischenablage. Gerade DIESE Diktate gehoeren in den Verlauf — dort ist der
# einzige Ort, an dem man sie spaeter noch findet (am 2026-10-02 fehlte eines).
IN_ABLAGE = N_("Nicht eingefügt — lag nur in der Zwischenablage (spät fertig, anderes Fenster)")

# Etikett fuer die Zaehlzeile der Insights („Rückfälle: 2× Ollama, 1× Sinnumkehr").
# Der volle Satz gehoert in den Einzelfall, nicht in eine Aufzaehlung.
KURZFORM = {
    OLLAMA: "Ollama",
    OLLAMA_FEHLER: N_("Ollama-Fehler"),
    KI_DIENST: N_("KI-Dienst"),
    KI_SCHLUESSEL: N_("API-Schlüssel"),
    KI_KONTINGENT: N_("Kontingent"),
    KONTEXT_VOLL: N_("Kontextfenster"),
    LEERE_ANTWORT: N_("leere Antwort"),
    AUSGEFUEHRT: N_("Prompt ausgeführt"),
    UMFORMULIERT: N_("Umformulierung"),
    SINN_GEDREHT: N_("Sinnumkehr"),
    FORMEL_UNPLAUSIBEL: N_("Formel-Ausreißer"),
    FORMEL_MARKER: N_("Formel verloren"),
    PROMPT_BEISPIEL: N_("Prompt-Beispiel"),
    AUSLASSUNG: N_("Auslassung"),
    BEFEHL_GESCHEITERT: N_("Befehl"),
    FORMAT_GESCHEITERT: N_("Ausgabeformat"),
    NICHT_UEBERSETZT: N_("Übersetzung"),
    KI_FRIST: N_("Zeitgrenze"),
    UEBERSPRUNGEN: N_("übersprungen"),
    AUSGEWICHEN: N_("Cloud-Ausweiche"),
    ENDE_GEKUERZT: N_("Wiederholung"),
    FREMDE_SCHRIFT: N_("fremde Schrift"),
    WORTSALAT: N_("Wortsalat"),
    DOMINANZ_SCHWANZ: N_("Halluzination"),
    WIEDERHOLUNG_INNEN: N_("Wiederholung"),
    SCHWANZ_OHNE_TON: N_("ohne Ton"),
    IN_ABLAGE: N_("nur Zwischenablage"),
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
            return tr(kurz)
    return grund


# Details, die als Satz mit Zahl entstehen (`textfilter.meaning_flipped`,
# `uebersetzung.pruefe`). Gespeichert ist der deutsche Satz; fuer die Anzeige wird
# er hier zerlegt und als ganzer Satz uebersetzt. Feste Details sind an ihrer
# Quelle mit N_() markiert und gehen einfach durch tr().
_DETAIL_MUSTER = (
    (re.compile(r"(?P<n>\d+) Verneinung\(en\) fehlen"), N_("{n} Verneinung(en) fehlen")),
    (re.compile(r"Zahl\(en\) fehlen: (?P<zahlen>.+)"), N_("Zahl(en) fehlen: {zahlen}")),
    (re.compile(r"Zahl (?P<zahl>\S+) fehlt"), N_("Zahl {zahl} fehlt")),
)


def _detail_anzeige(detail: str) -> str:
    for muster, satz in _DETAIL_MUSTER:
        treffer = muster.fullmatch(detail)
        if treffer:
            return tr(satz, **treffer.groupdict())
    return tr(detail)


def anzeige(grund: str) -> str:
    """Gespeicherten Grund in der Sprache der Oberflaeche ("" bleibt "").

    Der Verlauf speichert den deutschen Satz (mit Detail, mehrere per `TRENNER`) —
    uebersetzt wird erst hier, beim Anzeigen. Unbekannte Teile (aeltere Fassungen)
    bleiben, wie sie sind."""
    teile = []
    for teil in (grund or "").split(TRENNER):
        teil = teil.strip()
        for voll in KURZFORM:
            if teil == voll:
                teil = tr(voll)
                break
            if teil.startswith(voll + ": "):
                teil = tr("{grund}: {detail}", grund=tr(voll),
                          detail=_detail_anzeige(teil[len(voll) + 2:]))
                break
        if teil:
            teile.append(teil)
    return TRENNER.join(teile)

