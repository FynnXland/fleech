# Funktions-Bewertung und LLM-Balance (Stand 2.1.0)

> Auslöser: sechs konkrete Beschwerden aus dem Alltagsbetrieb plus der Auftrag,
> die Funktionen zu bewerten, auszusortieren und die Arbeitsteilung mit dem
> lokalen Modell zu überdenken. Grundlage sind **740 echte Diktate** aus
> `fleech.log` (4,7 MB), nicht Vermutungen.

---

## 1. Die sechs Befunde — was wirklich dahintersteckte

### 1.1 Autostart startet nicht

**Vermutung:** Antivirus löscht den Registry-Eintrag.
**Messung:** Ein Testwert im `Run`-Key überlebte unverändert. Der Eintrag wird also
nicht von außen entfernt. Im Log stand fünfmal in Folge „Autostart laut Einstellungen
gewünscht, aber kein Eintrag — stelle her"; in der `settings.json` steht
`autostart: false`, obwohl der Wunsch nachweislich einmal `true` war.

**Ursache:** Ein selbstverstärkender Fehler in der eigenen Logik. `_apply_autostart`
schrieb den Eintrag, verifizierte ihn und setzte bei fehlgeschlagener Verifikation
**den Nutzerwunsch selbst auf `false`**. Beim nächsten Start sah der Abgleich dann
„Wunsch = aus, Eintrag vorhanden" und **löschte den Eintrag aktiv**. Ein einziger
misslungener Schreibversuch schaltete den Autostart damit dauerhaft ab — ohne dass
je jemand etwas abgeschaltet hätte.

**Behoben:** Der Wunsch wird immer gespeichert, auch wenn das Schreiben scheitert;
Fleech versucht es bei jedem Start erneut. Zusätzlich liest Fleech jetzt die
Freigabe-Liste `StartupApproved`, mit der Windows einen vorhandenen Eintrag
stillschweigend außer Kraft setzen kann (Task-Manager → Autostart). Genau dieser
Fall war bisher unsichtbar und hätte auch nach dem Fix zu „steht drin, startet
trotzdem nicht" geführt.

### 1.2 „Halluziniert häufig am Satzende"

Das ist der wichtigste Befund, und die Messung korrigiert das Bild.

Von 740 Diktaten hatten **11** einen schwach gestützten Schlusssatz. Davon war genau
**einer** eine echte Halluzination (ein angehängter, nie gesprochener Satz) — und den
hatte der bestehende Guard bereits gefangen. Die anderen zehn waren etwas anderes:
**Ausschmückung**. Das Modell hängt nichts an, es **baut den letzten Satzteil um**:

| gesprochen | eingefügt |
|---|---|
| „kannst du mir das vielleicht visualisieren" | „…visuell **darstellen**?" |
| „ich fände schon gut, die irgendwo anzuzeigen" | „…**wenn sie** irgendwo **angezeigt würde**" |
| „da ich diese versuche konkret einzuhalten" | „da ich diese **Versuchung** auch konkret **einbeziehe**" |

Der dritte Fall ist der schlimmste: aus einem undeutlich diktierten Satz wurde ein
**anderer Sinn**. Zusätzlich hatten **108 von 682** Diktaten mehr Wörter in der
Ausgabe als in der Eingabe.

**Warum kein Guard griff — zwei unabhängige Gründe:**

1. **Die Kennzahl misst die falsche Richtung.** `verbatim_ratio` zählt, wie viele
   gesprochene Wörter *überleben*. Wer „visualisieren" durch „visuell darstellen"
   ersetzt, behält alle Originalwörter — der Wert bleibt hoch, der Guard schweigt.
2. **Der Schutz war im Betriebsmodus des Nutzers komplett abgeschaltet.** In
   `_enforce_verbatim` stand `if intervention == "strong" or self.auto_latex: return`.
   Wer die automatische Formel-Erkennung aktiviert hat — bei gemischter Arbeit ein
   Dauerzustand — diktierte also **völlig ungeschützt**. Das erklärt „sehr häufig"
   restlos.

**Behoben:** Neuer Kennwert `added_ratio` misst die Gegenrichtung (Wörter, die
niemand gesagt hat). Bei aktiver Formel-Automatik wird jetzt auf dem
*formelbereinigten* Text gemessen, statt den Schutz abzuschalten. Die Wortgetreue
selbst bleibt dort ausgespart — „x hoch zwei" wird legitim zu `$x^2$`, die Rohwörter
verschwinden also zu Recht.

