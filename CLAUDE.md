# CLAUDE.md — Arbeitsanweisung für den Entwicklungsagenten

Diese Datei ist verbindlich. Wenn eine Anweisung hier mit einer Standard-Gewohnheit
kollidiert, gilt diese Datei.

## Was Fleech ist

Lokale deutsche Diktier-App für Windows 11 (Wispr-Flow-artig), Python + PySide6/Qt,
läuft als **Tray-App** (Fenster schließen = in den Tray, nicht beenden). Alles läuft
lokal: Mikrofon → Erkennung → KI-Bereinigung → Text landet im gerade fokussierten Feld
(Zwischenablage + simuliertes Strg+V). Kommunikation mit dem Nutzer **auf Deutsch**.

## Pipeline (der Kern)

`Audio → STT → Modus-Routing → LLM → Injection` (`fleech/pipeline.py`, `process()`):

1. **STT** — faster-whisper `large-v3-turbo` auf GPU (RTX 4070, ~0,2 s warm).
   `initial_prompt` primet Vokabular + Signalwort. Kein Cloud-Fallback mehr.
2. **Routing** (`fleech/routing.py`, `detect_mode`): `cleanup` (Default) | `command`
   (Safe-Word erkannt) | `math` (Hotkey/Latch/gesprochene Delimiter).
3. **LLM** — Cleanup: Ollama `gemma3:4b` (ein Modell für alles). Formeln entstehen
   im deterministischen Parser, ohne Modell.
4. **Injection** (`fleech/injection.py`) — Clipboard + Strg+V, global serialisiert.

**Wichtig zu den Modellen:** Seit v3.5.0 läuft alles über `gemma3:4b` — an 15 echten
Diktaten gemessen 34 % schneller als das frühere `qwen3.5:9b`, halb so groß (3,3 GB)
und dabei sogar wortgetreuer (ergänzt 0,014 statt 0,021 eigene Wörter). Das zweite,
kleine Modell ist entfallen: Es brachte 0,1 s und kostete Treue, während zwei Modelle
dauerhaft 8,5 GB VRAM belegten — der Hauptgrund für die ständigen Entladungen.
Wer auf ein **Thinking-Modell** zurückwechselt (`qwen3.5:9b` & Co.), muss in
`config.yaml` zwingend `reasoning_effort: none` setzen, sonst denkt es 30–50 s pro
Diktat und liefert teils leeren Content (auch `low` ist unbrauchbar); für `gemma3`
bleibt das Feld leer.

**`num_ctx` ist Pflicht, nicht Feinschliff:** Ollama lädt Modelle immer mit 4096 Token
Kontext, egal was das Modell könnte — und der OpenAI-Aufsatz ignoriert jede Option
dagegen (gemessen). Allein `prompts/cleanup.md` belegt ~3000 Token; lange Diktate
brachen dadurch mitten im Satz ab. Deshalb spricht `ChatClient` bei localhost-Endpoints
Ollamas eigene `/api/chat` mit `options.num_ctx` (8192) an; jeder andere Provider läuft
weiter über den OpenAI-Weg. Zusätzlich meldet der Client `last_truncated` — bricht eine
Antwort doch am Fenster ab, fügt die Pipeline den **Rohtext** ein statt eines halben Satzes.

Provider/Modelle/Prompts sind in `config.yaml` + `prompts/` konfigurierbar
(Benutzerpfad `%APPDATA%\Fleech`, sonst App-Ordner).

## Modul-Landkarte (Kurz)

- `fleech/pipeline.py` — Orchestrierung; `pipeline_factory.py` baut sie aus Config+Settings.
- `fleech/commands.py` — Safe-Word-Befehle (JSON-Parsing, Plausibilitäts-/Lösch-Guards).
- `fleech/routing.py` — Modus-Erkennung, `text_before_trigger`, `split_command_continuation`.
- `fleech/textfilter.py` — **Qualitäts-Guards der Pipeline**: erfundene Ergänzungen,
  Wortsalat, fremde Schrift, Sinnumkehr. Kern-Fachlogik, keine Helfer-Sammlung.
