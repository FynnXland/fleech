"""Welches Erkennungsmodell: das allgemeine oder das deutsch nachtrainierte.

„Deutsch" ist `primeline/whisper-large-v3-turbo-german` — dasselbe Turbo-Modell,
auf deutschen Sprachdaten nachtrainiert (Test-WER 2,6 %). Gemessen an den
TTS-Aufnahmen (5–120 s): 4 statt 11 Fehler, und bei Rauschen hinter dem letzten
Wort erfand es keinen Schlusssatz (das allgemeine schrieb „Lass uns das Ganze
ansehen."). Satzzeichen und Großschreibung bleiben, Tempo und Größe gleich.

Die CTranslate2-Fassung von jimmymeister, weil sie ihren Tokenizer mitbringt.
Fehlt `tokenizer.json`, greift faster-whisper zum Tokenizer von whisper-tiny —
und der zählt die Sondertoken von v3 anders (ein Sprachtoken weniger). Mit einer
Fassung ohne Tokenizer liefe das Modell bei Freunden still falsch.
"""

STANDARD = "large-v3-turbo"
DEUTSCH = "jimmymeister/whisper-large-v3-turbo-german-ct2"


def modell_fuer(wahl: str, bisher: str) -> str:
    """Modellname für die Einstellung `wahl`.

    „standard" lässt ein in config.yaml eigens gesetztes Modell stehen (z. B.
    `medium` auf schwacher Hardware) — zurückgesetzt wird nur das deutsche."""
    if wahl == "deutsch":
        return DEUTSCH
    return STANDARD if bisher == DEUTSCH else bisher
