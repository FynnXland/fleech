"""Schlanke Fassung eines lokalen Sprachmodells: dasselbe Modell ohne Bildteil.

gemma3:4b bringt eine Bildverarbeitung mit (841 MB der 3,3 GB), die Fleech nie
benutzt — es schickt nur Text. Ollama laedt sie trotzdem jedes Mal in den
Speicher. Diese Datei baut daraus `gemma3:4b-text`: Sie liest Ollamas eigene
Modelldatei (GGUF), laesst die Bild-Tensoren und ihre Schluessel weg und meldet
den Rest ueber Ollamas API als neues Modell an. Die Textgewichte werden Byte fuer
Byte uebernommen — keine neue Quantisierung, also keine andere Qualitaet.

Gemessen am 2026-10-22: Datei 2,5 statt 3,3 GB, ohne Grafikkarte 3,3 statt
4,1 GB Arbeitsspeicher; an 76 Diktaten mit Sollfassung gleich wortgetreu
(65 Ausgaben wortgleich, der Rest gleich gut). Eine fertige Text-Fassung aus
fremder Quelle (unsloth, andere Quantisierung) formulierte dagegen deutlich
schlechter um — deshalb wird das vorhandene Modell umgebaut statt ein anderes
geladen. Kein Zusatzpaket, kein zusaetzlicher Download.

Grenzen: Ollama muss auf diesem Rechner laufen und sein Modellordner lesbar
sein. Klappt der Umbau nicht, nutzt Fleech das Original und sagt, warum.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path

from ..i18n import dezimal, tr

log = logging.getLogger(__name__)

# Schlanke Fassung → Original. Nur gemessene Paare: Ein anderes Modell kann seinen
# Bildteil anders ablegen, und ungeprueft umgebaut waere es ein Ratespiel.
VARIANTEN = {"gemma3:4b-text": "gemma3:4b"}
GROESSE_GB = {"gemma3:4b-text": 2.5}
ERSPARNIS_GB = {"gemma3:4b-text": 0.8}

_GGUF_ALIGNMENT = 32
_BILD_TENSOREN = ("v.", "mm.")
# Merkt fehlgeschlagene Umbauten fuer diese Sitzung: Ein Ordner, der nicht lesbar
# ist, wird es beim naechsten Warmhalten auch nicht — kein Dauerversuch, keine
# Meldungsflut.
_GESCHEITERT: dict = {}


class SchlankFehler(Exception):
    """Warum der Umbau nicht ging — ein Satz fuer Menschen."""


def quelle_von(modell: str) -> str:
    """'gemma3:4b-text' → 'gemma3:4b'; '' fuer alles, was keine schlanke Fassung ist."""
    return VARIANTEN.get(str(modell or "").strip(), "")


def schlanke_fassung(modell: str) -> str:
    """'gemma3:4b' → 'gemma3:4b-text'; '' wenn es keine gemessene gibt."""
    for schlank, quelle in VARIANTEN.items():
        if quelle == str(modell or "").strip():
            return schlank
    return ""


def grund(modell: str) -> str:
    """Warum der Umbau in dieser Sitzung scheiterte ('' = nicht gescheitert)."""
    return _GESCHEITERT.get(modell, "")


def bevorzugt(modell: str) -> str:
    """Die schlanke Fassung, wenn es eine gibt, sonst das Modell selbst."""
    return schlanke_fassung(modell) or modell


def _gb(wert: float) -> str:
    # Geschuetztes Leerzeichen: Die Hinweis-Blase bricht sonst „0,8 | GB" um.
    return dezimal(wert, 1) + " GB"


def erklaerung(schlank: str) -> str:
    """Der Satz, der dem Nutzer sagt, was diese Fassung ist."""
    quelle = quelle_von(schlank)
    ersparnis = ERSPARNIS_GB.get(schlank)
    weniger = (tr("rund {gb} weniger Speicher", gb=_gb(ersparnis)) if ersparnis
               else tr("weniger Speicher"))
    return tr("Dieselbe KI wie {quelle}, nur ohne den Bildteil, den Fleech nie braucht: "
              "{weniger}, an echten Diktaten gemessen gleich wortgetreu. Fleech baut "
              "sie auf diesem Rechner aus {quelle}.", quelle=quelle, weniger=weniger)


def ankuendigung(schlank: str, quelle_da: bool) -> str:
    """Was gleich passiert — bevor es passiert, nicht erst hinterher."""
    quelle = quelle_von(schlank)
    ersparnis = ERSPARNIS_GB.get(schlank)
    warum = ", " + tr("spart rund {gb} Speicher", gb=_gb(ersparnis)) if ersparnis else ""
    if quelle_da:
        return tr("Fleech verschlankt das Sprachmodell: {quelle} ohne den Bildteil, den es "
                  "nie braucht{warum}. Dauert etwa 20 Sekunden, ohne Download; bis dahin "
                  "bereinigt {quelle} weiter.", quelle=quelle, warum=warum)
    return tr("Fleech lädt {quelle} und baut daraus die schlanke Fassung {schlank} "
              "(ohne Bildteil{warum}). Das Original wird danach wieder entfernt.",
              quelle=quelle, schlank=schlank, warum=warum)


# -- Ollamas Modellablage ---------------------------------------------------------------


def _modellordner_kandidaten() -> list:
    """Wo Ollama seine Modelle ablegt: eigene Angabe, Benutzerordner, Systemdienst."""
    kandidaten = []
    eigen = os.environ.get("OLLAMA_MODELS", "").strip()
    if eigen:
        kandidaten.append(Path(eigen))
    kandidaten.append(Path.home() / ".ollama" / "models")
    kandidaten += [Path("/usr/share/ollama/.ollama/models"),
                   Path("/var/lib/ollama/.ollama/models")]
    return kandidaten


def _manifest_teil(name: str) -> Path:
    """'gemma3:4b' → registry.ollama.ai/library/gemma3/4b."""
    repo, _, tag = name.partition(":")
    if "/" not in repo:
        repo = f"library/{repo}"
    return Path("manifests") / "registry.ollama.ai" / repo / (tag or "latest")


def finde_ablage(name: str) -> tuple:
    """(Modellordner, Manifest) des Originals — oder SchlankFehler."""
    for ordner in _modellordner_kandidaten():
        datei = ordner / _manifest_teil(name)
        try:
            if datei.is_file():
                return ordner, json.loads(datei.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SchlankFehler(tr("Ollamas Modellordner ist nicht lesbar ({fehler})",
                                    fehler=exc)) from exc
    raise SchlankFehler(tr("Ollamas Ablage von {name} wurde nicht gefunden", name=name))


def _schicht(ordner: Path, manifest: dict, art: str) -> Path | None:
    for schicht in manifest.get("layers") or []:
        if str(schicht.get("mediaType", "")).endswith(art):
            return ordner / "blobs" / str(schicht.get("digest", "")).replace(":", "-")
    return None


# -- GGUF lesen und ohne Bildteil neu zusammensetzen --------------------------------------

_FESTE_GROESSE = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}


class _Leser:
    def __init__(self, datei):
        self.f = datei

    def u32(self) -> int:
        return struct.unpack("<I", self.f.read(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.f.read(8))[0]

    def text(self) -> str:
        return self.f.read(self.u64()).decode("utf-8")

    def wert(self, typ: int):
        """Liest einen Wert; Zahlen-Arrays werden nur uebersprungen."""
        if typ == 8:
            return self.text()
        if typ == 9:
            innen, anzahl = self.u32(), self.u64()
            if innen in (8, 9):
                return [self.wert(innen) for _ in range(anzahl)]
            self.f.seek(_FESTE_GROESSE[innen] * anzahl, 1)
            return None
        roh = self.f.read(_FESTE_GROESSE[typ])
        return int.from_bytes(roh, "little") if typ in (0, 2, 4, 10) else roh


def lies_kopf(pfad: Path) -> dict:
    """Schluessel (als Rohbytes), Tensoren und Datenbeginn einer GGUF-Datei."""
    with open(pfad, "rb") as datei:
        lies = _Leser(datei)
        if datei.read(4) != b"GGUF":
            raise SchlankFehler(tr("die Modelldatei ist kein GGUF"))
        version, n_tensoren, n_schluessel = lies.u32(), lies.u64(), lies.u64()
        schluessel = []
        for _ in range(n_schluessel):
            start = datei.tell()
            name, typ = lies.text(), lies.u32()
            wert = lies.wert(typ)
            ende = datei.tell()
            datei.seek(start)
            schluessel.append((name, wert, datei.read(ende - start)))
        tensoren = []
        for _ in range(n_tensoren):
            name = lies.text()
            dims = [lies.u64() for _ in range(lies.u32())]
            typ, versatz = lies.u32(), lies.u64()
            tensoren.append({"name": name, "dims": dims, "typ": typ, "versatz": versatz})
        kopf_ende = datei.tell()
    ausrichtung = next((w for n, w, _ in schluessel if n == "general.alignment"
                        and isinstance(w, int)), _GGUF_ALIGNMENT)
    daten = (kopf_ende + ausrichtung - 1) // ausrichtung * ausrichtung
    groesse = Path(pfad).stat().st_size
    reihe = sorted(tensoren, key=lambda t: t["versatz"])
    for i, t in enumerate(reihe):
        naechster = reihe[i + 1]["versatz"] if i + 1 < len(reihe) else groesse - daten
        t["laenge"] = naechster - t["versatz"]
    return {"version": version, "schluessel": schluessel, "tensoren": tensoren,
            "daten": daten, "ausrichtung": ausrichtung}


def _ist_bildschluessel(name: str, architektur: str) -> bool:
    return name.startswith((f"{architektur}.vision.", f"{architektur}.mm."))


def ohne_bildteil(kopf: dict) -> tuple:
    """(neuer Kopf als Bytes, [(Quell-Offset, Laenge), …]) — die Textgewichte in
    ihrer urspruenglichen Reihenfolge, jeder Abschnitt samt seiner Ausrichtung."""
    architektur = next((w for n, w, _ in kopf["schluessel"]
                        if n == "general.architecture"), "")
    tensoren = [t for t in kopf["tensoren"] if not t["name"].startswith(_BILD_TENSOREN)]
    schluessel = [s for s in kopf["schluessel"]
                  if not _ist_bildschluessel(s[0], architektur)]
    if len(tensoren) == len(kopf["tensoren"]):
        raise SchlankFehler(tr("das Modell hat keinen Bildteil, den man entfernen könnte"))

    def text(t: str) -> bytes:
        roh = t.encode("utf-8")
        return struct.pack("<Q", len(roh)) + roh

    neu = b"GGUF" + struct.pack("<IQQ", kopf["version"], len(tensoren), len(schluessel))
    neu += b"".join(roh for _, _, roh in schluessel)
    versatz, neue_lage, abschnitte = 0, {}, []
    for t in sorted(tensoren, key=lambda t: t["versatz"]):
        neue_lage[t["name"]] = versatz
        versatz += t["laenge"]
        abschnitte.append((kopf["daten"] + t["versatz"], t["laenge"]))
    for t in tensoren:
        neu += text(t["name"]) + struct.pack("<I", len(t["dims"]))
        neu += b"".join(struct.pack("<Q", d) for d in t["dims"])
        neu += struct.pack("<IQ", t["typ"], neue_lage[t["name"]])
    neu += b"\0" * (-len(neu) % kopf["ausrichtung"])
    return neu, abschnitte


def datenstrom(pfad: Path, kopf: bytes, abschnitte: list, stueck: int = 8 << 20):
    """Die neue Datei als Folge von Bytes — ohne sie auf die Platte zu schreiben."""
    yield kopf
    with open(pfad, "rb") as datei:
        for start, laenge in abschnitte:
            datei.seek(start)
            while laenge > 0:
                teil = datei.read(min(laenge, stueck))
                if not teil:
                    raise SchlankFehler(tr("die Modelldatei endet zu früh"))
                laenge -= len(teil)
                yield teil


# -- Bauen und besorgen ------------------------------------------------------------------


def _anfrage(url: str, daten=None, methode: str = "POST", kopf=None,
             timeout: float = 600.0):
    import urllib.request

    anfrage = urllib.request.Request(url, data=daten, method=methode,
                                     headers=kopf or {"Content-Type": "application/json"})
    return urllib.request.urlopen(anfrage, timeout=timeout)


def baue(base_url: str, schlank: str, on_prozent=None) -> None:
    """Die schlanke Fassung aus dem installierten Original bauen (blockiert)."""
    import urllib.error

    from .client import ollama_root

    quelle = quelle_von(schlank)
    if not quelle:
        raise SchlankFehler(tr("für {schlank} kennt Fleech keine schlanke Fassung", schlank=schlank))
    ordner, manifest = finde_ablage(quelle)
    modelldatei = _schicht(ordner, manifest, "image.model")
    if modelldatei is None or not modelldatei.is_file():
        raise SchlankFehler(tr("die Modelldatei von {quelle} fehlt", quelle=quelle))
    kopf, abschnitte = ohne_bildteil(lies_kopf(modelldatei))
    gesamt = len(kopf) + sum(laenge for _, laenge in abschnitte)
    try:
        frei = shutil.disk_usage(ordner).free
    except OSError:
        frei = None
    if frei is not None and frei < gesamt + (512 << 20):
        raise SchlankFehler(tr("auf der Platte sind nur {frei} frei, gebraucht werden {noetig}",
                               frei=_gb(frei / 1e9), noetig=_gb(gesamt / 1e9)))

    def melde(fertig: int, phase: int) -> None:
        if on_prozent:
            on_prozent(min(99, int((phase * gesamt + fertig) * 50 / gesamt)))

    pruefsumme, fertig = hashlib.sha256(), 0
    for teil in datenstrom(modelldatei, kopf, abschnitte):
        pruefsumme.update(teil)
        fertig += len(teil)
        melde(fertig, 0)
    digest = "sha256:" + pruefsumme.hexdigest()
    wurzel = ollama_root(base_url)
    try:
        _anfrage(f"{wurzel}/api/blobs/{digest}", methode="HEAD", timeout=30).close()
        vorhanden = True
    except urllib.error.HTTPError:
        vorhanden = False
    if not vorhanden:
        def strom():
            gesendet = 0
            for teil in datenstrom(modelldatei, kopf, abschnitte):
                gesendet += len(teil)
                melde(gesendet, 1)
                yield teil

        _anfrage(f"{wurzel}/api/blobs/{digest}", strom(),
                 kopf={"Content-Length": str(gesamt),
                       "Content-Type": "application/octet-stream"}).close()

    def schicht_text(art: str) -> str:
        pfad = _schicht(ordner, manifest, art)
        return pfad.read_text(encoding="utf-8") if pfad and pfad.is_file() else ""

    auftrag = {"model": schlank, "stream": False,
               "files": {schlank.replace(":", "-") + ".gguf": digest}}
    for feld, art in (("template", "image.template"), ("license", "image.license")):
        if schicht_text(art):
            auftrag[feld] = schicht_text(art)
    if schicht_text("image.params"):
        auftrag["parameters"] = json.loads(schicht_text("image.params"))
    with _anfrage(f"{wurzel}/api/create", json.dumps(auftrag).encode("utf-8")) as antwort:
        ergebnis = json.loads(antwort.read() or b"{}")
    if ergebnis.get("status") != "success":
        raise SchlankFehler(tr("Ollama hat das Modell nicht angelegt ({fehler})",
                               fehler=ergebnis.get("error") or ergebnis))
    if on_prozent:
        on_prozent(100)
    log.info("Schlanke Fassung %s aus %s gebaut (%.1f GB).", schlank, quelle, gesamt / 1e9)


def entferne(base_url: str, modell: str) -> bool:
    """Ein Modell aus Ollama loeschen (`/api/delete`). False bei Fehler."""
    from .client import ollama_root

    try:
        _anfrage(f"{ollama_root(base_url)}/api/delete",
                 json.dumps({"model": modell}).encode("utf-8"), methode="DELETE",
                 timeout=60).close()
        return True
    except Exception as exc:
        log.warning("Modell %s liess sich nicht entfernen: %s", modell, exc)
        return False


@dataclass
class Ergebnis:
    """modell: was jetzt laeuft ('' = nichts besorgt). hinweis: Satz fuer den Nutzer."""

    modell: str
    hinweis: str = ""
    verschlankt: bool = False


def besorge(base_url: str, modell: str, on_phase=None, on_bytes=None,
            on_prozent=None) -> Ergebnis:
    """Ein fehlendes Modell besorgen — die schlanke Fassung baut Fleech selbst.

    Normales Modell: aus der Ollama-Bibliothek laden. Schlanke Fassung: das
    Original laden, falls es fehlt, daraus bauen und ein eben dafuer geladenes
    Original wieder entfernen (es lag vorher nicht da, also braucht es niemand).
    Ein schon vorhandenes Original bleibt — vielleicht nutzt es ein anderes
    Programm. Geht der Umbau schief, laeuft das Original weiter.
    """
    from .client import ollama_installed_models, ollama_pull

    def phase(text: str) -> None:
        if on_phase:
            on_phase(text)

    quelle = quelle_von(modell)
    if not quelle:
        phase(tr("wird geladen"))
        return Ergebnis(modell if ollama_pull(base_url, modell, on_bytes=on_bytes) else "")
    if modell in _GESCHEITERT:
        return Ergebnis(quelle)
    geholt = False
    if quelle not in ollama_installed_models(base_url):
        phase(tr("lädt {quelle}", quelle=quelle))
        if not ollama_pull(base_url, quelle, on_bytes=on_bytes):
            return Ergebnis("")
        geholt = True
    phase(tr("entfernt den Bildteil"))
    try:
        baue(base_url, modell, on_prozent=on_prozent)
    except Exception as exc:
        grund = str(exc) if isinstance(exc, SchlankFehler) else tr("Fehler: {fehler}", fehler=exc)
        _GESCHEITERT[modell] = grund
        log.warning("Schlanke Fassung %s nicht gebaut (%s) — nutze %s.", modell, grund, quelle)
        return Ergebnis(quelle, tr("Fleech konnte die schlanke Fassung {modell} nicht bauen "
                                   "({grund}). Es nutzt deshalb {quelle} — gleich gut, "
                                   "braucht aber mehr Speicher.",
                                   modell=modell, grund=grund, quelle=quelle))
    ersparnis = ERSPARNIS_GB.get(modell)
    if ersparnis:
        satz = tr("Sprachmodell verschlankt: Fleech nutzt jetzt {modell}, dieselbe KI wie "
                  "{quelle} ohne den Bildteil, den Fleech nie braucht — rund {gb} weniger "
                  "Speicher.", modell=modell, quelle=quelle, gb=_gb(ersparnis))
    else:
        satz = tr("Sprachmodell verschlankt: Fleech nutzt jetzt {modell}, dieselbe KI wie "
                  "{quelle} ohne den Bildteil, den Fleech nie braucht.",
                  modell=modell, quelle=quelle)
    if geholt and entferne(base_url, quelle):
        satz += " " + tr("Das dafür geladene {quelle} ist wieder entfernt.", quelle=quelle)
    elif not geholt:
        satz += " " + tr("Das Original {quelle} bleibt installiert; brauchst du es nicht, "
                         "entfernst du es mit „ollama rm {quelle}“.", quelle=quelle)
    return Ergebnis(modell, satz, verschlankt=True)
