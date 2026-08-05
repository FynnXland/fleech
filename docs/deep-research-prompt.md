# Prompt für ein externes Gutachten (Deep Research)

Diese Datei enthält den fertigen Auftragstext. Kopieren, die beiden Anhänge
mitgeben — fertig.

**Die beiden Anhänge:**

| Datei | Was drin steht | Umfang |
|---|---|---|
| `docs/fleech-gesamtkonzept.md` | Idee, jede Funktion, jede Einstellung, Architektur, alle Messwerte und die Begründungen dahinter | ~2100 Zeilen |
| `export/fleech-quellcode.md` | der vollständige Quellcode inkl. Tests und Prompts | 207 Dateien, ~600k Token |

Erzeugt wird der Export mit:

```bash
.venv/Scripts/python packaging/export_quellcode.py
```

Passt das nicht ins Kontextfenster, gibt es die Fassung ohne Testsuite
(`--ohne-tests`, ~424k Token). Dann im Prompt unten den Absatz zur Testsuite
streichen — sonst wird über etwas geurteilt, das gar nicht vorliegt.

**Vorher prüfen:** Der Export läuft über eine Geheimnis-Prüfung und meldet
Funde. Er enthält bewusst *keine* Diktate, keinen Verlauf, keine Einstellungen
und keinen Lizenzschlüssel — aber ein Blick in die Kopfzeilen vor dem Versand
kostet nichts.

---

## Der Prompt

