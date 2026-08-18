"""Der Schwanz ohne Ton — erfundene Segmente hinter dem letzten echten Wort.

Whisper haengt bei langen Diktaten mit `initial_prompt` Floskeln ans Ende:
„Vielen Dank. Vielen Dank.", „Bis zum naechsten Mal.", „Untertitelung des ZDF".
Real getroffen hat es 7 von 1419 Diktaten im Verlauf — selten, aber immer am
Ende, wo der Nutzer es zuletzt liest.

Warum ein eigener Guard noetig ist:

- **`no_speech_prob` taugt nicht.** In der Messung (2367 Segmente aus rund 120
  Laeufen) stand der Wert bei ALLEN Segmenten auf exakt 0,0000 — echt wie
  erfunden. `_keep_segment` in `faster_whisper_stt.py` ist hier also blind:
  0 Treffer von 420 halluzinierten Segmenten.
- **Der Wiederholungs-Guard reicht nicht.** `collapse_trailing_repetitions`
  kuerzt „Vielen Dank."x4 auf EINE Nennung — und genau dieses eine Segment
  bleibt dann stehen. Beide Guards braucht es, keiner ersetzt den anderen.
- **Der Ton trennt sauber.** Kein einziges der 420 erfundenen Segmente hatte
  mehr als RMS 0,00194 hinter sich; jedes echte lag bei 0,06–0,11. Und 343 der
  Segmente begannen sogar NACH dem Ende des Audios — physikalisch unmoeglicher
  Text.

Audio-Fachlogik, deshalb nicht in `textfilter.py` (das sind Textguards und steht
dicht an seiner Zeilengrenze) und nicht in `faster_whisper_stt.py` (dort steht
das Backend, nicht die Regel).
"""

from __future__ import annotations

import numpy as np

# RMS, unter dem im Segmentfenster „kein Ton" gilt. Dieselbe Zahl wie
# KEIN_TON_SCHWELLE der Overlay-Pille (fleech/ui/overlaypille/konstanten.py) —
# bewusst NICHT von dort importiert, der Kern zeigt nie in die Oberflaeche; ein
# Test haelt beide gleich (tests/test_nachlauf.py).
#
# Belegt in zwei Richtungen: Am Geraet (Scarlett Solo) loeste die Kein-Ton-Wache
# genau dort aus, wo Whisper selbst aufgab. Und in der Halluzinations-Messung
# begann der Fehlalarm erst UNTER 0,002 — ein kuenstlich auf RMS 0,00186
# heruntergerechneter echter Satz fiel, alles ab 0,00278 blieb heil.
KEIN_TON_RMS = 0.002


def _rms(audio: np.ndarray, start_s: float, end_s: float, samplerate: int) -> float:
    """Lautstaerke des Original-Audios im Fenster [start_s, end_s].

    Arbeitet auf einer Sicht (Slice), nicht auf einer Kopie — der Guard laeuft
    im Aufnahmeweg, und das Audio ist bei langen Diktaten mehrere Megabyte."""
    a = max(0, int(start_s * samplerate))
    b = min(audio.size, int(round(end_s * samplerate)))
    if b <= a:
        return 0.0  # leeres oder negatives Fenster = kein Ton
    fenster = audio[a:b]
    return float(np.sqrt(np.mean(np.square(fenster, dtype=np.float64))))


def streiche_tonlosen_schwanz(
    segmente, audio: np.ndarray, samplerate: int = 16000,
    schwelle: float = KEIN_TON_RMS,
) -> tuple[list, list]:
    """Segmente vom ENDE her verwerfen, solange dahinter kein Ton liegt.

    `segmente` sind Whisper-Segmente (alles mit `.start`, `.end` in Sekunden auf
    der Original-Zeitachse und `.text`); `audio` das 16-kHz-Mono-Audio, aus dem
    sie stammen. Rueckgabe: (behalten, verworfen), beide in Originalreihenfolge.

    Drei Sicherungen, damit nie echte Sprache faellt:

    1. **Nur vom Ende her** — beim ersten Segment MIT Ton wird abgebrochen. Mitten
       im Text wird nichts geschnitten (dort ist die Stille eine Sprechpause).
    2. **Nie das letzte verbleibende Segment** — beim Fluester-Diktat lieber ein
       fragwuerdiger Satz als gar nichts.
    3. **Segmente ohne Zeiten gelten als mit Ton** — was wir nicht pruefen
       koennen, verwerfen wir nicht.
    """
    liste = list(segmente)
    if len(liste) <= 1:
        return liste, []
    dauer_s = audio.size / samplerate if samplerate else 0.0

    schnitt = len(liste)
    # Bei 1 aufhoeren: das erste Segment bleibt in jedem Fall stehen.
    for i in range(len(liste) - 1, 0, -1):
        seg = liste[i]
        start = getattr(seg, "start", None)
        ende = getattr(seg, "end", None)
        if start is None or ende is None:
            break
        # Jenseits der Audiodauer begonnen: Whisper hat ueber das Material hinaus
        # weitergeschrieben. Kann kein gesprochenes Wort sein.
        if start >= dauer_s:
            schnitt = i
            continue
        if _rms(audio, start, ende, samplerate) >= schwelle:
            break
        schnitt = i

    return liste[:schnitt], liste[schnitt:]


def lautester_pegel(segmente, audio: np.ndarray, samplerate: int = 16000) -> float:
    """Hoechstes Segment-RMS einer Auswahl — fuer die Log-Zeile des Verwerfens."""
    pegel = [_rms(audio, seg.start, seg.end, samplerate) for seg in segmente
             if getattr(seg, "start", None) is not None
             and getattr(seg, "end", None) is not None]
    return max(pegel) if pegel else 0.0
