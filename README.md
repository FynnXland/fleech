<h1 align="center">Fleech</h1>

<p align="center">
  <b>Lokales Diktieren für Windows und Linux: Taste halten, sprechen, loslassen.</b><br>
  Der Text landet bereinigt dort, wo dein Cursor steht. Alles läuft auf deinem Rechner.
</p>

<p align="center">
  <a href="https://github.com/FynnXland/fleech/releases/latest"><b>⬇ Neueste Version herunterladen</b></a>
  &nbsp;·&nbsp;
  <a href="#installation">Installation</a>
  &nbsp;·&nbsp;
  <a href="#selbst-bauen">Selbst bauen</a>
  &nbsp;·&nbsp;
  <a href="docs/">Dokumentation</a>
</p>

<p align="center">
  <img src="docs/bilder/pille.png" alt="Die Fleech-Pille während einer Aufnahme: Abbrechen, Pegel, Fertig, Pause" width="404">
</p>

<p align="center">
  <img src="docs/bilder/hauptfenster.png" alt="Das Fleech-Hauptfenster mit dem Verlauf der letzten Diktate" width="900">
</p>

---

## Was Fleech ist

Eine Diktier-App. Du drückst eine Taste, sprichst, lässt los — und der Text erscheint
im Feld, in dem der Cursor steht: Word, Browser, Mail, Chat, Editor, egal welches
Programm. Fleech greift dafür nicht in Anwendungen hinein, sondern fügt über die
Zwischenablage und ein simuliertes `Strg+V` ein.

Anders als die eingebaute Spracherkennung des Betriebssystems räumt danach eine KI auf:
„Ähm", Versprecher und doppelte Anläufe fallen weg, Satzzeichen kommen dazu. Was du
gesagt hast, bleibt dabei so stehen, wie du es gesagt hast. Fleech glättet, es
formuliert nicht um.