**Kalibrierung an den echten Daten:** Die Grenze von 22 % neuen Wörtern löst bei
**1,2 %** der 740 Diktate einen Zweitversuch aus. Sie fängt die groben Fälle
(Sinnentstellung, als Prompt ausgeführte Diktate mit 79–88 % neuen Wörtern), ohne
für jedes zweite Diktat Latenz zu erzeugen.

**Die milden Fälle löst der Prompt, nicht der Guard.** Ein Zweitversuch für jedes
umformulierte Wort wäre teuer erkauft. Stattdessen stehen die drei echten
Fehlausgaben jetzt wörtlich als Gegenbeispiele in `prompts/cleanup.md`. Der Live-Test
gegen Ollama zeigt: **alle vier Beschwerdefälle sind behoben**, ohne dass der Guard
überhaupt eingreifen muss.

### 1.3 Formatierung „nicht übertreiben"

Das ist dasselbe Problem wie 1.2 und mit derselben Maßnahme erledigt. Die Grenze ist
bewusst nicht null: Ein ergänztes „es" oder „dass" ist Grammatik und bleibt erlaubt.
Der Merksatz im Prompt: *Ein Wort, das im Diktat nicht vorkam, brauchst du nur dann,
wenn ohne es der Satz grammatisch falsch wäre.*

### 1.4 Inhalte rechts abgeschnitten

Die Startgröße war **780 × 560** — zu klein für die dreispaltige Profilseite und die
Insights-Reihen. Schlimmer: Es gab **gar keine Mindestgröße**, das Fenster ließ sich
in einen Zustand ziehen, in dem Text einfach verschwand.
**Behoben:** Start bei 1120 × 780, Minimum 940 × 620.

### 1.5 Mathe-Einstellungen umständlich

