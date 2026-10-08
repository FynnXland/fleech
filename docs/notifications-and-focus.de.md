# Benachrichtigungen und Fokus

Stand: 6.1.0 · Code: `fleech/ui/notifications.py` (Policy), `fleech/ui/windowsfocus.py`
(Fokus-Signale), Einstellungsseite `fleech/ui/settings/benachrichtigungen.py`.

## Kanal-Strategie

| Kanal | Rolle | Wann zurückgenommen? |
|---|---|---|
| **Tray** | dauerhafter Statuskanal (Icon-Farbe, Tooltip) | nie |
| **Pille** | aktiver Arbeitskanal (Aufnahme, Verarbeitung, Hinweise) | bei „Nicht stören“ und im Spiel, siehe unten |
| **Sound** | kurzes lokales Feedback (Start, Stopp, Eingefügt, Fehler) | bei „Nicht stören“ auf Wunsch stumm, im Spiel leiser |
| **Toast** (Windows-Banner) | NUR seltene, wichtige Ereignisse | bei „Nicht stören“ und im Spiel (außer kritisch); 90 s Pause je Art |

Wichtige Hinweise zum Diktat selbst zeigt die Pille als Blase, unabhängig von diesen
Einstellungen — etwa „liegt in der Zwischenablage“ oder dass die KI auf dem Prozessor
statt auf der Grafikkarte rechnet.

## Toast-Arten

| Art | Wann | kritisch? |
|---|---|---|
| `background_info` | „läuft im Hintergrund“ beim ersten Schließen des Fensters; Update gefunden; Test-Toast | nein |
| `critical_error` | Verarbeitung fehlgeschlagen; Diktat liegt in der Zwischenablage statt im Feld | ja |
| `provider_quota` | Ein Cloud-Anbieter lehnt den API-Schlüssel ab (401/403) oder meldet ein erschöpftes Kontingent (429). Fleech wiederholt nicht, der Text kommt unbereinigt an. | nein |
| `long_processing` | Diktat war erst nach mehr als 15 s fertig | nein |

Kritische Toasts hängen an einem eigenen Feld (`toast_critical_always`) und setzen sich
über „Nicht stören“, Spiel und den globalen Schalter hinweg. Ein eigener
Akzent-Sound für kritische Toasts ist opt-in.

In der Oberfläche gibt es dafür nur noch einen Regler, „Windows-Banner“:

| Stufe | Wirkung |
|---|---|
| Nichts | keine Toasts, auch keine kritischen |
| Wichtiges | kritische Fehler und Anbieter-Probleme |
| Alles | zusätzlich die Statusmeldungen (`background_info`, `long_processing`) |

Ausgeliefert sind alle Arten außer `long_processing` an; der Regler zeigt dann „Alles“.

Einige Rückmeldungen auf eine eigene Aktion gehen ohne Policy direkt an den Tray: „Verlauf
gelöscht“, ein gelernter Wörterbuch-Eintrag und die Warnung nach dem Wechsel auf ein
Loopback-Gerät.

## Signalquellen

1. **`SHQueryUserNotificationState`** (shell32, **dokumentiert**): Busy, Präsentation,
   **D3D-Vollbild**, nimmt Benachrichtigungen an. Erkennt exklusive Vollbild-Spiele direkt.
2. **Focus Assist / „Nicht stören“**: nur über die **undokumentierte** WNF-Abfrage
   (`NtQueryWnfStateData`, `WNF_SHEL_QUIETHOURS_ACTIVE_PROFILE_CHANGED`) lesbar.
   Ergebnis True, False oder None. **None (nicht ermittelbar) gilt als „kein DND“** —
   sonst blieben Toasts auf Systemen, auf denen die Abfrage scheitert, grundlos stumm.
3. **Vollbild-Heuristik**: Das Vordergrundfenster deckt seinen Monitor vollständig ab und
   ist nicht Desktop oder Shell (`Progman`, `WorkerW`). Ergänzt Signal 1 um randlose
   Vollbild-Apps. Der Prozessname (psutil) speist die Ausnahmeliste.

**Linux (X11):** Vollbild und Prozessname kommen über EWMH (`fleech/ui/x11tools.py`).
„Nicht stören“ ist dort nicht allgemein abfragbar und bleibt None. Unter Wayland
entfällt die Vollbild-Erkennung.

