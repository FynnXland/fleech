# Technische Notiz: Audio-Fokus-Architektur (Heavy-Math-Dictation)

Stand: 2026-07-04

## Kern-Invariante

**Capture und Playback sind zwei getrennte Welten, die sich im Code nie berühren.**

```
CAPTURE  (Transkription)                 PLAYBACK  (Komfort)
─────────────────────────                ─────────────────────────
sounddevice.InputStream                  pycaw / WASAPI-Session-Volumes
auf DEM gewählten Mikrofon               ISimpleAudioVolume FREMDER Prozesse
│                                        │
├─ fleech/audio.py (Recorder)            ├─ fleech/audiofocus.py (PlaybackDucker)
├─ DeviceGuard blockt Loopback-Namen     ├─ relativ ducken (orig × duck_level)
└─ → STT → LLM → Injection               └─ weiche Fades, exakte Wiederherstellung
```

- Es existiert **kein Code-Pfad**, der WASAPI-Loopback, Stereo Mix oder App-Audio in
  die Transkription mischt. Der Recorder öffnet ausschließlich einen Input-Stream auf
  dem konfigurierten Mikrofon.
- Ducking ist reine *Ausgabe*-Steuerung über die Session-Lautstärken anderer Prozesse
  (eigene PID wird übersprungen). Es fließt kein Audio zurück.
- Der **DeviceGuard** prüft den Namen des gewählten Input-Geräts gegen Loopback-Muster
  (Stereo Mix, Loopback, What U Hear, VB-Cable, Voicemeeter, …). Im Formel-Modus wird
  ein solches Gerät standardmäßig **blockiert** (`block_loopback_in_math: true`), im
  normalen Diktat sichtbar gewarnt.

## Die drei Modi

| Modus | Ducking | Verhalten |
|---|---|---|
| `pure_mic` | keins | Nur die Mic-only-Garantie; andere Apps unverändert. |
| `soft_duck` **(Default)** | auf 25 % (relativ) | Apps bleiben hörbar, weicher 250-ms-Fade rein/raus. |
| `hard_focus` | auf 8 % (relativ) | Qualität vor Komfort; optional + `math_focus`-Härtung. |

Relatives Ducken heißt: Eine App, die vorher auf 40 % stand, landet bei 10 % — die
Lautstärke-Verhältnisse des Nutzers bleiben erhalten, und `restore()` stellt die
exakten Ursprungswerte wieder her. `hard_mute: true` (opt-in) schaltet stattdessen
komplett stumm; Standard ist immer der weiche Fade.

## Math Focus (optionaler Schalter)

- `mic_level`: senkt den Pegel des Standard-Aufnahmegeräts während der Aufnahme
  (gegen Übersteuern durch aggressive Treiber-Boosts) und stellt ihn danach exakt
  wieder her.
