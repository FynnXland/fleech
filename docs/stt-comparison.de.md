# Spracherkennung: Modellvergleich und Safe-Word

Stand: 6.1.0 · Messungen vom Juli 2026 auf einer RTX 4070 mit Computerstimmen-Aufnahmen
(Microsoft Hedda, de-DE), sofern nicht anders angegeben. Code: `fleech/stt/`.

## large-v3-turbo gegen large-v3

| | large-v3-turbo (Vorgabe) | large-v3 |
|---|---|---|
| Warm-Latenz, 6 s Audio | **0,20 s** | 0,41 s |
| Download | ~1,6 GB | ~3 GB |
| Referenz-Transkript (sauberes TTS-Audio) | fehlerfrei | fehlerfrei |
| Safe-Word-Kandidaten (s. u.) | 3/4 perfekt, „Melone“ wackelt | 4/4 perfekt |
| „Redax“ | ✗ („Idax“) | ✗ („EDAX“/„IDAX“) |

**Einordnung:** Auf sauberem TTS-Audio sind beide Modelle fehlerfrei. Der Unterschied
zeigt sich erst bei schwierigem Material (echte Stimme, Nebengeräusche, Eigennamen);
large-v3 war im Test minimal robuster (Fall „Melone“). Auch seine 0,41 s sind für Diktat
unkritisch. Umstellen geht über eine eigene `config.yaml` im Benutzerordner
(`stt.model_size: large-v3`) und wirkt, solange unter Einstellungen → Advanced →
Spracherkennung „Standard“ gewählt ist. Ob es sich lohnt, zeigt nur echtes Diktat mit der
eigenen Stimme. Das Safe-Word-Problem löst large-v3 **nicht** (s. u.) — das war ein
Wort-Problem, kein Modell-Problem.

**Grafikspeicher:** Seit 5.15.1 rechnet die Erkennung auf der Grafikkarte mit
`int8_float16` statt `float16` — gemessen im Oktober 2026 rund 1,0 statt 2,1 GB für turbo,
gleich schnell und ohne mehr Fehler (`waehle_rechenart` in
`fleech/stt/faster_whisper_stt.py`). Ohne Grafikkarte läuft sie mit `int8` auf dem
Prozessor.

## Deutsch nachtrainiertes Modell

Seit 5.15.0 bietet Einstellungen → Advanced → Spracherkennung „Deutsch-optimiert“:
`jimmymeister/whisper-large-v3-turbo-german-ct2`, dasselbe Turbo-Modell auf deutsche
Sprachdaten nachtrainiert (`fleech/stt/modellwahl.py`). An TTS-Aufnahmen von 5 bis 120 s
(Oktober 2026) machte es zusammen 4 statt 11 Fehler und erfand bei Rauschen hinter dem letzten
Wort keinen Schlusssatz. Satzzeichen, Großschreibung, Tempo und Größe bleiben gleich;
einmaliger Download von 1,6 GB. Für englische Diktate bleibt „Standard“ die richtige Wahl.

## Safe-Word-Robustheit

Kriterien: mehrsilbig, vokalreich, keine verwechselbaren Plosive (b/d/g), und ein
**echtes Wort** — Whisper normalisiert Kunstwörter auf bekannte Wörter; genau das war
der Fehler „Redax“ → „Idax“/„Redux“. Getestet einzeln und in einem Befehlssatz, mit beiden
Modellen:

| Kandidat | turbo einzeln | turbo im Satz | v3 einzeln | v3 im Satz |
|---|---|---|---|---|
| **Kimono** (Vorgabe) | ✅ | ✅ | ✅ | ✅ |
| **Ananas** | ✅ | ✅ | ✅ | ✅ |
| **Salami** | ✅ | ✅ | ✅ | ✅ |
| Melone | ✗ („Meloone“) | ✅ | ✅ | ✅ |
| Redax (alt) | ✗ „Idax“ | ✗ „Idax“ | ✗ „EDAX“ | ✗ „IDAX“ |

„Kimono“ ist Vorgabe, weil es im echten Diktat am unwahrscheinlichsten vorkommt; „Ananas“
und „Salami“ sind gleich robust. Zusätzlich gibt Fleech der Erkennung das Safe-Word als
Hinweis mit (`initial_prompt`, „Signalwort: Kimono.“). Umstellen lässt es sich unter
Einstellungen → Ausgabe → „Safe-Word (Befehle)“, ohne Neustart. Die TTS-Stimme ist nicht
die eigene — die endgültige Wahl trifft das eigene Mikrofon.

## Historie: zwei Bereinigungsmodelle

Bis 3.5.0 verteilte Fleech die KI-Bereinigung nach Komplexität auf zwei Ollama-Modelle
(`qwen2.5:3b` für einfache, `qwen3.5:9b` für schwierige Diktate). Seit 3.5.0 läuft alles
über `gemma3:4b`; der Schalter „Adaptive Geschwindigkeit“ entfiel in 5.11.0. Die
Einstufung selbst besteht weiter (`classify_complexity` in `fleech/textfilter.py`): Kurze,
saubere Äußerungen (bis fünf Wörter, ohne Zahlen, Füll- und Korrekturwörter) gehen ohne
Modell durch, alles andere geht an das eine Modell — `cleanup` und `cleanup_fast` in
`config.yaml` zeigen auf dasselbe. Die Messwerte zur Modellwahl stehen als Kommentar in
`config.yaml`.

## Ausblick: Voxtral (bewusst nicht jetzt)

Voxtral (Mistral, Apache 2.0) schlug Whisper zum Zeitpunkt der Messung bei reiner
Genauigkeit und bietet natives Streaming. Das würde auch die Live-Vorschau in der Pille
vereinfachen (echtes schrittweises Dekodieren statt eines gleitenden Fensters, das jede
Sekunde neu dekodiert wird). Die Migration wäre aber ein eigenes Projekt: neues Serving,
anderes VRAM-Profil, keine faster-whisper-Schnittstelle. Der STT-Layer ist hinter
`STTEngine` (`fleech/stt/base.py`) abstrahiert — ein weiteres Backend käme hinzu, ohne
die Pipeline umzubauen.