Die App fragt den Fokus-Zustand alle 3 s ab; vor jeder Toast-Entscheidung wird frisch
gefragt. Jede Teilabfrage ist einzeln abgesichert — ein kaputtes Signal wird zu
„unbekannt“, nie zu einem App-Fehler. Die `NotificationPolicy` ist reine Logik ohne
Win32 und Qt und vollständig unit-getestet (`tests/test_notifications.py`).

## Verhalten im Spiel oder Vollbild

- keine nicht-kritischen Toasts
- Pille nach der Einstellung „Overlay im Gaming-Modus“:
  - „Nur bei Aufnahme/Verarbeitung“ (Vorgabe) und „Compact“ wirken gleich: Eine
    dauerhaft sichtbare Pille erscheint nur noch während Aufnahme und Verarbeitung.
  - „Versteckt“ blendet die Pille aus, auch während der Aufnahme.
  - „Unverändert“ lässt alles, wie es ist.
- Fleech-eigene Töne mit dem Regler „Fleech-eigene Töne im Spiel“ (Vorgabe 50 %, 0 % = stumm)
- Bei „Modell-Warmhaltung: Nach Nutzung“ (Vorgabe, Einstellungen → Advanced) entlädt
  Fleech beim Spielstart das lokale KI-Modell und gibt so Grafikspeicher frei.
- Prozesse auf der Ausnahmeliste gelten nie als Spiel (z. B. ein Videoplayer).

Die Nutzereinstellungen der Pille werden dabei **nie** überschrieben; es ist ein
vorübergehender Override. Bei „Nicht stören“ ohne Spiel gilt — sofern
„Windows Do Not Disturb respektieren“ an ist — dasselbe wie „Nur bei
Aufnahme/Verarbeitung“.

## Einstellungsseite „Benachrichtigungen“

Windows Do Not Disturb respektieren · Sounds bei DND stummschalten · Windows-Banner
(Nichts/Wichtiges/Alles) · Akzent-Sound bei kritischen Toasts · Gaming-/Fullscreen-Erkennung
· Overlay im Gaming-Modus · Fleech-eigene Töne im Spiel · Ausnahmen (Prozesse) · Testen
(Test-Toast, Test-Sound).

Der Test-Toast läuft absichtlich durch die echte Policy: Unter „Nicht stören“ oder im
Spiel wird er unterdrückt, und das Protokoll vermerkt das. Er zählt als Statusmeldung —
bei der Stufe „Wichtiges“ erscheint er deshalb nicht.

## Vorgaben in `settings.json`

```jsonc
"focus": {
  "respect_dnd": true,            // „Nicht stören“ respektieren
  "dnd_mute_sounds": false,       // lokale Töne sind leise genug
  "toasts_enabled": true,         // nicht-kritische Toasts insgesamt
  "toast_critical_always": true,
  "toast_background_info": true,  // „läuft im Hintergrund" erscheint nur einmal
  "toast_provider_quota": true,
  "toast_long_processing": false, // Pille und Tray reichen dafür
  "notification_sounds": false,   // Akzent-Sound bei kritischen Toasts
  "gaming_detection": true,
  "gaming_overlay": "activity_only",
  "gaming_sound_factor": 0.5,
  "gaming_exceptions": []         // z. B. "mpv.exe", "vlc.exe"
}
```

## Bekannte Grenzen

1. **Focus Assist über WNF ist undokumentiert.** Kann in künftigen Windows-Versionen
   brechen. Dann liefert die Abfrage None, und Fleech verhält sich, als wäre kein DND
   aktiv; der Rest der Policy greift weiter.
2. **Windows unterdrückt Toasts unter DND zusätzlich selbst.** Fleechs Policy ist die
   erste Linie, Windows die zweite. Der Schalter für kritische Toasts kann Windows'
   eigene Unterdrückung nicht umgehen — bewusst.
3. **Vollbild-Heuristik:** Ein randloses Fenster, das den ganzen Monitor füllt, gilt als
   Vollbild, auch wenn es ein maximierter Editor ist. Dafür gibt es die Ausnahmeliste.
   Ein Spiel im Fenstermodus auf einem Zweitmonitor wird nur erkannt, solange es im
   Vordergrund ist.
4. **Der Ton eines Windows-Banners** hängt an den Windows-Benachrichtigungseinstellungen,
   nicht an Fleech.
5. **Ein Spielstart wird bis zu 3 s später erkannt**, weil der Fokus-Zustand im
   3-s-Takt abgefragt wird.