> Du begutachtest **Fleech**, eine vollständig lokal laufende Diktier-Anwendung für
> Windows 11 und Linux (Python 3.11, PySide6, faster-whisper, Ollama). Sie läuft als
> Tray-Anwendung: Mikrofon → Spracherkennung → Sprachmodell-Bereinigung → der fertige
> Text landet im gerade fokussierten Eingabefeld. Kein Cloud-Dienst, keine
> Netzwerkverbindung im Betrieb.
>
> Ich gebe dir zwei Dateien: die **Gesamtdarstellung** (Konzept, jede Funktion, die
> Architektur und die Messwerte, auf denen die Entscheidungen beruhen) und den
> **vollständigen Quellcode** inklusive Testsuite.
>
> Ich suche kein Lob und keine Zusammenfassung dessen, was ohnehin dasteht. Ich suche
> die Stellen, an denen dieses Projekt in sechs Monaten Ärger machen wird, und die
> Gelegenheiten, die ich übersehen habe.
>
> **Arbeite die folgenden sechs Fragen ab. Belege jede Aussage am Code** — Datei und
> Funktion nennen. Wenn du etwas vermutest, aber nicht belegen kannst, schreib
> ausdrücklich „Vermutung" dazu.
>
> **1 · Korrektheit und Nebenläufigkeit.**
> Die Anwendung hat vier Threads, die sich Zustand teilen: den Qt-GUI-Thread, den
> Audio-Callback von PortAudio, einen Prüf-Thread für die Startworterkennung und
> Worker für die Verarbeitung. Wo wird geteilter Zustand ohne Absicherung angefasst?
> Wo kann ein Ereignis in der falschen Reihenfolge oder doppelt eintreffen? Wo hängt
> Korrektheit an einer Zeitannahme, die unter Last nicht gilt? Achte besonders auf
> `fleech/freihand.py`, `fleech/pipeline.py`, `fleech/ui/desktop.py` und
> `fleech/audio.py`.
>
> **2 · Die Schutzmechanismen gegen das Sprachmodell.**
> Das zentrale Risiko der Anwendung: Ein lokales Modell (`gemma3:4b`) bekommt ein
> Rohtranskript und soll es *bereinigen*, nicht umschreiben. Dagegen stehen mehrere
> Guards in `fleech/textfilter.py`. Prüfe sie einzeln: Was lässt jeder Guard
> durch, was fängt er ab, und wo ist die Lücke? Konstruiere konkrete Eingaben, die
> einen Guard aushebeln. Beurteile auch die Prompt-Dateien in `prompts/` — insbesondere,
> ob die Markierung des Nutzertextes (`⟦TRANSKRIPT⟧`) einer gezielten Anweisung im
> Diktat standhält.
>
> **3 · Die Architektur.**
> Zwischen den Versionen 5.4 und 5.9 wurden die großen Dateien nach Themen aufgeteilt
> (siehe Modulkarte). Ist der Schnitt an den richtigen Stellen erfolgt? Wo liegt Logik
> jetzt am falschen Ort, wo ist eine Abhängigkeit verdreht, wo ist etwas geteilt worden,
> das zusammengehört? Nenne konkret die Stellen, an denen die nächste Erweiterung teuer
> wird — und die Stellen, an denen die Aufteilung nur Dateien verschoben hat, ohne die
> Kopplung zu lösen.
>
> **4 · Die Testsuite.**
> Rund 1200 Tests. Wo geben sie falsche Sicherheit — Tests, die die Implementierung
> spiegeln statt das Verhalten zu prüfen, oder die bestehen würden, obwohl die Funktion
> kaputt ist? Welche realen Fehlerfälle sind gar nicht abgedeckt? Bewerte auch die
> Struktur-Tests (`test_ui_struktur.py`, `test_kernstruktur.py`), die Dateigrößen und
> Abhängigkeitsrichtungen erzwingen: Ist das eine sinnvolle Absicherung oder eine
> Regel, die zu Umgehungen einlädt?
>
> **5 · Datenschutz und Sicherheit.**
> Die Anwendung verspricht, dass nichts das Gerät verlässt und dass beim Lauschen
> nichts gespeichert wird. Halte diese Zusagen gegen den Code. Beachte: den
> Freihand-Ringpuffer, die opt-in-Diagnose in `fleech/freihand_diagnose.py`, den
> SQLite-Verlauf, die Zwischenablage, das Protokoll und die Lizenzprüfung
> (Ed25519, offline). Wo könnte Text an einer Stelle landen, die der Nutzer nicht
> erwartet?
>
> **6 · Der blinde Fleck.**
> Was würde ein erfahrener Entwickler an diesem Projekt sofort anders machen, das in
> der Gesamtdarstellung nicht einmal als Frage auftaucht? Welche Annahme wird
> durchgehend getroffen, ohne je geprüft worden zu sein?
>
> **Zum Umgang mit den Begründungen:** Viele Entscheidungen sind im Code ausführlich
> begründet, oft mit Messwerten. Nimm diese Begründungen ernst — aber prüfe sie. Wenn
> eine Messung eine falsche Frage beantwortet oder eine Schlussfolgerung nicht trägt,
> ist genau das ein wertvoller Befund.
>
> **Form der Antwort:** Nach Dringlichkeit sortiert, nicht nach Themen. Für jeden
> Punkt: was ist es, wo steht es (Datei + Funktion), was ist die Folge im Alltag, und
> was wäre die kleinste Änderung, die es behebt. Sag mir am Ende ausdrücklich, welche
> drei Punkte du zuerst angehen würdest und warum — und was du dir angesehen und für
> in Ordnung befunden hast, damit ich weiß, was geprüft ist.

---

## Warum der Prompt so aussieht

- **Zwei Dateien statt einer.** Der Code allein sagt nicht, *warum* etwas so ist; das
  Konzept allein lässt sich nicht überprüfen. Erst zusammen kann ein Gutachter eine
  Begründung gegen ihre Umsetzung halten.
- **„Kein Lob, keine Zusammenfassung."** Ohne diese Ansage kommt regelmäßig eine
  Nacherzählung der Architektur zurück — richtig, aber wertlos.
- **Belegpflicht mit Datei und Funktion.** Macht jede Behauptung nachprüfbar und
  filtert die Antworten heraus, die allgemein klingen und auf jedes Projekt passen.
- **„Vermutung" als erlaubte Antwort.** Wer raten darf, wenn er es kennzeichnet, muss
  nicht so tun, als hätte er alles gelesen.
- **Die Bitte um das Geprüfte-und-in-Ordnung.** Sonst weiß man nach dem Gutachten nur,
  was schlecht ist — nicht, was abgedeckt wurde.
- **Frage 6 zuletzt.** Sie ist die einzige ohne Vorgabe und liefert erfahrungsgemäß den
  Punkt, den man selbst nie gestellt hätte.
