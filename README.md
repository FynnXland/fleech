# Fleech — lokale Diktat-App für Windows und Linux

**Hotkey halten → sprechen → loslassen → bereinigter Text landet im fokussierten
Textfeld.** Kein Cloud-Dienst, kein Konto, kein Netzwerkverkehr im Betrieb:
Spracherkennung (faster-whisper) und Textbereinigung (Ollama) laufen auf dem eigenen
Rechner. Fleech lebt im System-Tray; Fenster schließen minimiert dorthin, beendet wird
über das Tray-Menü.

Fleech schreibt in **jedes** Textfeld, weil es nicht in Anwendungen hineingreift,
sondern über die Zwischenablage und ein simuliertes `Strg+V` einfügt.

> Ausführliche Gesamtdarstellung — Konzept, alle Funktionen, alle Einstellungen, die
> Oberfläche und die technische Umsetzung:
> [docs/fleech-gesamtkonzept.md](docs/fleech-gesamtkonzept.md)

## Was daran anders ist

**Deine Worte bleiben deine Worte.** Das Sprachmodell darf Füllwörter („äh"),
Versprecher und Selbstkorrekturen entfernen sowie Satzzeichen setzen — aber nicht
umformulieren. Nach jeder Bereinigung laufen sieben Prüfungen, die das Ergebnis
verwerfen, wenn das Modell zu frei wird:

| Prüfung | Greift, wenn … |
|---|---|
| Wortgetreue | zu wenig Deckung mit dem Gesprochenen bleibt |
| Inflation | das Modell eigene Wörter ergänzt hat |
| Bedeutung | Verneinungen oder Zahlen fehlen |
| Abschneiden | die Antwort am Kontextfenster endete |
| Schwanz | ein Satz ohne Grundlage angehängt wurde |
| Erdung | eine Ersetzung nicht zum Zieltext passt |
| LaTeX | eine Formel unplausibel ist |

Greift eine Prüfung, fügt Fleech den **Rohtext** ein und markiert das sichtbar. Lieber
unbereinigt als verfälscht.

Dazu drei Filter **vor** dem Modell, gegen die bekannteste Whisper-Schwäche: in Stille
erfundene Sätze, endlos wiederholte Wortgruppen und plötzlich fremdsprachige Schnipsel.

## Installation

Beim ersten Start führt eine Einführung durch die Einrichtung und holt selbst, was
fehlt: **Ollama** (unter Windows per `winget`, auf Klick), das **Sprachmodell**
`gemma3:4b` (~3 GB) und das **Erkennungsmodell** `large-v3-turbo` (~1,6 GB) — mit
sichtbarem Fortschritt, ohne Terminal. Fehlt `winget`, nennt Fleech den Weg von Hand.

### Windows

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python packaging\build.py               # → dist\Fleech\Fleech.exe
.venv\Scripts\python packaging\build.py --installer   # → dist\FleechSetup-<version>.exe
```

Das Setup (Inno Setup 6 nötig) installiert per-user ohne UAC, legt einen
Startmenü-Eintrag an und bietet optional Autostart und Desktop-Icon. Ohne Paketierung
starten: Doppelklick auf `Fleech.pyw` oder `.venv\Scripts\python -m fleech`.

### Linux (X11, getestet auf Kubuntu)

Das Projekt darf auf NTFS liegen, die venv nicht — `bash packaging/setup-linux.sh` legt
sie unter `~/.venvs/fleech` an. Dann:

```bash
~/.venvs/fleech/bin/python packaging/build.py --install   # → ~/.local/opt/Fleech
```

Unter Wayland sind globale Hotkeys nicht möglich; Fleech sagt das ehrlich, statt stumm
zu versagen.

## Bedienung

**F9 gedrückt halten, sprechen, loslassen** — oder auf Umschalten stellen (drücken =
Start, nochmal = Ende). Während der Aufnahme erscheint eine kleine Pille am
Bildschirmrand: **✕** verwirft, **✓** beendet und fügt ein, in der Mitte läuft der
Live-Pegel. Sie nimmt nie den Fokus — sonst wäre das Ziel-Textfeld weg.

Vier Modi:

- **Diktat** — der Normalfall.
- **Befehle** — mitten im Reden das Safe-Word sagen (Standard „Kimono", phonetisch
  getestet), dann die Anweisung: *„Der Umsatz stieg um 20 Prozent. **Kimono**, mach den
  letzten Satz formeller."* Das wirkt nur auf selbst diktierten Text derselben Sitzung:
  Fleech kann fremde Textfelder nicht lesen, es führt Buch über das eigene Einfügen und
  ersetzt per Backspaces. Ein Fensterwechsel verwirft den Kontext bewusst.
- **Formeln** — `Strg+Alt+M` oder „Formel … Formel Ende": gesprochene Mathematik wird zu
  LaTeX, in einem deterministischen Parser ohne Modell. Mehrdeutiges wird als unsicher
  markiert und vor dem Einfügen gezeigt.
- **KI-Prompting** — `Strg+Alt+P`: aus dem Diktat wird ein strukturierter Prompt.

Außerdem: **Textbausteine** („Baustein Signatur"), ein **Wörterbuch** für Fachbegriffe
(primt zusätzlich die Erkennung), **Ersetzungsregeln**, **Profile** je Anwendung
(Eingriffsgrad, Safe-Word an/aus, automatisch absenden), **Rückgängig** nach einer
Fehlausgabe (`Strg+Alt+Z`) und ein **Verlauf** mit Auswertung (Wörter, WPM, Serie,
häufigste Wörter) — alles lokal in SQLite.

## Wo Daten liegen

Ausschließlich auf dem eigenen Rechner, außerhalb der Anwendung:

| Was | Windows | Linux |
|---|---|---|
| Einstellungen | `%APPDATA%\Fleech\settings.json` | `~/.config/Fleech/settings.json` |
| Verlauf | `%APPDATA%\Fleech\history.db` | `~/.config/Fleech/history.db` |
| Log | `%APPDATA%\Fleech\fleech.log` | `~/.config/Fleech/fleech.log` |

Der Verlauf enthält Diktattexte — wer das nicht möchte, schaltet ihn in den
Einstellungen ab und löscht ihn dort. Audio wird nie gespeichert.

## Konfiguration

Nutzer-Einstellungen gehören ins Einstellungsfenster. Alles Technische (Modelle,
Endpunkte, Schwellen) steht kommentiert in [config.yaml](config.yaml), mit
ENV-Overrides (`FLEECH_HOTKEY`, `FLEECH_STT_MODEL`, `FLEECH_LLM_MODEL`, …). Eine eigene
Kopie darf im Benutzerordner (`%APPDATA%\Fleech`) liegen und sticht die im App-Ordner.
Die System-Prompts sind Dateien in [prompts/](prompts/) und ohne Code-Änderung
editierbar.

**Zu den Modellen:** `gemma3:4b` ist Standard, weil es an 15 echten Diktaten gemessen
34 % schneller war als das zuvor genutzte 9B-Modell, halb so groß — und dabei
wortgetreuer. Wer auf ein Thinking-Modell wechselt, muss `reasoning_effort: none`
setzen, sonst denkt es 30–50 s pro Diktat. Ollama lädt Modelle immer mit 4096 Token
Kontext; Fleech spricht deshalb bei lokalen Endpunkten Ollamas eigene `/api/chat` mit
`num_ctx` an — sonst brechen lange Diktate mitten im Satz ab.

## Tests

```powershell
.venv\Scripts\python -m pytest -q
```

Knapp 600 Tests, STT und LLM gemockt. Optional ein echter faster-whisper-Lauf auf einer
per TTS erzeugten Datei: `pwsh tests/fixtures/make_fixture.ps1`, dann
`$env:FLEECH_STT_TEST = "1"` und `pytest tests/test_stt_integration.py`.

## Aufbau

Die Pipeline ist eine Kette: `Audio → STT → Artefakt-Filter → Routing → LLM → Prüfungen
→ Injection` ([fleech/pipeline.py](fleech/pipeline.py)).

| Modul | Aufgabe |
|---|---|
| `fleech/pipeline.py` | Orchestrierung der Kette |
| `fleech/stt/` | faster-whisper (CUDA/CPU) inkl. Segment-Filter |
| `fleech/routing.py` | Modus-Erkennung, Safe-Word-Fundstelle |
| `fleech/llm/client.py` | Ollama-Client (`/api/chat` mit `num_ctx`) |
| `fleech/textutils.py` | Wortgetreue, Bedeutung, Artefakt-Filter, Wörterbuch |
| `fleech/commands.py` | Safe-Word-Befehle inkl. Plausibilitäts-Guards |
| `fleech/formula.py` | gesprochene Mathematik → LaTeX (deterministisch) |
| `fleech/document.py` | Buchführung über eigenes Diktat (Sitzungen je Fenster) |
| `fleech/injection.py` | Zwischenablage + `Strg+V`, global serialisiert |
| `fleech/audiofocus.py` | weiches Ducking anderer Apps, Loopback-Erkennung |
| `fleech/provisioning.py` | Kaltstart: Ollama und Modelle besorgen |
| `fleech/history.py` | SQLite-Verlauf und Auswertung |
| `fleech/usersettings.py` | Einstellungen (additive Migration) |
| `fleech/ui/` | Tray, Hauptfenster, Einstellungen, Overlay-Pille, Einführung |
| `packaging/` | PyInstaller-Spec, Build-Skript, Inno-Installer, Linux-Setup |

Plattformunterschiede stecken hinter festen Nahtstellen (`platformpaths`, `clipboard`,
`audiofocus`, `ui/x11tools`, `ui/autostart`, `singleinstance`) statt in verstreuten
`sys.platform`-Abfragen.

## Weitergabe: Lizenzschlüssel und Updates

Zwei getrennte Dinge, die zusammen das Ziel erfüllen — *weitergeben können, ohne dass
die Datei überall läuft, und trotzdem automatische Updates*:

### Wer darf Fleech benutzen? — signierter Lizenzschlüssel

Fleech nimmt nur mit gültigem Schlüssel auf. Der Schlüssel ist eine **Ed25519-Signatur**,
keine geheime Zeichenkette: Die App kennt ausschließlich den *öffentlichen* Schlüssel,
mit dem sich Lizenzen **prüfen**, aber niemals **erzeugen** lassen. Wer die EXE zerlegt,
findet dort also nichts Verwertbares. Geprüft wird ohne Internet.

```powershell
python packaging\issue_key.py --init            # einmalig: Schlüsselpaar erzeugen
python packaging\issue_key.py "Max Mustermann"  # Schlüssel für eine Person
python packaging\issue_key.py "Max" --days 365  # befristet
```

Der **private** Schlüssel liegt außerhalb des Projekts (`%APPDATA%\Fleech\signing\`)
und wird nie ausgeliefert — diese eine Datei ist das ganze Geheimnis. Der Empfänger
fügt seinen Schlüssel unter Einstellungen → Allgemein → **Lizenz** ein.

*Grenze, ehrlich gesagt:* Das hält niemanden auf, der die EXE zerlegt und die Prüfung
herauspatcht — das kann keine lokale Prüfung, egal mit welchem Verfahren. Es verhindert
genau das, worum es geht: dass eine weitergereichte Datei bei irgendwem einfach läuft.

### Wie kommen Updates an? — zwei Repositories

| Repository | Inhalt | Sichtbarkeit |
|---|---|---|
| `FynnXland/fleech` | Quellcode | **privat** |
| `FynnXland/fleech-releases` | nur die Setup-Dateien | öffentlich |

Fleech fragt beim Releases-Repo nach — deshalb braucht **keine** Installation einen
GitHub-Token, und der Quellcode bleibt trotzdem privat. Sichtbar ist dort nur die
Installationsdatei, also genau das, was der Empfänger ohnehin bekommt; benutzen kann
er sie ohne Lizenzschlüssel nicht.

Geprüft wird beim Start und danach täglich, geladen im Hintergrund, **installiert nur
auf Klick** (dabei startet die App neu). Vor jeder Installation wird die SHA-256 aus
den Release-Notizen geprüft; stimmt sie nicht, wird die Datei gelöscht statt ausgeführt.
Geladen wird ausschließlich über HTTPS von einem GitHub-Host — auch nach Weiterleitungen.

Veröffentlichen:

```powershell
.venv\Scripts\python packaging\release.py       # baut, signiert die Prüfsumme, lädt hoch
```

Für einen privaten Feed gibt es weiterhin das Token-Feld unter Einstellungen →
Erweitert; im Normalbetrieb bleibt es leer.

## Lizenz

Noch nicht festgelegt — bis dahin alle Rechte vorbehalten.
