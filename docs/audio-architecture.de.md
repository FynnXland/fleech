# Audio-Architektur: Aufnahme, Ducking, Geräteschutz

Stand: 6.1.0 · maßgeblich ist der Quellcode (`fleech/audio.py`, `fleech/audiofocus.py`).

## Kern-Invariante

**Aufnahme und Wiedergabe sind zwei getrennte Welten, die sich im Code nie berühren.**

```
AUFNAHME (Transkription)                 WIEDERGABE (Komfort)
─────────────────────────                ─────────────────────────
sounddevice.InputStream                  Lautstärken FREMDER Prozesse
auf DEM gewählten Mikrofon               Windows: pycaw / WASAPI-Sessions
│                                        Linux:   pulsectl / Sink-Inputs
│                                        │
├─ fleech/audio.py (Recorder)            ├─ fleech/audiofocus.py (PlaybackDucker)
├─ DeviceGuard warnt vor Loopback-       ├─ relativ ducken (Pegel × Restlautstärke)
│  Geräten und gesperrten Geräten        ├─ weiche Fades, exakte Wiederherstellung
└─ → STT → LLM → Einfügen                └─ eigener Prozess wird übersprungen
```

- Es gibt **keinen Code-Pfad**, der WASAPI-Loopback, Stereomix oder App-Audio in die
  Transkription mischt. Der Recorder öffnet ausschließlich einen Input-Stream auf dem
  gewählten Mikrofon.
- Ducking ist reine *Ausgabe*-Steuerung über die Session-Lautstärken anderer Prozesse.
  Es fließt kein Audio zurück. Ein Fehler beim Ducken darf das Diktat nie stören; er
  landet nur im Protokoll.
- Ducken und Wiederherstellen laufen in einem kurzen Hintergrund-Thread, damit der Fade
  den Hotkey-Listener nicht blockiert.

## Geräteschutz (DeviceGuard)

`DeviceGuard.check()` prüft das gewählte Eingabegerät in dieser Reihenfolge:

1. **Sperrliste des Nutzers** (Einstellungen → Aufnahme → „Gesperrte Geräte“): ein
   Namensteil je Zeile, Groß-/Kleinschreibung egal, Zeilen mit `#` zählen nicht. Steht
   vorn, damit ein bewusst ausgeschlossenes Gerät nie durchrutscht.
2. **Monitor-Quellen unter Linux**: PulseAudio/PipeWire meldet strukturell, ob eine
   Quelle der Monitor einer Ausgabe ist (`monitor_of_sink`). Unter Windows gibt es kein
   Gegenstück — dort ist „Stereomix“ ein ganz normales Aufnahmegerät.
3. **Wortliste** typischer Loopback-Namen: Stereo Mix, Loopback, What U Hear, Wave Out
   Mix, Aufnahmesumme, CABLE Output, VB-Audio, Voicemeeter, „Monitor of …“ u. a.

Ein Treffer **blockiert die Aufnahme nicht**, er wird gemeldet: im Protokoll (beim
Start und bei jedem Aufnahmestart), nach einem Wechsel des Mikrofons oder der Sperrliste
zusätzlich als Tray-Hinweis. Geprüft wird beim Start und nach jeder solchen Änderung in
den Einstellungen. Fehlt das gewählte Mikrofon (abgesteckt, Standby), nimmt Fleech über
den Systemstandard auf und sagt das einmal je Gerät an der Pille.

## Die drei Modi

Einstellungen → Audio-Fokus → „Fokus-Modus“, dazu der Regler „Restlautstärke anderer
Apps“ (Vorgabe 25 %).

| Anzeige | Wert | Verhalten |
|---|---|---|
| Aus (fremde Apps unverändert) | `pure_mic` | Kein Ducking, nur die Mic-only-Garantie. |
| Leiser stellen **(Vorgabe)** | `soft_duck` | Fremde Apps sinken auf die Restlautstärke, weicher Fade von 250 ms. |
| Stark absenken | `hard_focus` | Siehe Hinweis unten. |

