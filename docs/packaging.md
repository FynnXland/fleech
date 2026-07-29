# Packaging, Installer, Autostart & Updates

Stand: 2026-07-04 · App-Version 1.0.0

## Überblick

Fleech wird als **onedir**-PyInstaller-Build (Ordner mit `Fleech.exe` + `_internal/`)
verpackt und per **Inno Setup** zu `FleechSetup-<version>.exe` gebündelt. Kein
Terminal, kein Projektordner-Zwang, in der Windows-Suche als „Fleech" auffindbar.

```
packaging/
  entry.py          # PyInstaller-Einstiegspunkt → fleech.__main__.main()
  fleech.spec       # PyInstaller-Konfiguration (Assets/Prompts/config gebundelt)
  version_info.txt  # EXE-Metadaten (auto-generiert vom Build-Skript)
  build.py          # reproduzierbarer Build (Icons → Stamp → EXE → optional Installer)
  fleech.iss        # Inno-Setup-Skript (Startmenü, Autostart-Task, Uninstall)
assets/
  logo.svg          # Brand-Quelle (Vektor)
  make_icons.py     # leitet PNG + fleech.ico ab (Pillow)
  fleech.ico        # Multi-Res-Icon (16–256) für EXE, Fenster, Tray, Installer
```

## Build-Prozess (reproduzierbar)

```powershell
# 1. EXE bauen (nutzt die zuletzt gewaehlte GPU/CPU-Praeferenz, Default CPU)
.venv\Scripts\python packaging\build.py

# 2. GPU-Variante (bundelt nvidia-cuBLAS/cuDNN, ~1 GB groesser) + Installer.
#    --gpu PERSISTIERT die Wahl in packaging/build.local.json — jeder spaetere
#    Build (auch ohne Flag) bleibt GPU, bis explizit --cpu gesetzt wird.
.venv\Scripts\python packaging\build.py --gpu --installer

# 3. Zurueck auf CPU-Build wechseln (persistiert ebenso)
.venv\Scripts\python packaging\build.py --cpu --installer
```

Das Build-Skript:
1. löst die GPU/CPU-Praeferenz auf (`--gpu`/`--cpu` > `FLEECH_GPU`-Env > zuletzt
   gespeicherter Wert in `packaging/build.local.json`, gitignored),
2. rendert die Icons (`assets/make_icons.py`),
3. schreibt `build.txt` (Datum + Git-Commit) — wird ins Paket gebündelt und in der
   Versionsanzeige gezeigt,
4. generiert `version_info.txt` (Windows-EXE-Metadaten aus `APP_VERSION`),
5. ruft PyInstaller mit `packaging/fleech.spec` auf,
6. baut optional den Installer via `ISCC.exe`.

**Laufzeit-Gegenstück:** Ob das *installierte* Programm die gebündelte GPU tatsächlich
nutzt, steuert die App selbst über Einstellungen → Advanced → „GPU-Beschleunigung
bevorzugen" (Default an). Das ist eine reine Laufzeit-Praeferenz (`stt.device`:
`auto` vs. `cpu`, persistiert in `settings.json`, übersteht Neustart/Autostart ohne
jede Env-Var) — unabhängig von der Build-Wahl oben, die nur bestimmt, ob die
nötigen DLLs überhaupt im Paket stecken.

**Artefakte:** `dist/Fleech/Fleech.exe` (onedir), `dist/FleechSetup-1.0.0.exe` (Installer).

## Was gebündelt wird

- **Code:** PySide6 (Qt), faster-whisper/ctranslate2/av, sounddevice, pynput, pycaw,
  comtypes, openai, numpy, PyYAML — via `collect_all` bzw. PyInstaller-Hooks.
- **Daten:** `prompts/`, `assets/`, `config.yaml`, `build.txt` (relative Pfade lösen
  sich über `fleech/resources.py` auf: `sys._MEIPASS` im Paket, Projektordner im Dev).
- **Ausgeschlossen:** tkinter (Desktop nutzt Qt-Overlay), pytest, matplotlib, ungenutzte
  Qt-Module (WebEngine, Charts, 3D) — hält das Paket schlank.

## Installationslayout

