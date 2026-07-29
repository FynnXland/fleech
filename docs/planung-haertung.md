# Planungskonzept: Härtung & Behebung der Research-Befunde

> Grundlage: externes Research-Dokument (4 Dimensionen, 25 Befunde) auf Basis von
> `fleech-gesamtkonzept.md`. Diese Planung bewertet jeden Befund **gegen den echten
> Code** (die Research kannte nur die Doku), sortiert nach Nutzen für den realen
> Einsatz (Windows-Hauptsystem + Kubuntu/X11, Einzelnutzer, Coding/Mathe/Prompting)
> und legt eine konkrete Umsetzungsreihenfolge in vier Wellen fest.

---

## 0. Vorab: Was die Research übersieht oder überschätzt

Die Research hat nur die Konzept-Doku gelesen. Vier Befunde sind gegen den Code
geprüft **schwächer als dargestellt** — das ändert die Priorisierung:

| Behauptung | Realität im Code | Konsequenz |
|---|---|---|
| „Stilles Versagen bei Fallbacks" | Fallback spielt bereits den Fehler-Sound, setzt die Statuszeile „eingefügt (Fallback — Log prüfen)" und landet als Status in der Historie. Es fehlt nur ein **visuelles** Signal an der Pille selbst. | Kleiner Rest-Fix statt großem Feature |
| „Kein Schema-Validator fürs Befehls-JSON" | `parse_command_json` fängt fehlende Felder (Defaults), kaputtes JSON (`ValueError` → Fallback) und unbekannte Scopes (Degradierung auf `as_described`) bereits ab. Es fehlt nur ein **Längendeckel** für `replacement`. | Ein 5-Zeilen-Guard, kein Pydantic |
| „Editierbare Prompts als alleinige Verteidigungslinie" | Die Delimiter-Rahmung (`⟦TRANSKRIPT⟧` + Anweisung) wird **im Code** um jede Nachricht gelegt (`wrap_transcript`), nicht im Prompt-File. Grounding- und Wortgetreue-Guard sind ebenfalls Code. Ein zerschossenes `cleanup.md` verliert nur Schicht 2 von 3. | Absicherung sinnvoll, aber klein (Lade-Validierung), nicht kritisch |
| „Race Condition zwischen Aufnahmestart und Formel-Job" | Der beschriebene Mechanismus stimmt nicht: Formel-Jobs werden beim Stopp **eingesammelt und als Schnappschuss** an den Verarbeitungs-Thread übergeben; ein neues Diktat startet mit frischen Job-Listen. **Aber:** Der Kern des Befunds ist real auf anderem Weg — zwei `_process`-Threads können überlappen (Diktat 2 endet, während Diktat 1 noch verarbeitet), und der `DocumentTracker` ist ungeschützt. | Richtiges Problem, andere Lösung: Verarbeitung serialisieren |

Zwei Befunde sind dagegen **wichtiger, als die Research ahnt**:

- **Grounding aus bei `auto_latex`**: Inzwischen hängt am selben Schalter auch der
  neue **Wortgetreue-Guard** (v1.6.x) — bei aktiver Formel-Automatik sind also *beide*
  Ausgabe-Prüfungen aus, nicht nur eine.
- **Clipboard-Timing**: Die 50 ms sind hart kodiert; genau die Ziel-Apps des Nutzers
  (VS Code, Discord = Electron) sind die Risikogruppe.

---

## 1. Bewertung aller Befunde im Überblick

Legende: **Urteil** = trifft zu / teilweise / bereits gelöst · **W** = Welle (1–4, — = bewusst nicht geplant)

### Dimension 1 — Architektur

