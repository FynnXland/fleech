# Notification- & Focus-Policy (Windows-Integration)

Stand: 2026-07-04

## Kanal-Strategie

| Kanal | Rolle | Wann unterdrückt? |
|---|---|---|
| **Tray** | dauerhafter Statuskanal (Icon-Farbe, Tooltip) | nie |
| **Overlay** | aktiver Arbeitskanal (Status, Modus, Vorschau) | unter DND/Gaming reduziert; nie während einer vom Nutzer selbst gestarteten Aufnahme |
| **Sound** | kurzes lokales Feedback (start/stop/commit/error) | bei DND (opt-in), im Gaming-Modus reduziert/stumm (Regler) |
| **Toast** | NUR seltene, wichtige Ereignisse | unter DND und Gaming (außer kritisch), globaler Schalter, 90-s-Cooldown pro Art |

**Toast-Arten** (jede einzeln schaltbar): „läuft im Hintergrund" (einmalig),
kritischer Fehler, Provider-/Quota-Problem (429 nach Backoff), Abschluss langer
Verarbeitung (>15 s, Default aus). Kritische Toasts haben einen eigenen
„immer anzeigen"-Schalter, der sich über DND/Gaming/Global-Aus hinwegsetzt.
Ein Akzent-Sound für kritische Toasts ist opt-in und von den UI-Sounds getrennt.

## Signalquellen (ehrlich eingeordnet)

1. **`SHQueryUserNotificationState`** (shell32, **dokumentiert**): liefert
   Busy / Presentation / **D3D-Fullscreen** / AcceptsNotifications. Primärsignal;
   erkennt exklusive Fullscreen-Games direkt.
2. **Focus Assist / „Bitte nicht stören"** (Win 10/11): nur über die
   **undokumentierte** WNF-Abfrage (`NtQueryWnfStateData`,
   `WNF_SHEL_QUIETHOURS_ACTIVE_PROFILE_CHANGED`) lesbar. Best-Effort: Ergebnis
   True/False/None. **None (nicht ermittelbar) gilt konservativ als „kein DND"** —
   sonst würden Toasts auf Systemen, wo die Abfrage scheitert, grundlos dauerhaft
   verstummen. Live auf dem Zielsystem verifiziert (liefert korrekt False).
3. **Fullscreen-Heuristik**: Vordergrundfenster deckt seinen Monitor exakt ab und
   ist nicht Desktop/Shell (`Progman`/`WorkerW`) → Fullscreen. Ergänzt Signal 1 um
   randlose Vollbild-Apps. Prozessname (psutil) speist die **Ausnahmeliste**
   (z. B. `mpv.exe` soll nicht als „Gaming" gelten).

Der `FocusProbe` wird alle 3 s gepollt (µs-billige Win32-Calls); die
**`NotificationPolicy`** ist reine, zustandslose Logik ohne Win32/Qt und vollständig
unit-getestet. Jede Teil-Abfrage ist einzeln fehler-isoliert — ein kaputtes Signal
degradiert zu „Signal unbekannt", nie zu einem App-Fehler.

## Verhalten im Gaming-/Fullscreen-Modus

- keine nicht-kritischen Toasts
- Overlay: konfigurierbar — nur bei Aufnahme/Verarbeitung (Default), Compact,
  versteckt, oder unverändert; die Nutzereinstellungen werden dabei **nie**
  überschrieben (temporärer Override)
- Sounds: Reduktionsregler (Default 50 %, 0 % = stumm im Spiel)
- Ausnahmeliste per Prozessname

## Settings (Seite „Focus & Toasts")

Alle Schalter der Anforderung sind vorhanden: DND respektieren, Sounds bei DND stumm,
Toasts global, kritische Toasts immer, drei Einzel-Toast-Schalter, Akzent-Sound,
Gaming-Erkennung, Overlay-Verhalten im Gaming-Modus, Sound-Reduktion, Ausnahmeliste,
**Test-Toast** und **Test-Sound** (der Test-Toast läuft absichtlich durch die echte
Policy — unter DND/Gaming wird er unterdrückt und das Log nennt den Grund).

## Empfohlene Default-Konfiguration (produktiver Alltag) — so ausgeliefert

```jsonc
"focus": {
  "respect_dnd": true,            // Windows-Fokusmomente respektieren
  "dnd_mute_sounds": false,       // lokale Sounds sind leise genug
  "toasts_enabled": true,         // aber nur seltene Arten …
  "toast_critical_always": true,
  "toast_background_info": true,  // erscheint ohnehin nur einmal
  "toast_provider_quota": true,
  "toast_long_processing": false, // Overlay/Tray reichen dafuer
  "notification_sounds": false,
  "gaming_detection": true,
  "gaming_overlay": "activity_only",
  "gaming_sound_factor": 0.5,
  "gaming_exceptions": []         // Video-Player hier eintragen (mpv.exe, vlc.exe)
}
```

## Bekannte Grenzen / Heuristiken

1. **Focus Assist via WNF ist undokumentiert.** Funktioniert stabil seit Win10 1709
   (live verifiziert), kann aber in künftigen Windows-Versionen brechen → dann
   liefert die Abfrage None und Fleech verhält sich, als wäre kein DND aktiv
   (sichere, ehrliche Degradation; Rest der Policy greift weiter).
2. **Windows unterdrückt Toasts unter DND zusätzlich selbst** — unsere Policy ist
   die erste Verteidigungslinie, Windows die zweite. Der „kritische Toasts immer"-
   Schalter kann Windows' eigene Unterdrückung NICHT umgehen (bewusst: wir kämpfen
   nicht gegen das Betriebssystem).