- `fleech/dictionary.py` — persönliches Wörterbuch (Priming, Ersetzung, Vorschläge).
- `fleech/textutils.py` — nur noch der Rahmen um den LLM-Call (Transkript einpacken/auspacken).
- `fleech/mathmode.py`, `document.py` — Formeln, Diktat-Puffer.
- `fleech/profiles.py` — App-Profile: Regeln (Prozess + Titel), Farben, Schnellwechsel.
- `fleech/usersettings.py` — `%APPDATA%\Fleech\settings.json` (Dataclasses, additive Migration).
  Importiert `profiles`, **nie umgekehrt**. `save()` läuft unter einem Modul-Lock mit
  eindeutiger Nebendatei; `load()` heilt eine gültige, aber zurückgesetzte Datei aus
  der `.bak` (Erkennung in `fleech/settingsheilung.py`, kennt weder Pfade noch Schreiben).
- `fleech/history.py` — SQLite-Verlauf (`history.db`), Stats für Insights; je Eintrag seit 5.10.4
  auch `reason`/`profile`/`title`/`dropped`. `fleech/gruende.py` — die Grund-Texte dazu.
- `fleech/ui/` — `desktop.py` (Aufbau, Aufnahme-Lebenszyklus, Hotkeys, Verdrahtung),
  `main_window.py` (Fenstergerüst), `settings_window.py` (Panel + Widget-Bauer),
  `overlay_qt.py` (das Pillen-Fenster: Aufbau, Hintergrund, Qt-Ereignisse),
  `state.py` (StateBus-Signale), `theme.py`, `widgets.py`, `dialogs.py`,
  `titlebar.py`, `chevron.py`, `focusrestore.py`, `windowsfocus.py`, `notifications.py`.