| Befund | Urteil | Aufwand | W | Kern der Umsetzung |
|---|---|---|---|---|
| Race Condition Formel-Job/Aufnahme | teilweise (anderer Mechanismus) | S | **1** | `_process` global serialisieren (Lock), `DocumentTracker` eigenes Lock, Interleaving-Test |
| God-Class `pipeline.py`/`desktop.py` | trifft zu, aber Risiko>Nutzen | XL | — | Kein Big-Bang-Refactor: 401 Tests sichern den Ist-Stand; Strategy-Pattern erst, wenn Modus Nr. 5 ansteht |
| Qt-Bus deckt Worker↔Worker nicht ab | trifft zu | S | **1** | erledigt sich mit dem Tracker-Lock (gleicher Fix) |
| Fehlende Sub-Zustände (Modell lädt, Retry …) | trifft zu | M | **2** | Kein neuer State nötig: vorhandenen `feedback`-Kanal nutzen („Modell lädt …", „Formel 2/4 …") |
| Magic Numbers f. leise Sprecher (0,004) | plausibel, kein realer Fall | M | — | Erst bei echtem Auftreten; bis dahin loggt der Stille-Filter jede Verwerfung ohnehin |
| Timing-Test-Lücken | trifft zu | M | **3** | Mock-Clipboard mit künstlicher Latenz, sobald die aktive Verifikation (W1) drin ist |

### Dimension 2 — LLM & Prompts