Für ein Ziel („erkenne Formeln automatisch") musste man **dreimal richtig raten**:
Priorität auf „Gemischt", Härtung an, Automatik an. Die drei Schalter sind technisch
sinnvoll, als Bedienelemente waren sie eine Zumutung.
**Behoben:** Ein Auswahlfeld **Formel-Erkennung** mit vier Stufen (Automatisch / Auf
Ansage / Nur Umschalt-Taste / Aus). Die technischen Felder werden daraus gesetzt —
keine neue Einstellung, keine Migration, bestehende Konfigurationen bleiben gültig.
Die Stufe „Automatisch" schaltet die Härtung bewusst mit ein: Wer Formeln im
Fließtext erkennen lässt, diktiert längere Ausdrücke, und getrennt eingeschaltet hat
sie im Alltag nie jemand.

### 1.6 Einstellungen unübersichtlich

Zwölf Seiten, rund 52 Bedienelemente. Die Ursache ist nicht mangelnde Erklärung —
es ist schlicht zu viel. Siehe Abschnitt 2.

---

## 2. Funktions-Bewertung: behalten, zusammenfassen, aussortieren

Bewertet nach realem Nutzen im Log (wie oft greift es?) gegen Bedienkosten.

### Tragende Säulen — unangetastet

Diktat mit Bereinigung, Safe-Word-Befehle, Formel-Modus, KI-Prompting, Wörterbuch,
Profile, Cursor-Rückkehr, Verlauf/Insights, Overlay-Pille. Alle im Log nachweislich
in Gebrauch.

### Zusammenfassen (weniger Schalter, gleiche Fähigkeit)

| Bisher | Neu | Begründung |
|---|---|---|
| Mathe: Priorität + Härtung + Automatik | **eine Stufe** | umgesetzt, siehe 1.5 |
| Overlay: 4 Einzelränder (`edge_*`) | ein „Kompaktheit"-Regler | vier Zahlenfelder für eine Optik-Frage; niemand stellt links und rechts unterschiedlich ein |
| Benachrichtigungen: 6 Toast-Schalter | „Wichtiges / Alles / Nichts" | die Einzelfälle sind für einen Einzelnutzer nicht unterscheidbar |

*Overlay- und Benachrichtigungs-Zusammenfassung sind vorgeschlagen, noch nicht
umgesetzt — sie ändern gewachsene Layouts und gehören in einen eigenen Schritt mit
Render-Prüfung.*

### Aussortieren — Kandidaten mit Begründung

- **Overlay `level_gain`** (Pegel-Empfindlichkeit): rein kosmetisch, betrifft nur den
  Ausschlag der Waveform. Der neue Pegelbalken im Onboarding macht die Kalibrierung
  ohnehin überflüssig. → in „Advanced" verschieben oder streichen.
- **`separate_islands`** (Inseln vs. durchgehende Pille): reine Geschmacksfrage, die
  im Log nie umgestellt wurde. → in „Advanced".
- **Sound-Preset „click" vs. „soft"**: zwei fast identische Klangsätze. → einer reicht.
- **Insights-Sichtbarkeitsschalter (11 Stück)**: Das ist ein Schalter *pro Karte*.
  Wer eine Karte nicht mag, blendet sie aus — aber elf Checkboxen für neun Karten
  sind mehr Bedienoberfläche als Nutzen. → durch direktes Ausblenden an der Karte
  selbst ersetzen (Kontextmenü), Seite „Oberfläche" entfällt damit fast ganz.

### Erweitern — was im Log fehlt

- **Ein „Diktat rückgängig"-Weg.** Der häufigste unerfüllte Wunsch nach einer
  Fehlausgabe. Der Befehls-Modus deckt das nur ab, solange der Cursor steht.
- **Formel-Vorschau vor dem Einfügen.** Der Formel-Pfad ist der einzige, der über
  ein Cloud-Modell läuft und der teuerste; eine kurze Bestätigung wäre dort mehr
  wert als überall sonst.

---

## 3. LLM-Balance: lokal bleiben, aber klüger verteilen

Ausgangslage: zwei lokale Modelle (`qwen3.5:9b` für Komplexes, `qwen2.5:3b` für
Einfaches) plus ein Cloud-Modell ausschließlich für Formeln (Audio-Verständnis, das
lokale Textmodelle nicht leisten können).

**Die Messung zeigt zwei Ungleichgewichte:**

1. **Das schnelle Modell ist unzuverlässiger als angenommen.** Beim Baustein-Test
   verschluckte `qwen2.5:3b` in zwei von drei kurzen Sätzen die Platzhalter. Seitdem
   gehen Diktate mit Platzhaltern (Bausteine, Inline-Formeln) immer ans große Modell.
   Dieselbe Vorsicht gilt bereits für Zahlen, Selbstkorrekturen und Code-Diktate.
2. **Der Zweitversuch ist das schärfste verfügbare Werkzeug und wurde kaum genutzt.**
   Mit dem neuen Aufbläh-Kennwert greift er dort, wo er wirkt (1,2 % der Diktate),
   und kostet dort ~4–8 s — akzeptabel, weil selten.

**Empfehlung zur Arbeitsteilung — in dieser Reihenfolge:**

1. **Prompt vor Guard vor Modellwechsel.** Der Live-Test hat gezeigt: Drei konkrete
   Gegenbeispiele im Prompt haben alle vier Fehlerfälle behoben — zum Nulltarif.
   Erst wenn das nicht reicht, ein Guard; erst wenn der nicht reicht, ein größeres
   Modell.
2. **Beim lokalen Modell bleiben.** Für Bereinigung und Befehle ist `qwen3.5:9b`
   nachweislich stark genug; die Fehler kamen aus Prompt und fehlenden Guards, nicht
   aus fehlender Modellgröße. Ein externes Textmodell würde das Datenschutz-Versprechen
   für einen Gewinn aufgeben, der bisher nicht belegt ist.
3. **Externes Modell nur als bewusster Notausgang.** Falls doch gewünscht: als
   *Zweitversuch*-Ziel, wenn das lokale Modell zweimal gescheitert ist — nicht als
   Regelpfad. Ein solcher Aufruf gehört sichtbar gemacht (die Privacy-Zeile in den
   Insights zählt bereits mit) und muss abschaltbar bleiben. **Nicht in dieser
   Runde umgesetzt**, entsprechend dem Wunsch, primär lokal zu bleiben.
4. **RAM-Balance ist gelöst und sollte so bleiben.** Idle-Entladung nach 10 min und
   sofortiges Entladen bei erkanntem Spiel funktionieren; das Vorladen beim
   Aufnahmestart versteckt die Ladezeit hinter dem Sprechen.

---

## 3a. Nachtrag: drei gemessene Optimierungen — alle drei verworfen

Nach der ersten Runde wurden drei naheliegende Beschleunigungen **gemessen statt
angenommen**. Keine hat gehalten, was sie versprach. Das ist das eigentliche
Ergebnis: **Die Verteilung ist bereits richtig kalibriert.**

| Hypothese | Messung | Ergebnis |
|---|---|---|
| Der wachsende System-Prompt (2880 Tokens) und die dynamischen Zusätze zerstören Ollamas Prefix-Cache | konstanter vs. wechselnder System-Prompt | **−8 % (Rauschen)** — kein Umbau nötig |
| Die 24-Wort-Grenze zum schnellen Modell ist zu vorsichtig | 8 echte Diktate mit 25–45 Wörtern, beide Modelle | **verworfen**: Wortgetreue 0,87 statt 0,96, dreifache Ausschmückung — ein Satz wurde komplett umgebaut |
| Lange Diktate in Blöcke teilen und parallel bereinigen | 123-Wort-Diktat, ein Aufruf vs. zwei parallele | **−3 %**: Ollama arbeitet die Anfragen nacheinander ab |

**Ein Nebenbefund war wertvoll:** Bei kurzen Diktaten (≤24 Wörter) ist das *kleine*
Modell nicht nur 2,3× schneller, sondern schmückt auch **weniger** aus (0,08 gegen
0,14 beim großen). Die bestehende Regel „kurz → klein" ist damit doppelt bestätigt —
sie spart Zeit *und* verbessert die Treue. Umgekehrt gilt ab 25 Wörtern das
Gegenteil. Die Grenze bleibt, wo sie ist.

**Konsequenz für die Latenz:** Die Ø 4,7 s bei langen Diktaten sind reine
Generierungszeit, kein Overhead. Daran ist mit Bordmitteln nichts zu holen; der
einzige verbleibende Hebel wäre ein anderes Modell oder Ollamas `num_parallel` —
beides außerhalb von Fleech.

## 3b. Die beiden Mathe-Wege sind nicht redundant

Die Frage „wozu noch ein Mathe-Modus, wenn die Automatik ohnehin Formeln erkennt?"
ist berechtigt — die Nutzungsdaten scheinen sie zu bestätigen: Von 738 Diktaten
liefen nur **18 (2,4 %)** über den Formel-Pfad, davon **4** als reiner Formel-Modus.

Technisch sind es aber **zwei verschiedene Verfahren**:

| | Automatik (`auto`) | Umschalt-Taste / „Formel …" |
|---|---|---|
| Eingabe | **Text** (das fertige Transkript) | **Audio** (die Aufnahme selbst) |
| Modell | lokal | Cloud (multimodal) |
| Stärke | bequem, kein Umschalten, 100 % lokal | hört Betonung und Pausen → erkennt Struktur |
| Schwäche | rät die Struktur aus Wörtern | Netz nötig, langsamer |

Bei „x plus eins durch zwei" entscheidet die **Pause**, ob (x+1)/2 oder x + 1/2
gemeint ist — diese Information existiert im Transkript nicht mehr. Deshalb bleibt
der Audio-Weg erhalten; er ist kein doppelter Modus, sondern die *genauere* Stufe
derselben Funktion.

**Umgesetzt wurde die ehrliche Erklärung statt eines Umbaus:** Die Auswahl in den
Einstellungen sagt jetzt bei jeder Stufe, welcher Weg genutzt wird und was er kann.
Wer nie komplexe Formeln diktiert, wählt „Automatisch" und sieht den anderen Weg nie.

## 4. Was in dieser Runde umgesetzt wurde

| Punkt | Status |
|---|---|
| Wortgetreue-Schutz bei Formel-Automatik reaktiviert | **umgesetzt** |
| Aufbläh-Kennwert `added_ratio` + Zweitversuch | **umgesetzt** |
| Prompt um drei echte Gegenbeispiele geschärft | **umgesetzt, live geprüft** |
| Block-Formeln (`$$…$$`, `\[…\]`) beim Messen ausblenden | **umgesetzt** |
| Autostart: Wunsch bewahren + Windows-Deaktivierung erkennen | **umgesetzt** |
| Fenster: Startgröße 1120×780, Minimum 940×620 | **umgesetzt** |
| Mathe: drei Schalter → eine Stufe | **umgesetzt** |
| Insights-Sichtbarkeit an die Karten verlagern | **umgesetzt** (Seite „Oberfläche" entfallen) |
| Waveform-Auto-Gain für leise Mikrofone | **umgesetzt** |
| Beide Mathe-Wege in der UI erklärt | **umgesetzt** |
| Overlay-/Benachrichtigungs-Schalter zusammenfassen | vorgeschlagen |
| Rückgängig-Weg, Formel-Vorschau | vorgeschlagen |
| Externes LLM als Notausgang | bewusst zurückgestellt |

### Nachtrag zum Level-Gain

Der Regler war als Streich-Kandidat gelistet — zu Unrecht. Das gemeldete Problem
(leises Mikrofon, Waveform schlägt kaum aus) ist real; nur war der Regler die
falsche Antwort darauf, weil man ihn kennen und pro Mikrofon neu einstellen muss.
Jetzt normalisiert die Anzeige sich selbst auf den lautesten Pegel der laufenden
Aufnahme (mit Untergrenze, damit Stille nicht auf Vollausschlag verstärkt wird).
**Der Regler bleibt** und wirkt zusätzlich — die Automatik macht ihn meistens
überflüssig, ersetzt ihn aber nicht.
