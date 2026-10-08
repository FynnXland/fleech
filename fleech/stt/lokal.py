"""Whisper-Modelle nur von der Platte laden — ohne Hugging Face zu fragen.

faster-whisper ruft beim Erzeugen eines `WhisperModel` `snapshot_download` mit
`local_files_only=False` auf. Dann fragt huggingface_hub bei JEDEM Laden per
`repo_info` nach, ob sich das Modell geaendert hat, und laedt gegebenenfalls
nach — also bei jedem Start, jedem Modellwechsel, jedem Neuladen nach einem
CUDA-Fehler. Fleech verspricht dagegen: ins Netz nur fuer Einrichtung,
Update-Pruefung, das bewusst gewaehlte Deutsch-Modell und den gewaehlten
Cloud-Anbieter.

Deshalb ist DIES die einzige Stelle, die ein `WhisperModel` erzeugt
(`tests/test_stt_lokal.py` wacht darueber): Der Modellname wird hier offline
zum Ordner im Cache aufgeloest, und faster-whisper bekommt nur noch den Ordner —
damit gibt es fuer die Bibliothek nichts mehr nachzufragen. Fehlt das Modell,
gibt es `ModellFehlt` statt eines stillen Downloads. Herunterladen darf nur
`provisioning.ensure_whisper`: die Einrichtung, der Wechsel auf das
Deutsch-Modell und das Nachholen eines fehlenden Modells.
"""

from __future__ import annotations

import os

# Ohne diese beiden startet CTranslate2 nicht. Bewusst geprueft, statt dem
# Cache zu glauben: Ein abgebrochener Download hinterlaesst einen Ordner mit
# den kleinen Dateien, aber ohne `model.bin` (huggingface_hub benennt sie erst
# um, wenn sie vollstaendig ist). Frueher reparierte die Nachfrage beim Laden
# das still — ohne Nachfrage muss es die Einrichtung tun, und die erfaehrt es
# nur, wenn „unvollstaendig" als „fehlt" zaehlt.
PFLICHTDATEIEN = ("model.bin", "config.json")


class ModellFehlt(RuntimeError):
    """Das Erkennungsmodell liegt nicht (vollstaendig) im lokalen Cache.

    Kein Grafikkarten-Problem: Wer das faengt, darf NICHT auf den Prozessor
    ausweichen — dort fehlt das Modell genauso."""

    def __init__(self, modell: str):
        super().__init__(f"Erkennungsmodell {modell} liegt nicht lokal vor — "
                         f"es muss erst eingerichtet (heruntergeladen) werden.")
        self.modell = modell


def modellordner(modell: str) -> str:
    """Ordner des vollstaendig geladenen Modells — ohne Netz.

    `modell` ist ein Name aus faster-whisper (`large-v3-turbo`), eine Hub-ID
    (`jimmymeister/…`) oder ein Ordnerpfad. Wirft `ModellFehlt`, wenn es nicht
    oder nur halb im Cache liegt; einen unbekannten Namen meldet faster-whisper
    selbst (`ValueError`) — das ist ein Konfigurationsfehler, kein fehlendes Modell.
    """
    if os.path.isdir(modell):
        return modell
    from faster_whisper.utils import download_model
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        ordner = download_model(modell, local_files_only=True)
    except LocalEntryNotFoundError as exc:
        raise ModellFehlt(modell) from exc
    if not all(os.path.isfile(os.path.join(ordner, d)) for d in PFLICHTDATEIEN):
        raise ModellFehlt(modell)
    return ordner


def lade_whisper(modell: str, **optionen):
    """`WhisperModel` aus dem lokalen Cache bauen.

    `optionen` gehen unveraendert an `WhisperModel` (device, compute_type …).
    Wirft `ModellFehlt` wie `modellordner`."""
    from faster_whisper import WhisperModel

    return WhisperModel(modellordner(modell), **optionen)