**Alles passiert lokal.** Spracherkennung ([faster-whisper](https://github.com/SYSTRAN/faster-whisper))
und Textbereinigung ([Ollama](https://ollama.com)) laufen auf deinem Rechner. Kein
Cloud-Dienst, kein Konto, keine Aufnahme verlässt das Gerät. Ins Netz geht Fleech nur
für die Einrichtung und die Update-Prüfung (abschaltbar).

## Was Fleech kann

|  |  |
|---|---|
| **Erkennt schon beim Sprechen** | Jeder Abschnitt wird in der nächsten Sprechpause erkannt. Nach dem Loslassen fehlt nur noch der letzte Satz — auch nach einer Minute Diktat ist der bereinigte Text nach ein bis zwei Sekunden da. |
| **Bleibt beim Wortlaut** | Die Bereinigung wird geprüft: Fehlt zu viel von dem, was du gesagt hast, oder taucht etwas auf, das du nie gesagt hast, kommt der Abschnitt unbereinigt. Lieber roh als verfälscht. |
| **Profile** | Je nach Programm wird aus dem Diktat bereinigter Text, eine fertige E-Mail, ein KI-Prompt oder eine Stichpunktliste. |
| **Befehle** | Mitten im Reden das Safe-Word sagen (Standard „Kimono"), dann die Anweisung: *„… **Kimono**, mach den letzten Satz formeller."* |
| **Formeln** | Gesprochene Mathematik wird zu LaTeX — in einem deterministischen Parser, ohne Modell. |
| **Wörterbuch** | Namen und Fachbegriffe, die du einträgst, werden zuverlässig richtig geschrieben. |
| **Verlauf** | Jedes Diktat lässt sich wiederfinden, durchsuchen, neu bereinigen und als Markdown speichern. |
| **Geht nicht verloren** | Bist du schon in einem anderen Fenster, wenn ein Diktat fertig wird, landet es in der Zwischenablage — und die Pille sagt dir das. |
| **Rücksicht beim Spielen** | Läuft ein Spiel, gibt Fleech den Grafikspeicher frei und lädt die KI erst beim nächsten Diktat wieder. |

## Ein Blick hinein

**Die Pille** erscheint beim Diktieren am Bildschirmrand: links das aktive Profil,
in der Mitte Abbrechen, Pegel und Fertig, rechts Pause. Sie nimmt nie den Fokus — sonst
wäre das Ziel-Textfeld weg — und lässt sich an jede Stelle ziehen.

**Insights** zeigen, wie viel und wie schnell du diktierst, in welchen Programmen und
wie viel Fleech für dich korrigiert hat.

<p align="center">
  <img src="docs/bilder/insights.png" alt="Insights: Wörter pro Minute, App-Nutzung, Serie, häufigste Wörter" width="900">
</p>

**Profile** bestimmen, was aus dem Gesprochenen wird. Auf der Seite *Apps* legst du
fest, welches Profil in welchem Programm automatisch gilt.

<p align="center">
  <img src="docs/bilder/profile.png" alt="Profile: Standard, Geschäftlich, Privat, Coding, Mathe, E-Mail, KI-Prompt, Stichpunkte" width="900">
</p>

**Einstellungen** — Hotkeys, Mikrofon, Ausgabe, Wörterbuch. Alles, was du änderst,
gilt sofort.

<p align="center">
  <img src="docs/bilder/einstellungen-aufnahme.png" alt="Einstellungen, Seite Aufnahme: Bedienmodus, Hotkeys, Mikrofon" width="760">
</p>

<sub>Alle Bilder zeigen Beispieldaten.</sub>

---

## Installation

### Was du brauchst

- Windows 10 oder 11 (Linux mit X11: siehe [Selbst bauen](#selbst-bauen))
- Ein Mikrofon
- Rund 8 GB freien Speicherplatz (Programm und Sprachmodelle)
- Einmalig Internet für die Einrichtung
- Eine NVIDIA-Grafikkarte ist ein großer Vorteil, aber keine Bedingung. Ohne läuft die
  Erkennung auf dem Prozessor — spürbar langsamer, aber sie läuft.

### 1 — Installieren

1. Unter [**Releases**](https://github.com/FynnXland/fleech/releases/latest) die Datei
   `FleechSetup-<Version>.exe` herunterladen (rund 1 GB).
2. Doppelklick. **Keine Administratorrechte nötig** — Fleech installiert sich in dein
   Benutzerverzeichnis.
3. Meldet Windows „Der Computer wurde geschützt" (SmartScreen): *Weitere Informationen
   → Trotzdem ausführen*. Das erscheint bei jedem Programm ohne gekaufte Signatur.

### 2 — Fleech richtet sich selbst ein

Beim ersten Start prüft Fleech, was fehlt, und holt es nach — mit Fortschrittsanzeige,
ohne Terminal:

| Baustein | Wofür | Größe |
|---|---|---|
| **Ollama** | führt die KI lokal aus | klein |
| **Sprachmodell** `gemma3:4b` | räumt den Text auf | ~3,3 GB |
| **Spracherkennung** Whisper `large-v3-turbo` | macht aus Ton Text | ~1,6 GB |

Das dauert je nach Leitung 5 bis 20 Minuten und passiert einmal. Ollama wird nur auf
deinen Klick installiert (unter Windows per `winget`; fehlt es, nennt Fleech den Weg von
Hand).

### 3 — Diktieren

Vorgabe ist **F9**: gedrückt halten, sprechen, loslassen. Taste und Bedienart (Halten
oder Umschalten) stellst du unter *Einstellungen → Aufnahme* um.

Das erste Diktat nach dem Start dauert ein paar Sekunden länger, weil die Modelle
geladen werden. Danach ist der Text meist nach ein bis zwei Sekunden da.

## Gut zu wissen

- **Wörterbuch** (*Einstellungen → Textersetzung*): Trag Namen, Fachbegriffe und
  Abkürzungen ein, die in deinem Alltag oft vorkommen. Der wirksamste Handgriff
  überhaupt — die Einträge primen zusätzlich die Spracherkennung.
- **Profil wechseln**: über den Punkt links an der Pille oder einen eigenen Hotkey —
  Tippen schaltet weiter, Halten öffnet eine Auswahl. Das geht auch mitten in der
  Aufnahme.
- **Weitere Hotkeys**: `Strg+Alt+P` macht aus dem laufenden Diktat einen KI-Prompt,
  `Strg+Alt+Leertaste` pausiert, `Strg+Alt+Z` nimmt eine Fehlausgabe zurück.
- **Deutsche Spracherkennung**: Unter *Einstellungen → Advanced → Spracherkennung* gibt
  es eine auf Deutsch nachtrainierte Variante. Wer viel Englisch diktiert, bleibt bei
  „Standard".
- **Fenster schließen beendet Fleech nicht** — es läuft im Infobereich neben der Uhr
  weiter. Rechtsklick auf das Symbol → *Beenden*.
- **Updates** meldet Fleech selbst und installiert sie erst auf Klick. Abschaltbar unter
  *Einstellungen → Advanced*.

## Wenn etwas nicht geht

| Problem | Lösung |
|---|---|
| Es wird nichts erkannt | *Einstellungen → Aufnahme*: Stimmt das Mikrofon? Der Pegel muss sich beim Sprechen bewegen. |
| Text kommt roh, ohne Aufräumen | Ollama läuft nicht. Fleech einmal neu starten — die Einrichtungsseite zeigt, was fehlt. |
| Text landet im falschen Fenster | *Einstellungen → Ausgabe → Cursor-Rückkehr* merkt sich das Zielfeld beim Aufnahmestart. |
| Es hängt oder stürzt ab | Das Protokoll liegt unter `%APPDATA%\Fleech\fleech.log` (Linux: `~/.config/Fleech/fleech.log`). Gern als [Issue](https://github.com/FynnXland/fleech/issues) melden, mit den letzten Zeilen daraus. |

## Wo Daten liegen

Ausschließlich auf dem eigenen Rechner, außerhalb der Anwendung:

| Was | Windows | Linux |
|---|---|---|
| Einstellungen | `%APPDATA%\Fleech\settings.json` | `~/.config/Fleech/settings.json` |
| Verlauf | `%APPDATA%\Fleech\history.db` | `~/.config/Fleech/history.db` |
| Log | `%APPDATA%\Fleech\fleech.log` | `~/.config/Fleech/fleech.log` |

Der Verlauf enthält Diktattexte — wer das nicht möchte, schaltet ihn in den
Einstellungen ab und löscht ihn dort. Audio wird nie gespeichert.

---

## Selbst bauen

Voraussetzung: Python 3.11.

### Windows

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m fleech                        # direkt starten (oder Fleech.pyw)
.venv\Scripts\python packaging\build.py               # → dist\Fleech\Fleech.exe
.venv\Scripts\python packaging\build.py --installer   # → dist\FleechSetup-<version>.exe
```

Für das Setup wird [Inno Setup 6](https://jrsoftware.org/isinfo.php) gebraucht
(`winget install JRSoftware.InnoSetup`). Es installiert per-user ohne UAC, legt einen
Startmenü-Eintrag an und bietet optional Autostart und Desktop-Symbol.

### Linux (X11, getestet auf Kubuntu)

```bash
bash packaging/setup-linux.sh                              # venv unter ~/.venvs/fleech
~/.venvs/fleech/bin/python packaging/build.py --install    # → ~/.local/opt/Fleech
```

Die venv liegt bewusst außerhalb des Projekts, damit es auch auf NTFS liegen darf.
Unter Wayland sind globale Hotkeys nicht möglich; Fleech sagt das, statt stumm zu
versagen.

### Tests

```powershell
.venv\Scripts\python -m pytest -q
```

Rund 1550 Tests, Spracherkennung und Sprachmodell gemockt. Optional ein echter
faster-whisper-Lauf auf einer per TTS erzeugten Datei: `pwsh tests/fixtures/make_fixture.ps1`,
dann `$env:FLEECH_STT_TEST = "1"` und `pytest tests/test_stt_integration.py`.

### Konfiguration

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

### Aufbau

Die Pipeline ist eine Kette: `Audio → STT → Artefakt-Filter → Routing → LLM → Prüfungen
→ Injection` ([fleech/pipeline.py](fleech/pipeline.py)).

| Modul | Aufgabe |
|---|---|
| `fleech/pipeline.py` | Orchestrierung der Kette |
| `fleech/stt/` | faster-whisper (CUDA/CPU), Abschnitte beim Sprechen, Segment-Filter |
| `fleech/routing.py` | Modus-Erkennung, Safe-Word-Fundstelle |
| `fleech/llm/client.py` | Ollama-Client (`/api/chat` mit `num_ctx`) |
| `fleech/textfilter.py` | Qualitäts-Prüfungen: erfundene Ergänzungen, Wortsalat, Sinnumkehr |
| `fleech/commands.py` | Safe-Word-Befehle inkl. Plausibilitäts-Guards |
| `fleech/formula.py` | gesprochene Mathematik → LaTeX (deterministisch) |
| `fleech/dictionary.py` | persönliches Wörterbuch (Priming, Ersetzung, Vorschläge) |
| `fleech/injection.py` | Zwischenablage + `Strg+V`, global serialisiert |
| `fleech/audiofocus.py` | weiches Ducking anderer Apps, Loopback-Erkennung |
| `fleech/provisioning.py` | Kaltstart: Ollama und Modelle besorgen |
| `fleech/history.py` | SQLite-Verlauf und Auswertung |
| `fleech/usersettings.py` | Einstellungen (atomar gespeichert, additive Migration) |
| `fleech/ui/` | Tray, Hauptfenster, Einstellungen, Overlay-Pille, Einführung, Updates |
| `packaging/` | PyInstaller-Spec, Build-, Release- und Stopp-Skript, Inno-Installer, Linux-Setup |

Plattformunterschiede stecken hinter festen Nahtstellen (`platformpaths`, `clipboard`,
`audiofocus`, `ui/x11tools`, `ui/autostart`, `singleinstance`) statt in verstreuten
`sys.platform`-Abfragen. Die ausführliche Architektur steht im
[Gesamtkonzept](docs/fleech-gesamtkonzept.md#14-architektur).

### Veröffentlichen

```powershell
.venv\Scripts\python packaging\release.py
```

Baut EXE und Setup, bildet die SHA-256 und legt ein GitHub-Release mit den Notizen aus
dem [CHANGELOG](CHANGELOG.md) an. Die installierte App findet es von dort selbst; vor
jeder Installation prüft sie die Prüfsumme und verwirft die Datei, wenn sie nicht passt.

```powershell
Get-FileHash .\FleechSetup-<version>.exe -Algorithm SHA256   # von Hand nachrechnen
```

## Lizenz

Fleech ist freie Software unter der [GNU General Public License v3.0](LICENSE).
Du darfst es benutzen, untersuchen, verändern und weitergeben — Veränderungen
und Weitergaben ebenfalls unter der GPL-3.0 und mit Quellcode.

Copyright © 2026 FynnXland
