# Desktop-App: Architektur, State-Modell, Settings-Schema, Testprotokoll

Stand: 2026-07-04

## Architekturübersicht

```
                         ┌─────────────────────────────────────────────┐
                         │ Qt-Main-Thread                              │
 pynput-Listener-Thread  │  TrayController   OverlayWindow   Settings- │
 ┌────────────────────┐  │  (Status-Icon,    (verschiebbar,  Window    │
 │ Hotkey press/release│  │   Menue, Toast)   persistiert)   (8 Seiten)│
 │        │            │  └───────▲──────────────▲───────────────▲────┘
 │        ▼            │          │   Qt-Signale (queued, thread-sicher)
 │ RecordingController │          │
 │ (hold/toggle,       │      StateBus  ◄──────────────┐
 │  entprellt)         │   (idle/listening/            │
 └───────┬─────────────┘    processing/error)          │
         │ on_start/on_stop                            │
         ▼                                             │
 ┌──────────────────────────────────────────────┐      │
 │ DesktopApp (Orchestrator)                    │──────┘
 │  Recorder ── PreviewStreamer ─► preview_text │
 │  AudioFocusController (Ducking, Guard)       │   Worker-Threads
 │  SoundPlayer (start/stop/commit/error)       │
 │  Pipeline: STT → Routing → LLM → Injection   │
 └──────────────────────────────────────────────┘
          Engine = unveraenderte Module aus M1–M6 + Audio-Fokus
```

- **Engine unangetastet:** `pipeline.py`, `stt/`, `llm/`, `audiofocus.py`,
  `document.py`, `commands.py` sind dieselben wie im CLI-Modus (der über
  `python -m fleech --cli` weiter funktioniert, inkl. Tk-Overlay).
- **Zweischichtige Konfiguration:** `config.yaml` (technisch: Modelle, Endpoints,
  Prompts) + `%APPDATA%/Fleech/settings.json` (alles, was das Settings-UI ändert).
  `UserSettings.apply_to(config)` legt die UI-Schicht beim Start über die Basis.
- **Kein Terminal nötig:** `Fleech.pyw` (Doppelklick) bzw. Autostart starten über
  `pythonw` der venv; Logs gehen nach `%APPDATA%/Fleech/fleech.log`.

## State-Modell

```
 idle ──(Hotkey/Tray)──► listening ──(Stop)──► processing ──┬─► idle   („eingefuegt“)
                              │                             └─► error ─► idle
                              └ Loopback-Block/Mic-Fehler ──► error
```

| Zustand | Tray-Icon | Overlay | Sound |
|---|---|---|---|
| idle | grau | versteckt (bei `during_activity`) | — |
| listening | rot | „hoere zu" + Live-Vorschau | start |
| processing | amber | „verarbeite" | stop |
| error | violett | Fehlerzeile | error |

Übergänge werden von Worker-Threads über `StateBus`-Signale emittiert; Tray und
Overlay konsumieren im Qt-Thread (Queued Connections). `pipeline.process()` liefert
`ok | fallback | empty | too_short | error` — daraus entstehen Folge-Zustand,
Feedbacktext und Commit-/Fehler-Sound.

## Settings-Schema (`%APPDATA%/Fleech/settings.json`)

```jsonc
{
  "general":   { "autostart": false, "language": "de" },
  "recording": { "mode": "hold|toggle", "hotkey": "f9",
                 "microphone": null },              // null = Systemstandard
                 // math_hotkey/math_toggle_hotkey gibt es nicht mehr (seit v3.0.0
                 // kein Formel-Modus); alte Dateien laden trotzdem weiter.
  "audio_focus": { "mode": "pure_mic|soft_duck|hard_focus" },
  "math":      { "priority": "math|natural|mixed", "math_focus": false },
  "overlay":   { "visibility": "always|during_activity|auto_hide|off",
                 "auto_hide_seconds": 4.0, "opacity": 0.9, "compact": false,
                 "click_through": false,
                 "x": null, "y": null, "width": 380, "height": 100 },
                 // x/y null = Default: rechter Rand, vertikal ~mittig
  "sounds":    { "enabled": true, "volume": 0.4, "preset": "soft|click",
                 "start": true, "stop": true, "commit": true, "error": true },
  "output":    { "intervention": "minimal|standard|strong" },
  "advanced":  { "debug_logging": false, "update_feed_url": "",
                 "prefer_gpu": true },  // Settings-Checkbox statt Env-Var/setx;
                                        // true→stt.device="auto" (GPU+Fallback),
                                        // false→"cpu" erzwingen. Uebersteht
                                        // Neustart/Autostart (settings.json).
  "window":    { "x": null, "y": null, "width": 780, "height": 560,
                 "tray_hint_shown": false }
}
```

