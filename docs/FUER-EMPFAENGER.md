# Fleech einrichten

Diese Seite ist für dich, wenn du Fleech bekommen hast. Fünf Minuten Lesen,
davon zwei Minuten Arbeit — der Rest sind Downloads, die im Hintergrund laufen.

## Was Fleech ist

Diktier-App für Windows. Du drückst eine Taste, sprichst, lässt los — der Text
landet in dem Feld, in dem der Cursor gerade steht. Egal ob Word, Browser, Chat
oder Editor.

Der Unterschied zur Windows-Spracherkennung: Eine lokale KI räumt hinterher auf.
„Ähm", Versprecher, doppelte Anläufe fallen weg, Satzzeichen kommen dazu. Je nach
gewähltem Profil wird aus dem Diktat auch eine fertige E-Mail oder eine
Stichpunktliste.

**Alles läuft auf deinem Rechner.** Kein Cloud-Dienst, kein Konto. Deine Stimme
und dein Text verlassen den Rechner nie. Fleech fragt beim Start und danach
täglich bei GitHub nach einer neuen Version — abschaltbar unter
*Einstellungen → Advanced*.

## Was du brauchst

- Windows 10 oder 11
- Ein Mikrofon
- Rund 8 GB freien Speicherplatz (Programm + Sprachmodelle)
- Einmalig Internet für die Einrichtung
- Eine NVIDIA-Grafikkarte ist ein Vorteil, aber keine Bedingung — ohne läuft die
  Erkennung auf dem Prozessor, spürbar langsamer, aber sie läuft.

## Schritt 1 — Installieren

1. Setup-Datei herunterladen:
   **https://github.com/FynnXland/fleech-releases/releases/latest**
   Die Datei heißt `FleechSetup-<Version>.exe`, rund 1 GB.
2. Doppelklick. **Kein Administrator nötig** — Fleech installiert sich in dein
   eigenes Benutzerverzeichnis.
3. Windows meldet eventuell „Der Computer wurde geschützt" (SmartScreen). Das
   kommt bei jedem Programm ohne gekaufte Signatur. Über *Weitere Informationen →
   Trotzdem ausführen* geht es weiter.

## Schritt 2 — Freischalten

Fleech diktiert nur mit einem persönlichen Schlüssel. Du hast ihn zusammen mit
dem Link bekommen — eine lange Zeile, die mit `FLEECH-1.` beginnt.

Beim ersten Aufnahmeversuch fragt Fleech danach. Du kannst ihn auch vorher
eintragen: **Einstellungen → Lizenz → einfügen**.

Der Schlüssel gilt für dich, nicht für ein Gerät — auf einem zweiten Rechner
funktioniert derselbe.

## Schritt 3 — Fleech richtet sich selbst ein

Beim ersten Start prüft Fleech, was fehlt, und holt es nach. Drei Schritte mit
Fortschrittsanzeige, kein Terminal:

| Schritt | Was es ist | Größe |
|---|---|---|
| **Ollama** | führt die KI lokal aus | klein |
| **Sprachmodell** (`gemma3:4b`) | räumt den Text auf | ~3,3 GB |
| **Spracherkennung** (Whisper) | macht aus Ton Text | ~1,6 GB |

Das dauert je nach Leitung 5–20 Minuten und passiert **einmal**. Ollama
installiert Fleech nur auf deinen Klick — fremde Software wird nicht ungefragt
eingerichtet.

## Schritt 4 — Diktieren

Vorgabe ist **F9**: gedrückt halten, sprechen, loslassen. Die Taste kannst du
unter *Einstellungen → Aufnahme* ändern; dort lässt sich auch auf „Umschalten"
stellen, wenn Halten unbequem ist.

Beim Sprechen erscheint eine kleine Pille am Bildschirmrand — sie zeigt den
Pegel, den erkannten Text und hat Knöpfe für Abbrechen, Fertig und Pause. Du
kannst sie an jede Stelle ziehen.

Das erste Diktat nach dem Start dauert ein paar Sekunden länger, weil die Modelle
in den Speicher geladen werden. Danach ist es je nach Länge des Diktats ein bis
wenige Sekunden.

## Was sich lohnt zu wissen

**Profile** bestimmen, was aus dem Gesprochenen wird:

- *Standard* — bereinigter Text, so wie gesprochen
- *E-Mail* — Anrede, Absätze, Grußformel
- *KI-Prompt* — knapp und strukturiert für ein KI-Chatfenster
- *Stichpunkte* — als Liste gegliedert, ohne zu kürzen — soweit das Modell folgt

Umschalten geht über den Punkt links an der Pille oder über einen eigenen Hotkey
(*Einstellungen → Aufnahme → Profil wechseln*): Tippen schaltet weiter, Halten
öffnet eine Auswahlliste am Mauszeiger.

**Auf der Seite „Apps"** legst du fest, welches Profil in welchem Programm
automatisch gilt — und zwischen welchen Profilen der Hotkey dort überhaupt
wechselt. In einem KI-Chat sind das andere als in Word.

**Wörterbuch** (*Einstellungen → Textersetzung*): Namen, Fachbegriffe und Abkürzungen,
die die Erkennung sonst verhaspelt. Der wirksamste Handgriff überhaupt — trag
dort ein, was in deinem Alltag ständig vorkommt.

**Fenster schließen beendet Fleech nicht**, es läuft im Infobereich weiter
(Symbol rechts unten neben der Uhr). Rechtsklick darauf → Beenden.

**Updates** meldet Fleech selbst, wenn eine neue Version da ist.

## Wenn etwas nicht geht

**Nichts wird erkannt** — Mikrofon prüfen unter *Einstellungen → Aufnahme*.
Fleech zeigt dort das gewählte Gerät und einen Pegel; wenn der beim Sprechen
still bleibt, ist das falsche Gerät ausgewählt.

**Text kommt roh, ohne Aufräumen** — dann läuft Ollama nicht. Einmal Fleech neu
starten; die Einrichtungsseite meldet, was fehlt.

**Text landet im falschen Fenster** — der Cursor muss beim Loslassen dort stehen,
wo der Text hin soll. *Einstellungen → Ausgabe → Cursor-Rückkehr* merkt sich das
Zielfeld beim Aufnahmestart und ist die Lösung dafür.

**Es hängt oder stürzt ab** — es gibt ein Protokoll unter
`%APPDATA%\Fleech\fleech.log`. Schick die letzten Zeilen an denjenigen, von dem
du Fleech hast; darin steht meistens direkt die Ursache.