3. **Fullscreen-Heuristik:** randlose Fenster, die exakt monitorgroß sind, gelten
   als Fullscreen — auch wenn es „nur" ein maximierter randloser Editor ist.
   Dafür gibt es die Ausnahmeliste. Fenster-Games im Borderless-Mode auf einem
   Zweitmonitor werden nur erkannt, wenn sie im Vordergrund sind.
4. **Windows' eigener Toast-Ton** wird von den Windows-Benachrichtigungs-
   einstellungen bestimmt, nicht von Fleech (Qt-Toasts erlauben keine
   Pro-Toast-Soundkontrolle).
5. Der Fokus-Kontext wird **alle 3 s** gepollt — ein Spielstart wird also bis zu
   3 s später erkannt; für Toast-Entscheidungen wird zusätzlich immer frisch
   abgefragt.

## Testprotokoll (2026-07-04)

| Test | Ergebnis |
|---|---|
| Unit-Suite gesamt (150 Tests) | ✅ grün |
| Policy-Matrix: DND an/aus/unbekannt × Toast-Arten, kritisch vs. nicht-kritisch, global aus (10 Tests) | ✅ |
| Gaming: D3D/Heuristik, Erkennung abschaltbar, Ausnahmeliste (case-insensitive) | ✅ |
| Sounds: DND-Mute opt-in, Gaming-Faktor 0.5/0.0, normal 1.0 | ✅ |
| Overlay-Override-Matrix (activity_only/compact/hidden/unchanged, DND, Ausnahme) | ✅ |
| Notifier: Anzeige vs. Unterdrückung, 90-s-Cooldown, Bypass für Test-Button, Akzent-Sound nur kritisch+opt-in | ✅ |
| Overlay-Override offscreen: always→Gaming→Aufnahme sichtbar→hidden→Override weg, Settings unverändert | ✅ |
| Persistenz: focus-Sektion Roundtrip + Defaults | ✅ |
| **Live: FocusProbe auf Zielsystem** — Focus Assist lesbar (False), Vordergrundprozess korrekt (claude.exe), kein Fullscreen | ✅ |
| **Live: App-Lauf mit 3-s-Polling** — 12 s, 0 Fehler im Log | ✅ |
| Echtes Spiel/DND am Bildschirm (Overlay-Verhalten, Toast-Unterdrückung fühlbar) | ⚠ Nutzer-Abnahme: Spiel starten bzw. DND aktivieren und Test-Toast-Button drücken |
