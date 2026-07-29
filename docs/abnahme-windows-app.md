# Abnahmeprotokoll — Windows-App (Recorder, Branding, Packaging, Installer, Autostart, Updates)

Stand: 2026-07-04 · App-Version 1.0.0

## Automatisierte Tests (grün)

| Bereich | Tests | Status |
|---|---|---|
| Hotkey-Serialisierung/Normalisierung/Migration | `test_hotkey.py` | ✅ |
| Hotkey-Manager: Einzelkey, Combo, Debounce, Modifier-Release, Binding-Wechsel | `test_hotkey.py` | ✅ |
| Recorder-Dialog: Einzelkey, Kombination, Native-VK-Buchstabe, Abbruch, Löschen, Auto-Repeat | `test_ui_smoke.py` | ✅ |
| Kollisionswarnung (Doppelbelegung + Windows-reserviert) | `test_ui_smoke.py` | ✅ |
| HotkeyField emittiert & zeigt Anzeige-String | `test_ui_smoke.py` | ✅ |
| Autostart: Dev-/Frozen-Command, Enable/Disable, Stale-Path-Reparatur | `test_autostart.py` | ✅ |
| Update-Basis: Versionsvergleich, kein Feed, kaputter Feed | `test_updates.py` | ✅ |
| Persistenz aller Settings inkl. neuer Felder | `test_usersettings.py` | ✅ |

Gesamt: **180 Tests grün, 1 übersprungen.** Zusätzlich verifiziert (Live auf dem
Zielsystem): EXE-Build (17,8 MB EXE / 354 MB onedir, korrekte Metadaten + Icon),
Start ohne Konsole, Installer-Build (97 MB), stille Installation → Startmenü/Suche →
Start der installierten EXE → Deinstallation mit erhaltenen Nutzer-Einstellungen.

## Manuelle Abnahme (am Bildschirm — für dich)

### A — Hotkey-Recorder
1. Einstellungen → Aufnahme → bei „Diktat-Hotkey" auf **Aufnehmen** klicken.
2. **Einzelkey:** F8 drücken → Feld zeigt „F8", Warnung bei Kollision mit Mathe-Hotkey.
3. **Kombination:** Aufnehmen → Ctrl+Shift halten, dann Leertaste → „Ctrl + Shift + Space".
4. **Abbruch:** Aufnehmen → Esc → Feld bleibt unverändert.
5. **Löschen:** Aufnehmen → Entf → Feld zeigt „— keine —" (Hotkey deaktiviert).
6. **Persistenz:** App neu starten (Tray → Neu laden) → gesetzter Hotkey ist noch da.
7. **Funktion:** neuen Hotkey drücken → Aufnahme startet (Tray wird rot).

### B — Branding
- Icon erscheint in: EXE (Explorer-Dateisymbol), Fenstertitel/Taskleiste, Tray
  (Waveform in Statusfarbe), Startmenü-Eintrag, Installer-Assistent.
- Prüfen: sieht auf hellem und dunklem Taskleisten-Hintergrund sauber aus.

### C — Packaging
1. `dist\Fleech\Fleech.exe` doppelklicken → **kein Konsolenfenster**, Tray-Icon erscheint.
2. Diktat testen (Assets/Prompts/Sounds vorhanden, Overlay erscheint).
3. Log unter `%APPDATA%\Fleech\fleech.log` prüfen (keine Pfad-/Asset-Fehler).

### D — Installer
1. `dist\FleechSetup-1.0.0.exe` ausführen → installiert nach Programme\Fleech.
2. **Windows-Suche** öffnen, „Fleech" tippen → App erscheint, startet per Enter.
3. Startmenü-Eintrag hat korrektes Icon, startet ohne Konsole.
4. Task-Manager: Prozess heißt „Fleech.exe", App-Gruppe „Fleech".
5. Deinstallation über „Apps & Features" → App weg, Startmenü-Eintrag weg,
   Autostart-Eintrag weg; `%APPDATA%\Fleech\settings.json` bleibt erhalten.

### E — Autostart
1. Einstellungen → Allgemein → Autostart aktivieren.
2. `regedit` → `HKCU\…\Run` → Wert „Fleech" zeigt auf die installierte EXE mit `--gui`.
3. Neu anmelden/testweise EXE-Ordner umbenennen und App aus neuem Pfad starten →
   Autostart-Pfad wird beim Start automatisch korrigiert.
4. Deaktivieren → Registry-Wert verschwindet.

### F — Update-Basis
1. Einstellungen → Advanced → **Version** zeigt „Fleech 1.0.0 (Build …)".
2. **Nach Updates suchen** ohne Feed → „Kein Feed konfiguriert (manuelle Updates)".
3. Update-Verteilung: neue `FleechSetup`-Version bauen und installieren (überinstalliert).

## Priorisierte Umsetzung (wie beauftragt)

1. Hotkey-Recorder ✅  2. Packaging zur EXE ✅  3. Installer + Startmenü + Suche ✅
4. Branding/Icon ✅  5. Autostart-Härtung ✅  6. Update-Basis ✅

## Nachtrag 2026-07-05: GPU-Settings-Checkbox + Live-Pipeline-Test aus installierter EXE