Jede UI-Änderung speichert sofort; unbekannte Schlüssel werden beim Laden ignoriert
(vorwärtskompatibel), kaputte Dateien fallen auf Defaults zurück.

**Defaults (Produktentscheidung „ruhige UX"):** Tray aktiv, Overlay nur während
Aufnahme/Verarbeitung, Soft Duck, Hold-to-talk, dezente Sounds an, Eingriffsgrad
Standard, Schließen = Tray (Hinweis-Toast nur beim ersten Mal).

## Eingriffsgrad & Mathe-Priorität

| Stufe | Verhalten |
|---|---|
| Minimal | kein LLM — fast Rohtranskript, minimale Latenz |
| Standard | Prompt 1 (Füllwörter, Selbstkorrektur, Interpunktion nach Bedeutung) |
| Strong | Prompt 1 + [prompts/cleanup-strong.md](../prompts/cleanup-strong.md) (Absätze, Glättung, Aufzählungen) |

| Mathe-Priorität | Verhalten |
|---|---|
| Mathe | gesprochene Delimiter aktiv + Whisper bekommt Mathe-Vokabular-Hinweis |
| Natürlich | Formel-Modus nur per Hotkey; „Formel: …" bleibt normaler Text |
| Gemischt (Default) | Hotkey + Delimiter, kein erzwungener Vokabular-Hinweis |

## Testprotokoll (2026-07-04)

| Test | Ergebnis |
|---|---|
| Unit-Suite gesamt (129 Tests) | ✅ grün |
| Bedienmodi: Hold, Toggle, Auto-Repeat-Entprellung, Moduswechsel bei laufender Aufnahme, Tray-Toggle (9 Tests) | ✅ |
| Persistenz: Roundtrip aller Sektionen, fehlende/korrupte Datei, unbekannte Keys, apply_to(config) (5 Tests) | ✅ |
| Overlay (offscreen): Default-Position rechtsseitig, Sichtbarkeits-Matrix (always/during/off), Compact, Opacity, Überlängen-Text | ✅ |
| Tray: Icons für alle 4 Zustände erzeugbar | ✅ |
| Sounds: beide Presets, alle 4 Events, <1 s, Einzelschalter/Volume/Global-Aus greifen | ✅ (dabei Hüllkurven-Bug gefunden und gefixt) |
| StateBus-Übergänge idle→listening→processing→idle | ✅ |
| Settings-Fenster (offscreen): 8 Seiten bauen, Geometrie-Persistenz beim Schließen, Tray-Callback | ✅ |
| **Live-Start auf dem Zielsystem:** App läuft ohne Konsole, STT nach ~5 s warm, Log in %APPDATA%, settings.json mit Overlay-Default (x=1515, rechtsseitig) persistiert | ✅ |
| Pipeline-Statuscodes, Eingriffsgrad minimal/strong, Mathe-Priorität „natural" deaktiviert Delimiter | ✅ |
| Optik/Bedienung am Bildschirm (Tray-Menü, Overlay ziehen, Sounds hören, Toggle-Gefühl) | ⚠ Nutzer-Abnahme nötig |

## Bekannte Grenzen

- Hotkey-Erfassung im Settings-UI ist ein Textfeld (pynput-Namen), kein „Taste
  drücken"-Recorder.
- `QSystemTrayIcon`-Toasts nutzen die Windows-Benachrichtigungen; wenn der Fokus-
  Assistent („Bitte nicht stören") aktiv ist, erscheint der Erste-Schließung-Hinweis
  ggf. nicht.
- „App neu laden" ersetzt den Prozess (os.execv) — laufende Aufnahmen gehen dabei
  verloren (wird vorher gestoppt).
- Kein signierter Installer; Start über `Fleech.pyw`, Autostart über HKCU-Run-Key.
  Packaging (PyInstaller) wäre der nächste Schritt, wenn Verteilung an Dritte ansteht.