| Ort | Inhalt |
|---|---|
| `%ProgramFiles%\Fleech\` (bzw. `%LocalAppData%\Programs\Fleech` ohne Adminrechte) | `Fleech.exe`, `_internal\`, `assets\`, `prompts\`, `config.yaml` |
| Startmenü `Fleech` | Verknüpfung mit korrektem Icon, startet ohne Konsole |
| Desktop (optional) | Verknüpfung (Task, standardmäßig aus) |
| `%APPDATA%\Fleech\settings.json` | Nutzer-Einstellungen (bleiben bei Deinstallation) |
| `%APPDATA%\Fleech\config.yaml` (optional) | technische Overrides (Provider/Modelle) |
| `%APPDATA%\Fleech\.env` (optional) | API-Keys (z. B. `FLEECH_MATH_API_KEY`) |
| `%APPDATA%\Fleech\fleech.log` | Log (bei Deinstallation entfernt) |

Uninstall über „Apps & Features" / Startmenü. Der Uninstaller entfernt App-Dateien,
Startmenü-/Desktop-Verknüpfungen, den Autostart-Registry-Eintrag und das Log;
Nutzer-Einstellungen bleiben absichtlich erhalten (Wiederinstallation kehrt in den
gewohnten Zustand zurück).

## Autostart

- **Installiert:** HKCU-Run-Eintrag `Fleech` → `"…\Fleech.exe" --gui` (kein Python
  sichtbar). Umschaltbar per Installer-Task ODER jederzeit im Settings-UI.
- **Selbstheilung:** Beim Start prüft die App, ob der gespeicherte Autostart-Pfad noch
  auf die aktuelle EXE zeigt. Nach Verschieben/Neuinstallation wird ein veralteter Pfad
  automatisch korrigiert (`refresh_autostart_if_stale`).
- **Deinstallation:** Der Inno-Uninstaller löscht den Run-Eintrag zusätzlich per
  `reg delete` — auch wenn er zur Laufzeit im Settings-UI gesetzt wurde.
- **Dev-Modus:** `pythonw -m fleech --gui --cwd <projekt>` (nur relevant ohne Installation).

## Versionsstruktur & Updates

| Ebene | Quelle |
|---|---|
| App-Version (SemVer) | `fleech/version.py` → `APP_VERSION` (1.0.0) |
| Build-Version | `build.txt` (Datum + Commit), vom Build-Skript erzeugt |
| Installer-Version | vom Build-Skript an Inno übergeben (`/DAppVersion`) |
| EXE-Metadaten | `version_info.txt` (auto-generiert) — sichtbar in den Dateieigenschaften |

Angezeigt in **Einstellungen → Advanced → Version**: `Fleech 1.0.0 (Build …)`.

**Update-Basis (bewusst noch kein Auto-Updater):** Die Struktur steht — ein Button
„Nach Updates suchen" fragt optional einen JSON-Feed ab
(`{"version": "1.1.0", "url": "…/FleechSetup.exe"}`), konfigurierbar unter
Advanced → Update-Feed. Ohne Feed: Status „manuelle Updates". Verteilung erfolgt
aktuell durch ein neues Setup (neue `FleechSetup-<version>.exe` bauen und ausführen;
installiert über die alte Version). Ein echter In-App-Downloader ist als **Nicht-Ziel
für jetzt** dokumentiert; die Voraussetzungen (Versionsvergleich `is_newer`,
Feed-Abfrage, Settings-Feld) sind bereits vorhanden.

## Pipeline-Selbsttest (installierte EXE, ohne Mikrofon/GUI-Automatisierung)

`Fleech.exe --pipeline-selftest <fixtures-ordner>` fährt Cleanup, Redax-Befehl und
Formel-Modus mit echten Audio-Fixtures gegen die echten Provider — mit exakt der
Config/den Prompts/der `.env`-Auflösung der **installierten** App (nicht der
Dev-venv). Erwartet im Ordner (jede Datei optional):
`diktat_de.wav`, `command_redax.wav`, `math_quadratisch.wav`
(liegen im Repo unter `tests/fixtures/`, erzeugbar über die `make_*_fixture(s).ps1`-
Skripte dort). Da die EXE `console=False` ist, dockt der Prozess automatisch an eine
bestehende PowerShell-Konsole an, wenn von dort gestartet — sonst bleibt die Ausgabe
unsichtbar (Doppelklick zeigt nichts).

## Bekannter Stolperstein: AttachConsole darf gültiges stdout nie überschreiben

`_attach_console_if_available()` (fleech/__main__.py) darf `sys.stdout`/`sys.stderr`
**nur** ersetzen, wenn sie `None` sind (echtes GUI-Subsystem ohne Umleitung). Ein
früherer Fehler hat sie unconditional durch `CONOUT$` ersetzt, sobald
`AttachConsole` „erfolgreich" an eine beliebige Vorgänger-Konsole andockte — das hat
bereits korrekt umgeleitetes stdout (`Fleech.exe --pipeline-selftest ... > out.txt`)
klammheimlich in ein nicht erfasstes Konsolen-Handle umgeleitet. Getestet in
`tests/test_main_stdio.py`.

## Bekannte Packaging-Grenzen

1. **GPU-Build ist groß** (~1 GB durch cuBLAS/cuDNN). Der Standard-Build ist CPU-fähig;
   Whisper fällt zur Laufzeit sauber auf CPU/int8 zurück, wenn keine CUDA-DLLs vorhanden
   sind. GPU nur bauen, wenn nötig (`FLEECH_GPU=1`).
2. **Whisper-Modelle sind nicht gebündelt** — sie werden beim ersten Lauf in den
   HuggingFace-Cache geladen (`~/.cache/huggingface`). Erststart braucht Internet.
3. **Kein Code-Signing.** Ohne Zertifikat zeigt Windows SmartScreen beim ersten Start
   eine Warnung („Weitere Informationen" → „Trotzdem ausführen"). Für eine breite
   Verteilung wäre ein Signaturzertifikat der nächste Schritt.
4. **onedir statt onefile** — bewusst: schnellerer Start und einfacheres Bündeln der
   nativen Bibliotheken. Der Installer verbirgt den Ordner ohnehin vor dem Nutzer.
5. **Erststart-Kaltlauf:** Modell-Download + Qt-/Whisper-Init dauern beim allerersten
   Start spürbar; danach ist das Modell warm.
6. **GPU-Build-Kompression ist langsam:** Das Bündeln/Komprimieren der ~2 GB
   cuBLAS/cuDNN-DLLs durch Inno Setup (LZMA2, solid) dauerte im Test 40–90 Minuten,
   vermutlich verlangsamt durch Echtzeit-Antivirus-Scans frisch geschriebener,
   unbekannter großer Binärdateien. Für schnellere Iteration: Projekt-`dist`/`build`-
   Ordner temporär von der AV-Echtzeitprüfung ausnehmen, oder für Code-only-Änderungen
   nur `packaging/build.py` **ohne** `--installer` laufen lassen (deutlich schneller)
   und die Dateien manuell in die installierte App synchronisieren (z. B. per
   `robocopy dist\Fleech "%LocalAppData%\Programs\Fleech" /MIR`).