**GPU als persistente Settings-Checkbox statt Env-Var:**
- Neu: `usersettings.AdvancedSettings.prefer_gpu` (Default `true`), Checkbox unter
  Einstellungen → Advanced → „GPU-Beschleunigung bevorzugen (STT)". Setzt
  `config.stt.device` auf `auto` (GPU + automatischer CPU-Fallback) bzw. `cpu`
  (erzwungen). Persistiert in `settings.json`, übersteht Neustart/Autostart ohne
  jeden Env-Var-/`setx`-Umweg. Wirkt sofort zur Laufzeit (STT-Engine wird neu geladen).
- Zusätzlich (Build-Ebene, damit GPU-DLLs überhaupt gebündelt werden): die
  Build-Präferenz (`--gpu`/`--cpu`) wird jetzt in `packaging/build.local.json`
  **persistiert** — kein wiederholtes `$env:FLEECH_GPU` mehr nötig.
- Refactor zur Vermeidung von Code-Duplikation: `fleech/pipeline_factory.py`
  bündelt die Pipeline-Verdrahtung, genutzt von `DesktopApp` **und** dem neuen
  Diagnosemodus (siehe unten).

**Live-Test aller drei Modi aus der installierten EXE** (`Fleech.exe
--pipeline-selftest <fixtures>`, neu: `fleech/pipelinetest.py`):

| Modus | Ergebnis | Bemerkung |
|---|---|---|
| Cleanup | ✅ `ok` | Echter Ollama-Call (qwen3.5:9b), `.env`-Auflösung aus `%APPDATA%\Fleech` bestätigt (`Math-Key: gesetzt`) |
| Redax-Befehl (Audio) | ⚠ Fallback auf Cleanup | Whisper transkribierte „Redax" reproduzierbar als „Idax" (isoliert nachgestellt) — Trigger-Wort-ASR-Robustheit, kein Pipeline-Bug. Der sichere Fallback griff korrekt. |
| Redax-Befehl (JSON-Logik direkt) | ✅ korrekt | Mit korrekt geschriebenem Transkript ausgeführt: JSON-Parsing, LLM-Call und Text-Ersetzung funktionieren identisch zur M5-Abnahme |
| Formel-Modus | ⚠ Fallback auf Cleanup | Gemini Free-Tier-Quota (20/Tag) durch die vielen Testläufe heute erschöpft — 429 real ausgelöst, Backoff (2/4/8 s, 3 Versuche) korrekt durchlaufen, sauberer Fallback, kein Crash |

**Dabei gefundener und behobener echter Bug:** `_attach_console_if_available()`
überschrieb ein bereits gültiges, umgeleitetes `stdout` (z. B. `> out.txt`)
unconditional durch `CONOUT$`, sobald `AttachConsole` an irgendeine
Vorgänger-Konsole andockte — die Diagnose-Ausgabe landete dadurch im Leeren.
Gefixt: Ersetzung nur noch, wenn `stdout`/`stderr` tatsächlich `None` sind.
Regressionstest: `tests/test_main_stdio.py::test_valid_redirected_stdout_survives_successful_attach_console`.

**Bekannte, dokumentierte Grenze (neu):** Trigger-Wort „Redax" ist mit der
verwendeten SAPI-TTS-Stimme nicht robust gegen ASR (wird als „Idax" gehört) — für
den Bauplan-Abschnitt „Trigger-Robustheit" ohnehin als offene Frage vermerkt.
Empfehlung: mit echter menschlicher Stimme erneut prüfen; bei Bedarf `Redax` gegen
ein phonetisch distinkteres Wort tauschen (`command.trigger_word` in config.yaml).

## Nachtrag 2026-07-05 (2): Redax-Bug-Cluster + finaler Selbsttest

Vier Punkte umgesetzt (Details: [stt-vergleich.md](stt-vergleich.md), Memory,
Zusammenfassung im Chat): (1) Halluzinations-Fix für Befehle (Prompt-Regel +
Plausibilitäts-Check mit Flexions-tolerantem Overlap), (2) Trigger-Wort empirisch
ersetzt (Redax → **Kimono**, live umsteckbar in Einstellungen → Ausgabe),
(3) Single-Instance-Lock + IPC-Wake (Zweitstart öffnet laufende Instanz; live
verifiziert) + SDK-Retries deaktiviert (12-Request-Burst = 4 eigene × 3 SDK-Tries),
(4) STT-Vergleich turbo/large-v3.

Finaler `--pipeline-selftest` aus der installierten EXE:
- Cleanup ✅ · **Formel ✅ end-to-end aus installierter EXE** (`x^2 + bx + c = 0`,
  1,4 s — Gemini-Tagesquota war zurückgesetzt; damit ist die letzte Lücke der
  vorherigen Abnahme geschlossen).
- Command: TTS-Fixture wurde als „Kimono **macht** den letzten Satz formeller"
  gehört (statt „mach", Komma verloren) → Modell lieferte ein fragwürdiges
  replacement → **der neue Plausibilitäts-Check hat es im Feld gefangen** und
  sichtbar auf Cleanup zurückgefallen. Genau das designte Verhalten: lieber
  sichtbarer Fallback als halluzinierter Text. Mit sauberem Transkript (echte
  Stimme, dev-validiert) läuft der Befehls-Modus korrekt durch.
