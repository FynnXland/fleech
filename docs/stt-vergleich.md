# STT-Vergleich & Trigger-Wort-Robustheit

Stand: 2026-07-05 · Messungen auf RTX 4070, TTS-Fixtures (Microsoft Hedda, de-DE)

## large-v3 vs. large-v3-turbo (4070)

| | large-v3-turbo (Default) | large-v3 |
|---|---|---|
| Warm-Latenz, 6 s Audio | **0,20 s** | 0,41 s |
| Download/VRAM | ~1,6 GB | ~3 GB |
| Referenz-Transkript (sauberes TTS-Audio) | fehlerfrei | fehlerfrei |
| Trigger-Kandidaten (s. u.) | 3/4 perfekt, „Melone" wackelt | 4/4 perfekt |
| „Redax" | ✗ („Idax") | ✗ („EDAX"/„IDAX") |

**Einordnung:** Auf sauberem TTS-Audio sind beide Modelle fehlerfrei — der
Genauigkeitsunterschied zeigt sich erst bei schwierigem Material (echte Stimme,
Nebengeräusche, Eigennamen); large-v3 war im Test minimal robuster (Melone-Fall).
Die Latenz von large-v3 (0,41 s warm) ist für Diktat immer noch völlig unkritisch.
**Empfehlung:** Umstellen ist eine Zeile (`stt.model_size: large-v3` in config.yaml)
— ob es sich für die eigene Stimme lohnt, lässt sich nur mit echtem Diktat
beurteilen. Beide Modelle sind jetzt lokal gecacht, A/B-Wechsel kostet nur den
Neustart. Wichtig: Das Trigger-Wort-Problem löst large-v3 NICHT (s. u.) — das war
ein Wort-Problem, kein Modell-Problem.

## Trigger-Wort-Robustheit (empirisch)

Kriterien: mehrsilbig, vokalreich, keine b/d/g-verwechselbaren Plosive, **echtes
Wort** (Whisper normalisiert Kunstwörter auf bekannte Wörter — genau das war der
„Redax"→„Idax/Redux"-Fehler). Getestet isoliert + im Befehlssatz, beide Modelle:

| Kandidat | turbo isoliert | turbo im Satz | v3 isoliert | v3 im Satz |
|---|---|---|---|---|
| **Kimono** (neuer Default) | ✅ | ✅ | ✅ | ✅ |
| **Ananas** | ✅ | ✅ | ✅ | ✅ |
| **Salami** | ✅ | ✅ | ✅ | ✅ |
| Melone | ✗ („Meloone") | ✅ | ✅ | ✅ |
| Redax (alt) | ✗ „Idax" | ✗ „Idax" | ✗ „EDAX" | ✗ „IDAX" |

„Kimono" ist Default (am unwahrscheinlichsten in echtem Diktat); „Ananas" und
„Salami" sind gleichwertig robust. **Mit echter Stimme durchprobieren:** Einstellungen
→ Ausgabe → „Safe-Word (Befehle)" — wirkt sofort, ohne Neustart. TTS-Stimme ≠ eigene
Stimme; die finale Wahl trifft das eigene Mikrofon.

## Adaptives Cleanup-Routing (Modellwahl nach Komplexität)

Statt jedes Diktat über das große `qwen3.5:9b` zu schicken, wählt Fleech das Modell
nach der Transkript-Komplexität (Signal ist der Text, nicht die Audiolänge — genauer):

| Stufe | Bedingung | Modell | Latenz (warm) |
|---|---|---|---|
| trivial | kurz, sauber, keine Marker/Zahlen | keins | sofort |
| simple | kurz–mittel, nur Füllwörter, keine Zahlen/Korrekturen | `qwen2.5:3b` | ~0,35 s |
| complex | Selbstkorrektur ODER Zahlen ODER > 24 Wörter | `qwen3.5:9b` | ~1–5 s |

Zahlen und Selbstkorrekturen sind die subtilsten Fälle (eine falsche Zahl ist schlimmer
als langsam) und gehen bewusst immer zum großen Modell.

**Modellwahl empirisch:** `qwen2.5:3b` (ältere, kleinere Qwen-Generation) hat als
einziger Kandidat die getunten Regeln gehalten — Injection-Abwehr (vorgelesener Prompt
wird transkribiert, nicht ausgeführt), Code-Switching (`refactoren` bleibt), Anredeform,
keine Halluzination. `llama3.2:3b` fiel durch: Meta-Kommentare („Ich würde den Text wie
folgt bereinigen:"), Eindeutschung (`refaktorieren`), erfundener Inhalt, Personenwechsel.

**Sicherheitsnetze greifen auf beiden Pfaden:** der Grounding-Guard (gegen
Prompt-Ausführung) und die Anführungszeichen-Bereinigung laufen modellunabhängig. Fällt
das kleine Modell aus, wird automatisch das große versucht (Qualität vor Tempo).

**VRAM (RTX 4070, 12 GB):** `qwen3.5:9b` (5,6 GB) + `qwen2.5:3b` (2,2 GB) + Whisper-turbo
≈ 10,5 GB — beide bleiben warm. Wer VRAM braucht (Spiel): Einstellungen → Advanced →
„Adaptive Geschwindigkeit" aus (nur großes Modell) oder GPU-Schalter für Whisper.

## Ausblick: Voxtral (separates Thema, bewusst nicht jetzt)

Voxtral (Mistral, Apache 2.0) schlägt Whisper aktuell bei reiner Genauigkeit und
bietet natives Streaming — Letzteres würde auch das M4-Live-Overlay vereinfachen
(echtes inkrementelles Decoding statt Sliding-Window-Redecode). Die Migration ist
aber ein eigener Aufwand (neues Serving, VRAM-Profil, kein faster-whisper-API).
Gute Nachricht: Der STT-Layer ist hinter `STTEngine` (fleech/stt/base.py)
abstrahiert — ein `voxtral_stt.py`-Backend wäre additiv, ohne Umbau der Pipeline.
Vorerst: nicht jetzt, dokumentiert als Kandidat.