Relatives Ducken heißt: Eine App, die vorher auf 40 % stand, landet bei 25 %
Restlautstärke auf 10 %. Die Lautstärke-Verhältnisse bleiben erhalten, und nach der
Aufnahme stellt Fleech die gemerkten Ursprungswerte wieder her. Bricht ein Ducking-Lauf
mittendrin ab, behält Fleech die schon gemerkten Ursprungswerte — sonst würde jedes
weitere Diktat die Lautstärke ein Stück weiter absenken.

**Hinweis zu „Stark absenken“:** Der Regler setzt in der Desktop-App die Restlautstärke
für beide Modi (`UserSettings.apply_to`). „Stark absenken“ wirkt deshalb derzeit genauso
wie „Leiser stellen“; der eigene Vorgabewert von 8 % (`hard_duck_level` in
`fleech/config.py`) kommt nicht zum Tragen.

Die Fade-Dauer (250 ms) und das komplette Stummschalten statt Duckens (`hard_mute`,
aus) sind feste Vorgaben in `fleech/config.py`. Der Abschnitt `audio_focus:` in
`config.yaml` wird derzeit nicht eingelesen; Modus und Restlautstärke kommen aus den
Einstellungen.

## Protokoll

- Nach dem Aufwärmen der Erkennung eine Statuszeile:
  `Mic: … | Capture: nur Mikrofon | Fokus: soft_duck`.
- `Ducking AN (auf 25%): …` mit den Namen der geduckten Prozesse, danach
  `Ducking AUS — Lautstaerken wiederhergestellt.`
- Geräteprüfung: `Aufnahmegeraet geprueft: … — in Ordnung.` oder eine ⚠-Zeile mit Grund.

## Selbsttest

`python -m fleech --audio-selftest` zeigt Statuszeile und Prüfergebnis, spielt 8 s lang
einen leisen Sinus-Sweep über den Standardausgang und nimmt parallel nur vom Mikrofon
auf. Man spricht die angezeigte Testformel; danach erscheint das Transkript. Der Testton
darf darin nicht als Text auftauchen.

Zwei Einschränkungen: Der Test nutzt `config.yaml` und die eingebauten Vorgaben, nicht
die Einstellungen der Desktop-App — das Mikrofon ist `audio.device`, geduckt wird mit
„Leiser stellen“ auf 25 %. Und der Testton selbst wird nicht geduckt, er gehört zu
Fleechs eigenem Prozess. Leiser werden nur andere Apps, die schon vor dem Test Ton
abspielen.

## Bekannte Grenzen

1. **Akustisches Übersprechen ist Physik.** Läuft Audio über *Lautsprecher*, kann das
   Mikrofon es akustisch aufnehmen. Das ist kein Software-Loopback und softwareseitig
   nicht vollständig zu verhindern. Ducking reduziert es, ein **Headset beseitigt es**.
2. **Treiber-Verbesserungen sind nicht programmatisch schaltbar.** Windows bietet keine
   stabile Schnittstelle, um Rauschunterdrückung oder automatische Pegelregelung des
   Treibers pro App zu schalten. Wer das will, aktiviert es einmalig in den
   Windows-Sound-Einstellungen des Mikrofons.
3. **Neue Audio-Sessions während der Aufnahme** (eine App startet mittendrin Ton) werden
   erst beim nächsten Diktat geduckt.
4. **Unter Windows ist der Geräteschutz namensbasiert.** Ein virtuelles Kabel mit
   unauffälligem Namen erkennt er nicht — dafür gibt es die Sperrliste. Systemaudio
   mischt die Architektur trotzdem nie bei; das Risiko wäre nur ein Loopback-Gerät, das
   der Nutzer selbst als Mikrofon gewählt hat.

## Historie

Bis 3.0.0 gab es einen eigenen Formel-Modus mit Hotkey, eine Mikrofon-Pegelsteuerung
(„Math Focus“) und einen Cloud-Pfad mit Rate-Limit-Backoff; in diesem Modus wurden
Loopback-Geräte blockiert. Das alles ist entfallen — Formeln übersetzt heute ein lokaler
Parser (`fleech/formula.py`). Die Klasse `MicLevelController` steht noch in
`audiofocus.py`, wird aber nirgends erzeugt.