- `fleech/ui/pages/` — die vier Seiten des Hauptfensters (home, insights, apps, profiles);
  dazu `verlauffilter` (Suche/Zeitraum/Export der Home-Timeline), `jetztzeile`
  („Wenn du jetzt diktierst …" auf der Apps-Seite, ohne Qt prüfbar), `titelvorschlag`
  (Titel per Knopf übernehmen) und `appsvorschlaege` (Zuordnungs-Karte der Apps-Seite).
- `fleech/varianten.py` — Schreibvarianten desselben Begriffs (Cloud-Code/Claude Code)
  für die Vorschlagskarte; `fleech/profilexport.py` — Profile als JSON sichern/einlesen;
  `fleech/settingsheilung.py`, `fleech/gruende.py` s. o.
- `fleech/ui/settings/` — die neun Einstellungsseiten, je Seite ein `build(panel)`.
- `fleech/ui/desktopapp/` — die Teilgebiete von `DesktopApp` als **Mixins**: `profil`,
  `freihand`, `anstupsen` (Stille-Wache des Nudge-Modus), `keinton` (Wache: Mikrofon
  liefert nichts), `modelle`, `nachbereitung`, `lizenz`, `lebenszyklus`.
- `fleech/ui/overlaypille/` — die Teile der Pille: `konstanten` (Maße/Farben/Zeiten),
  `bausteine` (Waveform, Status-Punkt, Textblase — echte Widgets), und als **Mixins**
  `geometrie` (Position, Ziehen, Presets), `einblendungen` (Transkript, Formeln,
  Fortschritt), `zustand` (Aufnahme, Modus, Profil, Pause).

**Wenn du etwas Neues hinzufügst, leg es an den passenden Ort, nicht dorthin, wo
gerade Platz ist.** Genau daraus sind die Monolithen entstanden — `main_window.py`
hatte 2970 Zeilen, `desktop.py` 1979, `overlay_qt.py` 1409, `settings_window.py` 1379,
`textutils.py` 898. Die Testsuite wacht
inzwischen darüber (`tests/test_ui_struktur.py`, `tests/test_kernstruktur.py`):
Obergrenzen je Datei, Richtung der Abhängigkeiten, und dass ein Teil nie sein Ganzes
importiert. **Reißt eine Grenze, erhöhe nicht die Zahl** — gib dem neuen Thema einen
eigenen Ort.

**Namenskonvention (bewusst gemischt):** Fachbegriffe der Domäne stehen auf Deutsch
(`freihand`, `kontext`, `profil`, `nachbereitung`, `_melde_profilfarbe`), technische
Infrastruktur auf Englisch (`pipeline`, `injection`, `history`, `StateBus`). Grund: Die
App ist deutschsprachig, ihre Fachbegriffe haben keine natürliche englische Entsprechung
(„Freihand" ist nicht „freehand"). Halte dich daran, statt bei jeder neuen Datei neu zu
entscheiden.

## Lieferpflichten — wie DU (Claude) abzuliefern hast

**Diese Kette ist bei JEDER Code-Änderung Pflicht. „Fertig" gibt es erst danach.**
Die App ist plattformfähig (Windows 11 + Linux/Kubuntu, X11); welche Kette gilt,
entscheidet die Plattform, auf der du gerade arbeitest:

**Windows** (venv im Projekt: `.venv`):

1. **Volle Testsuite grün**: `.venv/Scripts/python -m pytest -q` (aktuell 390+ Tests).
   Neue Logik = neue/angepasste Tests. Fehlschläge nennst du mit Output, nicht verschweigen.
2. **EXE bauen**: `.venv/Scripts/python packaging/build.py`.
3. **Syncen + Neustart** (PowerShell): Fleech **beenden** (robocopy hängt sonst am
   laufenden Prozess!), `robocopy dist\Fleech %LOCALAPPDATA%\Programs\Fleech /MIR /R:2 /W:2`,
   dann **Verify-Lauf** `robocopy … /MIR /L /R:0 /W:0` — **muss Exit 0** liefern (0 Unterschiede),
   dann Fleech neu starten. (`copy exit: 1` = Dateien kopiert = ok; `verify exit: 0` = synchron.)

   **Beenden immer über `packaging/stop_fleech.py`, nicht per `Stop-Process -Force`.**
   Das Skript bittet die laufende Instanz über den IPC-Kanal, sich selbst zu beenden
   (Exit 0 = weg; Exit 1 = hängt, dann ist ein hartes Kill die Notbremse). Grund: Ein
   hartes Kill kann einen laufenden `settings.save()` treffen. Das hat real mehrfach
   die `settings.json` geleert — beim nächsten Start standen Hotkeys, Profile und der
   **Lizenzschlüssel** auf Vorgabe. Seit v4.9.1 schreibt `UserSettings.save()` atomar
   (Temp + `fsync` + `os.replace`) und legt eine `settings.json.bak` an, aus der
   `load()` bei einer kaputten Datei heilt — der ordentliche Weg bleibt trotzdem Pflicht.

### Wann wird VERÖFFENTLICHT? (nicht bei jeder Änderung)

Die drei Schritte oben gelten immer. Der **Release** (Installer bauen + hochladen)
dauert zusätzlich rund zehn Minuten — oft länger als die Änderung selbst. Deshalb:

- **Patch-Version** (`4.3.1`, `4.3.2`, …) = Kleinigkeit → **kein Release**. Nur Schritte
  1–3, damit die laufende Installation aktuell ist. `packaging/release.py` weigert
  sich bei Patch-Versionen von sich aus (`--force` überstimmt).
- **Minor/Major** (`4.4.0`, `5.0.0`) = genug zusammengekommen → `packaging/release.py`.
  Dann bekommt auch die Weitergabe die neuen Sachen auf einmal.

Faustregel für die Nummer: Fehlerbehebung oder Feinschliff → dritte Stelle. Neue
Funktion, geänderte Bedienung oder etwas, das der Empfänger merken soll → zweite.

**`CHANGELOG.md` gehört zu jeder Versionsänderung** — dieselbe Zeile Arbeit wie
`version.py`, nicht ein Extra-Schritt am Ende. Geschrieben für den, der Fleech
*benutzt*: was sich für ihn ändert, nicht welche Funktion umgebaut wurde (das
steht in der Commit-Nachricht). Patch-Versionen bekommen den Zusatz „nicht
einzeln veröffentlicht". `packaging/release.py` zieht den Abschnitt der aktuellen
Version automatisch in die GitHub-Release-Notizen — fehlt er, geht das Release
ohne Erklärung raus. `tests/test_changelog.py` schlägt Alarm, wenn die Version in
`version.py` keinen Eintrag hat.

**Linux** (Projekt liegt auf NTFS → venv liegt AUSSERHALB: `~/.venvs/fleech`;
Neuaufsetzen: `bash packaging/setup-linux.sh` — installiert u. a. pynput bewusst
mit `--no-deps`, weil evdev ohne python3-dev nicht baut und X11 es nicht braucht):

1. **Volle Testsuite grün**: `~/.venvs/fleech/bin/python -m pytest -q`.
2. **Binary bauen**: `~/.venvs/fleech/bin/python packaging/build.py` → `dist/linux/Fleech/Fleech`.
3. **Installieren/Syncen**: Fleech beenden, dann
   `~/.venvs/fleech/bin/python packaging/build.py --install`
   (kopiert nach `~/.local/opt/Fleech`, legt `fleech.desktop` + Icon an), neu starten.

**Beide Plattformen danach**: kurze Zusammenfassung auf Deutsch, dann **auf das OK des
Nutzers warten** — er testet mit echtem Mikrofon/Screen. Nicht den nächsten Block ohne
Freigabe starten. Plattformspezifischen Code immer hinter den bestehenden Nahtstellen
halten (`platformpaths`, `clipboard`, `audiofocus.default_playback_sessions`,
`ui/x11tools`, `ui/autostart`, `singleinstance`) — kein verstreutes `sys.platform`-Geflecht.

**Weitere feste Regeln:**

- **LLM-/Prompt-Änderungen live gegen Ollama prüfen** (kurzes Skript, echter `ChatClient`),
  nicht nur Unit-Tests — Unit-Tests mocken das LLM.
- **Bugs aus dem Log diagnostizieren, nicht raten**: `%APPDATA%\Fleech\fleech.log`
  (Windows) bzw. `~/.config/Fleech/fleech.log` (Linux). Immer erst den echten Verlauf
  lesen, bevor du eine Ursache behauptest.
- **UI-Änderungen offscreen rendern und ansehen** (siehe Fallen), nicht blind bauen.
- **Ehrlich berichten**: was getestet/übersprungen wurde, was verifiziert ist. Kein Hedging
  bei Verifiziertem, keine „erledigt"-Behauptung bei fehlgeschlagenen Schritten.
- **Version**: `fleech/version.py` (`APP_VERSION`). Bei bewusst neuen Releases hochziehen.

## Qt-/Windows-Fallen (real aufgetreten — beachten!)

- **Referenzzyklus-Crash**: Ein Lambda, das `self` (Qt-Parent) fängt und als Attribut in
  einem Kind-Widget liegt → Python-Zyklus → Widgets sterben per GC in undefinierter
  Reihenfolge → sporadische, wandernde „access violation" (Crash-Ort ≠ Ursache). Fix:
  nur das reine Dataclass fangen (`_ref = settings; lambda: getattr(_ref, …)`).
- **Edit-Falle**: Eine Methode mitten in `__init__` einfügen schiebt Konstruktor-Code in
  den Methodenrumpf (gleiche Einrückung) → `AttributeError` → Access Violation. Methoden
  ans Klassenende hängen oder den ganzen Konstruktor als `old_string` nehmen.
- **Offscreen-Rendering**: `offscreen`-Plattform hat keine Font-Engine → über die echte
  Plattform rendern und `widget.grab()` **ohne** `show()` nutzen. Für Sichtbarkeits-Checks
  `isHidden()` statt `isVisible()` (Letzteres ist ohne gezeigtes Fenster immer False).
- **QSS-Kaskade**: Container per `objectName` scopen (`QFrame#card{…}`) — ein unscoped
  `QFrame{…}` kaskadiert auf alle Kind-QLabels und malt Pillen dahinter.
- **HiDPI**: Pixmaps in Gerätepixeln rendern (`size*dpr`) + `setDevicePixelRatio(dpr)`,
  sonst blockig auf skalierten Displays.
- **Tooltips im inaktiven Fenster** (Overlay): `WA_AlwaysShowToolTips` setzen, sonst
  unterdrückt Qt sie. Eigene Tooltip-Positionierung UNTER dem Cursor (nicht darüber, sonst
  schließt er sofort).
- **Robocopy hängt**, wenn `Fleech.exe` läuft → immer erst beenden.
- **Titelleiste/Chevrons**: dunkle Titelleiste via DWM (`fleech/ui/titlebar.py`);
  Combo/Spinbox-Pfeile via generierte Chevron-Icons (`fleech/ui/chevron.py`,
  `apply_chevrons()` ersetzt `__CHEV_*__`-Platzhalter im QSS) statt CSS-Border-Dreiecken.

## Kontext / Grenzen

- StateBus-Signale (`fleech/ui/state.py`) übertragen Worker-Thread → UI thread-sicher.
- Der Nutzer erledigt echte Mikrofon-/Hotkey-Tests selbst; Fixture-Tests nutzen TTS-WAVs.
- Der lange Sitzungs-Verlauf (Entscheidungen, gelöste Bugs) steht in der Auto-Memory
  (`memory/fleech-projekt-stand.md`) — dort nachsehen, statt Vergangenes neu herzuleiten.
