# Ideen zur Weiterentwicklung

> Ergänzend zum [Härtungs-Plan](planung-haertung.md) (der behebt Schwächen — diese
> Datei sammelt **neue Fähigkeiten**). Quellen: Markt-Recherche (Wispr Flow, Dragon,
> Superwhisper, VoiceOS u. a.) plus eigene Ideen aus der Arbeit am Code. Jede Idee
> ist bewertet nach Nutzwert für den realen Einsatz (Coding, Mathe, Prompts,
> lokal-first) und Aufwand; die Stufen sind eine Empfehlung für die Reihenfolge.

**Faustregel für die Auswahl:** Fleechs Identität ist *lokal, leise, präzise*.
Ideen, die diese Identität stärken (Snippets, Export, bessere Insights), schlagen
Ideen, die eine andere App daraus machen (Cloud-Aktionen, Voice Control) — Letztere
erst, wenn der Kern ausgereizt ist.

---

## Stufe 1 — klein, sofort lohnend (je ≤ 1 Sitzung)

### 1. Text-Snippets („Baustein: …") — gebaut in 3.x, in 5.11.0 wieder entfernt (unbenutzt)
Gesprochenes Kürzel fügt einen festen Textblock ein: „Baustein Signatur" → die
E-Mail-Signatur, „Baustein Absage" → die Standard-Absage.
**Was daraus wurde:** gebaut wie hier beschrieben — und in 1399 gemessenen Diktaten
kein einziges Mal benutzt; im Verlauf gibt es auch keinen wiederkehrenden Text, der
ein Baustein geworden wäre. In 5.11.0 wieder entfernt. Der Eintrag bleibt als
Warnung stehen: Was Vorab-Handarbeit verlangt, passiert nicht — was von selbst
lernt (Projekt-Gedächtnis), lebt.
**Aufwand: S — und trotzdem verlorene Zeit.**

### 2. Verlauf-Export (Markdown/Text)
Den Diktat-Verlauf (gefiltert nach Zeitraum/App) als Markdown-Datei exportieren;
dazu „Eintrag kopieren" als Kontextaktion. Später optional verschlüsseltes Backup
von Wörterbuch + Profilen + Einstellungen als eine Datei.
**Warum früh:** Die Daten liegen fertig in SQLite; es fehlt nur die Ausgabe. Passt
zum Datenschutz-Versprechen („deine Daten gehören dir").
**Aufwand: S**

### 3. Privacy-Karte in den Insights — HINFÄLLIG
„100 % lokal: X von Y Diktaten · Z nutzten den Formel-Cloud-Pfad." Die Daten stehen
bereits in der Historie (`mode`-Spalte).
**Warum:** Macht das zentrale Verkaufsargument sichtbar und ehrlich — inklusive des
einzigen Cloud-Pfads.
**Aufwand: S**
**Hinfällig (Bahn F, Befund F-B10):** Die Prämisse gilt seit v3.0.0 nicht mehr —
Formeln entstehen im lokalen Parser, es gibt keinen Cloud-Pfad mehr zu zeigen;
`history.privacy_split()`/`CLOUD_MODES` wurden ersatzlos entfernt.

### 4. Befehlstypen-Statistik
Die Befehls-Historie nicht nur als Fallback-Quote, sondern als Karte „häufigste
Befehle" (umformulieren / löschen / übersetzen / kürzen — die Klassifikation dafür
existiert schon als Guard-Regexe in `commands.py`).
**Aufwand: S**

### 5. Safe-Word-Verzögerung (Bestätigungsfenster)
Konfigurierbare Wartezeit (z. B. 0,8 s) zwischen Safe-Word-Erkennung in der
Live-Vorschau und dem Scharfstellen — ein kurzes Zeitfenster, in dem Weitersprechen
die Befehls-Deutung abbricht. Reduziert Fehlauslösungen, wenn das Safe-Word zufällig
im Diktat vorkommt.
**Aufwand: S** (Timer in der bestehenden Armed-Logik)

---

## Stufe 2 — mittel, klarer Mehrwert (je 1–2 Sitzungen)

### 6. Aktionable Insights
Drei Karten, die aus Zahlen Vorschläge machen:
- „**Diese 5 Wörter** korrigierst du am häufigsten → als Wörterbuch-Regel anlegen?"
  (Ein-Klick-Übernahme; Datenquelle: Rückfrage-Historie + Wort-Diffs)
- „**Fallback-Quote steigt** seit 3 Tagen → läuft Ollama stabil?"
- „**Kaltstart-Verlauf**": Latenzen als Zeitreihe, Kaltstarts sichtbar markiert.
**Warum Stufe 2:** Baut auf Welle-2-Daten des Härtungs-Plans auf (Wörterbuch-Zähler).
**Aufwand: M**