| Befund | Urteil | Aufwand | W | Kern der Umsetzung |
|---|---|---|---|---|
| Grounding aus bei `auto_latex` | **trifft zu, verschärft** | S–M | **1** | LaTeX-toleranter Check: `$…$`-Blöcke ausfiltern, Rest gegen Grounding- UND Wortgetreue-Guard prüfen. Zusatz: Plausibilitätsdeckel „nicht mehr `$…$`-Blöcke als Wortgruppen" |
| Prompts ohne Sicherheits-Absicherung | teilweise (2 von 3 Schichten sind Code) | S | **1** | Lade-Validierung: fehlt der Marker-Abschnitt in `cleanup.md`/`command.md` → WARN-Log + programmatisch angehängter Sicherheitsblock |
| Klassifikation: Code-Diktate als „trivial" | **trifft zu, Zielgruppen-relevant** | S | **1** | Dritte Regex-Ebene in `classify_complexity`: „Klammer", „Komma", „gleich", „Punkt" als gesprochene Tokens, CamelCase-/Versionsmuster → `complex` |
| Denkblock-Formate unbekannter Modelle | trifft zu, latent | S | **2** | Regex-Liste in `config.yaml` konfigurierbar machen; Meta-Kommentar-Heuristik („Okay, ich soll…") als Zusatz-Check vor der Injection |
| Befehls-JSON-Validator | größtenteils gelöst | S | **1** | Nur nachrüsten: `replacement` länger als 3× Ziel → Befehl verwerfen (Guard C) |
| Wörterbuch-60er-Limit intransparent | trifft zu | M | **2** | Priorisierung: Treffer-Zähler je Begriff (Ersetzung/Rückfrage) in settings; Top-60 nach Nutzung; UI-Hinweis „62 von 78 aktiv geprimt" |
| Kein Ersatzschutz bei Formeln (minor) | trifft zu | S | **1** | im LaTeX-toleranten Check enthalten (Blockzahl-Deckel) |

### Dimension 3 — UX & Produkt

| Befund | Urteil | Aufwand | W | Kern der Umsetzung |
|---|---|---|---|---|
| Kein Onboarding | trifft zu (Produkt-Sicht) | L | **3** | Wizard beim Erststart: Mikro-Test → Hotkey → 4 Modi je 1 Satz + Probediktat → Safe-Word. Aus Einstellungen erneut aufrufbar |
| Stilles Fallback-Versagen | teilweise (Sound+Status existieren) | S | **1** | Pille: ✓ blinkt bei Fallback **amber** statt cyan; Transkript-Blase bekommt dezenten amber Rahmen. Kein neuer Toast (Politik: so wenig Banner wie möglich) |
| Safe-Word in sensiblen Kontexten | trifft zu | S | **2** | `command_enabled` wird pro Profil übersteuerbar („Geschäftlich": Safe-Word aus, »-Knopf bleibt) |
| App-Zuordnung über Prozessnamen fragil | trifft zu, für Solo-Betrieb mild | M | **3** | Zweitkriterium Fenstertitel-Regex (optional pro Profil); Hinweis auf Profilseite, wenn ein zugeordneter Prozess >30 Tage nicht gesehen wurde |
| Kein Session-Kontext über Diktate | trifft zu (Feature, kein Bug) | L | **3** | `DocumentTracker` behält pro (Fenster, Feld) die letzten N Blöcke statt nur den letzten; Befehls-Scope „dictated" bekommt Zugriff auf ältere eigene Blöcke; Session-Punkt in der Pille |
| Insights rein deskriptiv | trifft zu | M | **2** | 3 aktionable Karten (s. Ideen-Datei, Stufe 1): Korrektur-Wörter → Regel anlegen, Fallback-Trend, Kaltstart-Verlauf |
| Kein Smart-Positioning der Pille | trifft zu | M | **3** | Beim Aufnahmestart: Caret-Position (liegt für Cursor-Rückkehr ohnehin vor) gegen Pillen-Rechteck prüfen → temporär in die nächste freie Ecke ausweichen, danach zurück. Opt-in |
| Diktat über Formularfelder | Nische | M | — | nicht geplant (siehe Ideen-Datei, Stufe 3) |

### Dimension 4 — Plattform

| Befund | Urteil | Aufwand | W | Kern der Umsetzung |
|---|---|---|---|---|
| Kein Wayland-Support (Fokus/Cursor/Vollbild) | trifft zu, aktuell ohne realen Nutzer | XL | **4** | Eigenes Projekt: xdg-desktop-portal (GlobalShortcuts, RemoteDesktop). Vorgezogen in W2: **ehrliche Degradation** — unter Wayland beim Start einen Settings-Hinweis zeigen, was nicht geht, statt still zu schweigen |
| Clipboard 50 ms zu kurz für Electron/VM | **trifft zu** | S | **1** | Aktive Verifikation: nach dem Schreiben zurücklesen (Poll alle 20 ms, Deckel 400 ms), erst dann Strg+V. Ersetzt die blinde 50-ms-Pause; bei Nicht-Bestätigung trotzdem senden (Fail-Open) + WARN-Log |
| Loopback-Erkennung nur über Namen | trifft zu | M | **3** | Wo die API es hergibt (WASAPI-Flow/PulseAudio-Monitor-Flag) technisch prüfen; zusätzlich nutzerpflegbare Sperrliste in den Einstellungen |
| Multi-Monitor-DPI beim Klick-Restore | teilweise (Fehlklick wird schon verhindert) | M | — | Point-in-Window-Verifikation fängt den Schadensfall ab; beobachten, erst bei realem Fehlverhalten anfassen |
| Accessibility (Screenreader, Tab-Ordnung) | trifft zu (Produkt-Sicht) | L | **4** | `accessibleName` systematisch, Tab-Reihenfolge, ein NVDA-Durchlauf — gebündelt vor einer etwaigen Veröffentlichung |

---

## 2. Die vier Wellen

### Welle 1 — „Korrektheit & Vertrauen" (klein, sofort; ~1 Sitzung)

Alles, was Diktat-Ergebnisse falsch machen oder Schutz aushebeln kann. Nur kleine,
gut testbare Eingriffe — jede Änderung mit eigenem Test.

1. **Verarbeitung serialisieren.** Ein `_process`-Lock in `desktop.py` (Diktate sind
   aus Nutzersicht ohnehin sequenziell) + `threading.Lock` um alle
   `DocumentTracker`-Mutationen + ein Interleaving-Test (zwei überlappende
   Verarbeitungen, Tracker bleibt konsistent).
2. **LaTeX-toleranter Ausgabe-Schutz.** Neue Helfer `strip_latex_blocks(text)`;
   bei `auto_latex` laufen Grounding **und** Wortgetreue auf dem formelbereinigten
   Text statt gar nicht. Deckel: mehr `$…$`-Blöcke als plausibel → Rohtext-Fallback.
3. **Aktive Clipboard-Verifikation** in `injection.py` (Poll statt 50-ms-Blindflug),
   Timeout 400 ms, Fail-Open, Test mit künstlich verzögertem Mock-Backend.
4. **Fallback sichtbar machen:** amber ✓-Blink + amber Blasenrahmen (Farbsprache
   existiert; kleine Änderung in `overlay_qt.py` + `desktop.py`-Verdrahtung).
5. **Code-Diktat-Heuristik** in `classify_complexity` (Regex-Ebene 3 → `complex`).
6. **Prompt-Lade-Validierung** in `prompts.py`: Marker-Abschnitt fehlt → WARN +
   Code-seitiger Sicherheitsblock wird angehängt.
7. **Replacement-Längendeckel** (3× Ziellänge) als Guard C in `_handle_command`.

*Lieferung wie immer: Tests → Build → Sync → Neustart; Punkte 2, 5, 6 zusätzlich
live gegen Ollama.*

### Welle 2 — „Alltag & Transparenz" (mittel; 1–2 Sitzungen)

8. **Sub-Zustands-Feedback** über den vorhandenen `feedback`-Kanal: „Modell lädt …",
   „Formel wird berechnet (Versuch 2/4) …" — Overlay-Blase + Tray-Tooltip.
9. **Wörterbuch-Priorisierung** (Nutzungszähler, Top-60, UI-Hinweis „X von Y geprimt").
10. **Aktionable Insights, Stufe 1** (drei Karten, siehe Ideen-Datei).
11. **Safe-Word pro Profil abschaltbar** (Standard: „Geschäftlich" ohne Safe-Word).
12. **Wayland-Ehrlichkeit:** Erkennung + Hinweistext in den Einstellungen, welche
    Funktionen dort degradiert laufen (noch kein Portal-Support).
13. **Denkblock-Muster konfigurierbar** + Meta-Kommentar-Heuristik.

### Welle 3 — „Produktreife" (groß; je eigene Sitzung mit eigenem Konzept)

14. **Onboarding-Wizard** (Erststart + aus Einstellungen aufrufbar).
15. **Session-Kontext** über mehrere Diktate (Tracker-Erweiterung + Pillen-Indikator
    + Timeout) — vorher kurzes Design-Dokument, das betrifft den Befehls-Modus im Kern.
16. **Profil-Zuordnung härten** (Fenstertitel-Regex, „lange nicht gesehen"-Hinweis).
17. **Smart-Positioning der Pille** (Caret-Kollision, opt-in).
18. **Loopback technisch erkennen** + Sperrliste.
19. **Timing-Fuzz-Tests** (verzögerte Mock-Backends für Clipboard/Fokus).

### Welle 4 — „Expansion" (nur mit Anlass)

20. **Wayland-Portale** (GlobalShortcuts/RemoteDesktop) — lohnt erst, wenn Fleech
    auf einem Wayland-System real genutzt wird oder verteilt werden soll.
21. **Accessibility-Pass** (NVDA/Orca) — gebündelt vor einer Veröffentlichung.

### Bewusst nicht geplant (mit Begründung)

- **Strategy-Pattern-Refactor:** Die Orchestrierung ist getestet (401 Tests) und
  die Modi teilen sich real viel Logik (Fallback-Kette, Guards, Injection). Ein
  Refactor jetzt wäre Risiko ohne Nutzerwert. Wiedervorlage: wenn Modus Nr. 5 kommt.
- **Pydantic:** keine neue Abhängigkeit für etwas, das `parse_command_json` bereits
  leistet.
- **Pegel-Kalibrierung / DPI-Restore:** keine realen Fehlerbilder; beide Pfade loggen
  bzw. verifizieren bereits. Erst anfassen, wenn es tatsächlich auftritt.

---

## 3. Reihenfolge-Begründung (Kurzform)

1. **Erst Korrektheit, dann Komfort:** Welle 1 enthält alles, was *falsche Ergebnisse*
   produzieren kann (Schutzlücke bei `auto_latex`, Clipboard-Fehleinfügung,
   Tracker-Races, Code-Diktate ohne Modell). Das sind die einzigen Punkte, bei denen
   Warten Schaden anrichtet.
2. **Sichtbarkeit vor neuen Features:** Fallback-Signal und Sub-Zustände (W1/W2)
   machen das bestehende Verhalten verstehbar — Voraussetzung dafür, dass sich neue
   Features überhaupt beurteilen lassen.
3. **Großes nur mit eigenem Konzept:** Onboarding, Session-Kontext und Wayland sind
   jeweils eigene Projekte mit UX-Entscheidungen. Sie in „nebenbei"-Wellen zu quetschen
   würde die CLAUDE.md-Qualitätskette (Tests, Live-Prüfung, Abnahme) unterlaufen.
4. **Plattform folgt Nutzung:** Wayland ist strategisch wichtig, aber ohne realen
   Wayland-Arbeitsplatz nicht testbar — deshalb zuerst die ehrliche Degradation (W2),
   der echte Support erst mit Anlass (W4).