- `initial_prompt`: Whisper bekommt beim Math-Hotkey ein Mathe-Vokabular als Hinweis
  („Klammer auf/zu", „das Ganze durch", „Formel Ende", …) — stabilisiert die
  Grenz-/Klammer-Erkennung im ASR-Hinweistext für den multimodalen Call.

## Rate-Limit-Robustheit (multimodaler Pfad)

HTTP 429 vom Formel-Provider → exponentieller Backoff (2 s, 4 s, 8 s; `retry_max: 3`,
konfigurierbar unter `llm.math`), jede Stufe sichtbar im Log. Nach dem Cap: sauberer
Fallback auf Cleanup — die gesprochenen Worte landen als Text im Feld, nichts geht
verloren.

## Logging

Beim Start und bei jeder Aufnahme sichtbar: aktives Mikrofon, Mic-only-Status,
Fokus-Modus, geduckte Prozesse (Namensliste), Ducking an/aus, Mic-Pegel-Änderungen,
Loopback-Konflikte (Warnung bzw. Blockade), 429-Retries. Das Overlay zeigt beim
Aufnahmestart dieselbe Statuszeile.

## Selbsttest

`python -m fleech --audio-selftest`: spielt einen Sinus-Sweep über die Lautsprecher
(bei aktivem Ducking hörbar leiser), nimmt parallel nur vom Mikrofon auf, der Nutzer
spricht die Testformel, das Transkript wird angezeigt und bewertet.

## Bekannte Grenzen

1. **Akustisches Übersprechen ist Physik:** Läuft Audio über *Lautsprecher*, kann das
   Mikrofon es akustisch aufnehmen. Das ist kein Software-Loopback und softwareseitig
   nicht vollständig verhinderbar — Ducking reduziert es stark, ein **Headset
   eliminiert es**. Der Selbsttest macht es sichtbar.
2. **Treiber-Enhancements nicht programmatisch schaltbar:** Windows bietet keine
   stabile API, um Treiber-APOs (Noise Suppression, AGC) pro App zu togglen. Hard
   Focus implementiert stattdessen die kontrollierbaren Hebel (stärkeres Ducking,
   Mic-Pegel, Whisper-Härtung). Wer Treiber-Noise-Suppression will: einmalig in den
   Windows-Sound-Einstellungen des Mikrofons aktivieren.
3. **`mic_level` wirkt auf das System-Standard-Aufnahmegerät** — nicht zwingend auf
   ein per Config abweichend gewähltes Mikrofon.
4. **Neue Audio-Sessions während der Aufnahme** (App startet Sound mittendrin) werden
   erst beim nächsten Duck-Zyklus erfasst.
5. **Delimiter-Weg ohne ASR-Hinweis:** Beim gesprochenen „Formel: …"-Weg ist der Modus
   erst nach der Transkription bekannt — der `initial_prompt` greift nur beim
   Math-Hotkey. Für Heavy-Math ist der Hotkey ohnehin der robustere Weg.
6. **DeviceGuard ist namensbasiert.** Exotische virtuelle Kabel mit unauffälligem
   Namen erkennt er nicht; die Architektur mischt aber auch dann kein Systemaudio —
   das Risiko wäre, dass der *Nutzer* physisch ein Loopback-Gerät als „Mikrofon"
   verkabelt hat.

## Empfohlene Defaults für Heavy-Math-User

```yaml
audio_focus:
  mode: soft_duck        # Produktentscheidung: Mic-only + Soft Duck als Standard
  duck_level: 0.25
  fade_ms: 250
  block_loopback_in_math: true
  math_focus:
    enabled: true        # bei langen Formeldiktaten: an
    mic_level: 0.7       # nur wenn der Treiber-Boost hörbar übersteuert, sonst null
hotkey:
  math: f10              # Formeln immer per Hotkey, nicht per Delimiter
```

Dazu: **Headset statt Lautsprecher** (eliminiert Übersprechen) und für häufige
Formeln Gemini-Billing aktivieren (Free-Tier-429 bei Bursts) oder einen anderen
multimodalen Provider in `llm.math` einstecken.

## Testprotokoll (2026-07-04)

| Test | Ergebnis |
|---|---|
| Unit-Suite (103 Tests: Moduswechsel, Fade, Guard, Blockade, Backoff, Regression) | ✅ alle grün |
| Fade weich + monoton, exakte Wiederherstellung (Unit, FakeSessions) | ✅ |
| Loopback-Blockade nur im Mathe-Modus, Warnung im Diktat (Unit) | ✅ |
| **Live-Ducking gegen 10 echte Sessions** (Discord, Steam, Browser, …): relativ auf 25 %, exakt restauriert, Fades 240/232 ms | ✅ bestanden |
| Device-Guard live: „Mikrofon (Scarlett Solo USB)" → OK, kein Loopback | ✅ |
| Selbsttest-Mechanik: Sinus-Ton über Lautsprecher, niemand spricht → Transkript leer (Ton wird nicht Text, kein Systemaudio im Capture) | ✅ |
| 429-Backoff live (Gemini-Quota erschöpft): 3 Retries 2/4/8 s, Cap, Fallback, Log-Hinweise | ✅ wie spezifiziert |
| LaTeX-Regression Prosodie („das Ganze durch" → `\frac{x^2+1}{2}`), Klammern, Delimiter („Formel…Formelende") | ✅ (Lauf vom selben Tag, vor Quota-Erschöpfung: 7/7 exakt) |
| Integrationstest „Browservideo + Diktat + nur Sprache im Transkript" | ⚠ Mikrofon-Teil braucht den Nutzer: `--audio-selftest` mit laufendem Video ausführen |