### 7. Nachverdichtung langer Diktate („Kimono, fass zusammen")
Ein langes Brainstorming-Diktat nachträglich auf Wunsch in Kernpunkte/Aufgaben
verdichten — als **Befehl** auf das letzte Diktat, nicht als Automatik. Nutzt das
vorhandene große Modell lokal; kein neuer Modus, sondern eine Erweiterung des
Befehls-Prompts um einen „verdichte"-Anweisungstyp (die Kompressions-Schwelle im
Plausibilitäts-Guard existiert bereits).
**Aufwand: M**

### 8. Code-Editor-Profil mit echtem Verhalten
Das „Coding"-Profil von „minimal" zu einem echten Editor-Profil ausbauen:
gesprochene Interpunktions-Kommandos („Klammer auf", „gleich") deterministisch
ersetzen, optional Kommentar-Präfix der Zielsprache („Kommentar: …" → `// …`).
**Warum:** Zielgruppennah (eigener Hauptanwendungsfall); differenziert Fleech von
Konkurrenz ohne Cloud.
**Aufwand: M**

### 9. Auto-Tonfall-Vorschlag je Profil
Beobachtete Korrekturmuster je App (aus der Historie) münden in einen Vorschlag:
„In Outlook korrigierst du oft zu formelleren Formulierungen — Stil-Tag
‚professioneller Ton' fürs Outlook-Profil übernehmen?" Nur Vorschlag, nie Automatik
(Wortgetreue bleibt Gesetz).
**Aufwand: M**

### 10. Profil-Vorschläge aus Nutzungsmustern
Wenn eine nicht zugeordnete App wiederholt stark abweichende Korrekturmuster zeigt:
„Für Obsidian ein eigenes Profil anlegen?" — Ein-Klick, vorbefüllt.
**Aufwand: M** (Datengrundlage wie Nr. 9)

---

## Stufe 3 — groß oder Nische (eigenes Konzept nötig, bewusst später)

### 11. Session-Modus / Edit-Mode
Befehle beziehen sich auf die letzten N eigenen Diktate im selben Feld statt nur
auf den letzten Block. *Bereits im Härtungs-Plan als Welle 3 eingeplant — hier nur
der Vollständigkeit halber; der Markt-Trend („Edit-Mode" bei Wispr Flow/VoiceOS)
bestätigt die Richtung.*

### 12. Speech-to-Action (Termine, Nachrichten, Issues)
Echte Aktionen mit Bestätigungsschritt. **Zurückgestellt:** kollidiert mit der
Identität (lokal, keine Konten), erfordert je Integration API-Pflege. Wenn, dann
als klar getrenntes Opt-in-Modul mit lokalem Erst-Ziel (z. B. Datei/Obsidian-Notiz
statt Google Calendar).

### 13. Mehrsprachige Zonen
Sprache pro Profil statt global (DE-Mail vs. EN-Code-Kommentare). Whisper kann
„auto" bereits — der Mehrwert wäre erzwungene Konsistenz je Ziel-App. Warten auf
realen Bedarf.

### 14. Formularfeld-Diktat („Segment bei Pause → Tab")
Nische; nur als klar markiertes Experiment, falls je gebraucht.

### 15. Voice Control (UI-Bedienung per Sprache)
Eigenständige Produktkategorie (Accessibility). Außerhalb des Fleech-Kerns;
allenfalls nach einem Accessibility-Pass der eigenen Oberfläche sinnvoll.

### 16. Struktur-Erkennungsrate als Metrik
Erst sinnvoll, wenn der Cleanup Listen-/Absatzstruktur aktiv erzeugt („strong"
tut das ansatzweise). Vorher fehlt die Datengrundlage.

---

## Empfohlene Gesamt-Reihenfolge

```
Härtung Welle 1  ──►  Ideen 1–3 (Snippets, Export, Privacy-Karte)
      │                       │
      ▼                       ▼
Härtung Welle 2  ──►  Ideen 4–6 (Befehls-Statistik, Safe-Word-Fenster, akt. Insights)
      │                       │
      ▼                       ▼
Härtung Welle 3  ──►  Ideen 7–10 (Verdichten, Code-Profil, Tonfall, Profil-Vorschläge)
                              │
                              ▼
                     Stufe 3 nur mit konkretem Anlass
```

Prinzip: **Nach jeder Härtungs-Welle eine Belohnungs-Runde Features** — so bleibt
die Basis solide, ohne dass die Weiterentwicklung monatelang unsichtbar ist. Snippets
(Nr. 1) ist der empfohlene Einstieg: kleinster Aufwand, täglicher Nutzen, null Risiko
für die bestehende Pipeline.
