"""Gibt es ein neueres Modell? — der Modellberater.

Die naheliegende Idee waere, die KI selbst zu fragen. Das traegt nicht: Ein Modell
kennt nur, was bis zu seinem Trainingsende existierte — gemma3 weiss nichts von
gemma4, und ein Cloud-Modell weiss nicht, was sein Anbieter gestern freigeschaltet
hat. Die Antwort waere geraten. Gefragt werden deshalb die Stellen, die es wissen:

  Cloud   — die Modellliste des Anbieters (`/models`, mit dem eigenen Schluessel).
            Neuer heisst: dieselbe Familie und Preisstufe („mini", „haiku",
            „flash" …) mit hoeherer Versionsnummer. Fehlt das eigene Modell in der
            Liste, hat der Anbieter es abgeschaltet — auch das ist ein Befund.
  Ollama  — die Registry (`registry.ollama.ai`): gibt es die naechste Generation
            der Familie (gemma3 → gemma4)? Dazu die Groesse, denn „neuer" ist bei
            lokalen Modellen oft „groesser".
  Beide   — der Katalog `fleech/llm/modelle.json`: was Fleech an echten Diktaten
            gemessen hat und empfiehlt. Er wird von GitHub gelesen, damit eine neue
            Empfehlung alle Installationen ohne Update erreicht; die mitgelieferte
            Kopie ist der Rueckfall, wenn kein Netz da ist.

„Neuer" heisst nicht „besser fuer Diktate" (gemma4:e4b ist doppelt so gross wie
gemma3:4b). Deshalb schlaegt Fleech vor und stellt nie selbst um.

Ohne Qt — die Anzeige liegt in `ui/settings/ki.py`, der Wochentakt in
`ui/desktopapp/modellpruefung.py`.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .providers import AUS, EIGENER, OLLAMA, anbieter, modelle_abrufen

log = logging.getLogger(__name__)

KATALOG_URL = ("https://raw.githubusercontent.com/FynnXland/fleech/main/"
               "fleech/llm/modelle.json")
REGISTRY = "https://registry.ollama.ai/v2/library"
_MITGELIEFERT = Path(__file__).with_name("modelle.json")
_CACHE_NAME = "modelle-katalog.json"
# Wie viel groesser darf eine neue Generation sein, um noch vorgeschlagen zu
# werden? gemma3:4b → gemma4 (3,3 → 6,6 GB) ja, ein 3B-Modell → 67 GB nein.
MAX_WACHSTUM = 2.5

# Vorschau-Modelle verschwinden oft nach Wochen wieder — als Vorschlag ungeeignet.
_VORSCHAU = {"preview", "exp", "experimental", "beta", "alpha"}
# Bedeutungslos fuer die Familie: „latest" ist ein Zeiger, kein Modell.
_RAUSCHEN = {"latest"} | _VORSCHAU


@dataclass(frozen=True)
class KatalogModell:
    modell: str
    groesse_gb: float = 0.0
    notiz: str = ""
    empfohlen: bool = False
    gemessen: bool = False
    neu: bool = False
    ersetzt: tuple = ()


@dataclass(frozen=True)
class Befund:
    """Ein Vorschlag: statt `aktuell` lieber `neuer` — und warum, in einem Satz."""

    anbieter: str
    aktuell: str
    neuer: str
    grund: str
    gemessen: bool = False       # vom Katalog empfohlen, also an Diktaten geprueft


# -- Katalog ---------------------------------------------------------------------


def _gueltig(daten) -> bool:
    return isinstance(daten, dict) and isinstance(daten.get("ollama"), list)


def mitgelieferter_katalog() -> dict:
    try:
        daten = json.loads(_MITGELIEFERT.read_text(encoding="utf-8"))
        return daten if _gueltig(daten) else {}
    except Exception:
        log.warning("Mitgelieferter Modellkatalog nicht lesbar.", exc_info=True)
        return {}


def katalog(cache_ordner: Path | None = None, netz: bool = False,
            timeout: float = 6.0) -> dict:
    """Der aktuellste erreichbare Katalog: GitHub → Zwischenspeicher → mitgeliefert.

    `netz=False` ruft nichts ab (Oberflaeche beim Aufbau, Tests); der zuletzt
    geladene Stand im Zwischenspeicher gilt trotzdem.
    """
    cache = Path(cache_ordner) / _CACHE_NAME if cache_ordner else None
    if netz:
        try:
            with urllib.request.urlopen(KATALOG_URL, timeout=timeout) as antwort:
                daten = json.loads(antwort.read())
            if _gueltig(daten):
                if cache is not None:
                    try:
                        cache.parent.mkdir(parents=True, exist_ok=True)
                        cache.write_text(json.dumps(daten, ensure_ascii=False),
                                         encoding="utf-8")
                    except OSError:
                        log.debug("Modellkatalog nicht zwischenspeicherbar.",
                                  exc_info=True)
                return daten
        except Exception as exc:
            log.info("Modellkatalog nicht von GitHub ladbar (%s) — nehme den "
                     "letzten Stand.", exc)
    if cache is not None and cache.is_file():
        try:
            daten = json.loads(cache.read_text(encoding="utf-8"))
            if _gueltig(daten):
                return daten
        except Exception:
            log.debug("Zwischengespeicherter Modellkatalog unlesbar.", exc_info=True)
    return mitgelieferter_katalog()


def ollama_modelle(daten: dict) -> list:
    """Die lokalen Modelle des Katalogs, in seiner Reihenfolge."""
    raus = []
    for roh in (daten or {}).get("ollama") or []:
        if not isinstance(roh, dict) or not roh.get("modell"):
            continue
        raus.append(KatalogModell(
            modell=str(roh["modell"]), groesse_gb=float(roh.get("groesse_gb") or 0),
            notiz=str(roh.get("notiz") or ""), empfohlen=bool(roh.get("empfohlen")),
            gemessen=bool(roh.get("gemessen")), neu=bool(roh.get("neu")),
            ersetzt=tuple(str(x) for x in roh.get("ersetzt") or ()),
        ))
    return raus


def empfohlenes_modell(anbieter_id: str, daten: dict) -> str:
    """Was Fleech fuer diesen Anbieter vorschlaegt (Katalog vor eingebautem Wert)."""
    eintrag = anbieter(anbieter_id)
    if eintrag.id == OLLAMA:
        for m in ollama_modelle(daten):
            if m.empfohlen:
                return m.modell
        return eintrag.modell
    wahl = ((daten or {}).get("cloud") or {}).get(eintrag.id)
    return str(wahl) if wahl else eintrag.modell


# -- Versionen vergleichen ----------------------------------------------------------


def zerlege(name: str) -> tuple:
    """Modellname → (Familie, Version, Vorschau).

    'claude-haiku-4-5-20251001' → ({'claude', 'haiku'}, (4, 5), False)
    'gpt-4o-mini'               → ({'gpt', 'mini'}, (4,), False)
    'gemini-2.5-flash-lite'     → ({'gemini', 'flash', 'lite'}, (2, 5), False)
    'llama-3.3-70b-versatile'   → ({'llama', '70b', 'versatile'}, (3, 3), False)

    Groessenangaben (70b, e4b) gehoeren zur Familie, nicht zur Version — ein
    groesseres Modell ist kein neueres. Datumsstempel fallen weg: ein datierter
    Schnappschuss derselben Version ist kein Fortschritt.
    """
    n = str(name or "").lower().strip()
    n = re.sub(r"[-_]\d{4}-\d{2}-\d{2}$", "", n)       # -2024-07-18
    n = re.sub(r"[-_]\d{8}$", "", n)                   # -20251001
    familie, version, vorschau = set(), [], False
    for teil in re.split(r"[-_/:\s]+", n):
        if not teil:
            continue
        if teil in _VORSCHAU:
            vorschau = True
            continue
        if teil in _RAUSCHEN:
            continue
        if re.fullmatch(r"[a-z]?\d+(\.\d+)?[bm]", teil):          # 70b, e4b, 1.5b
            familie.add(teil)
            continue
        zahl = re.fullmatch(r"(\d+(?:\.\d+)*)[a-z]?", teil)      # 4, 2.5, 4o
        if zahl:
            version.extend(int(x) for x in zahl.group(1).split("."))
            continue
        gemischt = re.fullmatch(r"([a-z]+)(\d+(?:\.\d+)*)", teil)  # o3, gemma3
        if gemischt:
            familie.add(gemischt.group(1))
            version.extend(int(x) for x in gemischt.group(2).split("."))
            continue
        familie.add(teil)
    while len(version) > 1 and version[-1] == 0:        # 3.0 ist 3
        version.pop()
    return frozenset(familie), tuple(version), vorschau


def neuester_verwandter(aktuell: str, namen) -> str:
    """Das neueste Modell derselben Familie in `namen` — oder leer.

    Ein Zeiger wie „mistral-small-latest" ist per Definition aktuell.
    """
    if "latest" in str(aktuell).lower():
        return ""
    familie, version, _ = zerlege(aktuell)
    if not familie or not version:
        return ""
    bester, bester_v = "", version
    for name in namen or ():
        f, v, vorschau = zerlege(name)
        if vorschau or f != familie or not v or v <= bester_v:
            continue
        bester, bester_v = name, v
    if not bester:
        return ""
    # Unter gleich neuen den kuerzesten Namen: den Zeiger, nicht den Schnappschuss.
    gleich = [n for n in namen if zerlege(n)[0] == familie
              and zerlege(n)[1] == bester_v and not zerlege(n)[2]]
    return min(gleich, key=len) if gleich else bester


def _ollama_basis(name: str) -> tuple:
    """'gemma3:4b' → ('gemma', (3,), '4b'); 'qwen3.5:9b' → ('qwen', (3, 5), '9b')."""
    kopf, _, tag = str(name or "").lower().partition(":")
    treffer = re.fullmatch(r"([a-z][a-z-]*?)-?(\d+(?:\.\d+)*)", kopf)
    if not treffer:
        return kopf, (), tag or "latest"
    return (treffer.group(1), tuple(int(x) for x in treffer.group(2).split(".")),
            tag or "latest")


def ollama_generation_groesser(a: str, b: str) -> bool:
    """Ist `a` eine spaetere Generation derselben Familie als `b`?"""
    fa, va, _ = _ollama_basis(a)
    fb, vb, _ = _ollama_basis(b)
    return bool(fa) and fa == fb and bool(va) and bool(vb) and va > vb


# -- Ollama-Registry ---------------------------------------------------------------


def registry_groesse_gb(modell: str, timeout: float = 6.0) -> float | None:
    """Groesse eines Modells in der Ollama-Registry; None = gibt es dort nicht."""
    kopf, _, tag = modell.partition(":")
    request = urllib.request.Request(
        f"{REGISTRY}/{kopf}/manifests/{tag or 'latest'}",
        headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as antwort:
            daten = json.loads(antwort.read())
    except Exception:
        return None
    gesamt = sum(int(s.get("size") or 0) for s in daten.get("layers") or [])
    return round(gesamt / 1e9, 1) if gesamt else 0.0


def ollama_nachfolger(aktuell: str, timeout: float = 6.0) -> tuple:
    """Naechste Generation der Familie in der Registry: (Name, Groesse) oder ("", None).

    Probiert die naechste ganze und die halbe Versionsnummer (gemma3 → gemma3.5,
    gemma4), zuerst mit demselben Tag, dann mit „latest".
    """
    basis, version, tag = _ollama_basis(aktuell)
    if not basis or not version:
        return "", None
    ganz = version[0]
    kandidaten = []
    if len(version) == 1:
        kandidaten.append(f"{ganz}.5")
    kandidaten.append(str(ganz + 1))
    for v in reversed(kandidaten):                # die hoechste zuerst
        for t in dict.fromkeys((tag, "latest")):
            name = f"{basis}{v}:{t}"
            groesse = registry_groesse_gb(name, timeout)
            if groesse is not None:
                return (name if t != "latest" else f"{basis}{v}"), groesse
    return "", None


# -- Die eigentliche Pruefung --------------------------------------------------------


def _gb(wert: float) -> str:
    return f"{wert:.1f}".replace(".", ",") + " GB"


def pruefe(anbieter_id: str, modell: str, schluessel: str = "", adresse: str = "",
           daten: dict | None = None, registry: bool = True,
           timeout: float = 8.0) -> Befund | None:
    """Gibt es fuer die aktuelle Wahl etwas Neueres? None = nein (oder nicht pruefbar).

    Blockiert (Netz) — immer im Hintergrund-Thread aufrufen.
    """
    eintrag = anbieter(anbieter_id)
    if eintrag.id in (AUS, EIGENER):
        return None              # eigener Server: dessen Modelle verwaltet der Nutzer
    daten = daten if daten is not None else mitgelieferter_katalog()
    aktuell = str(modell or "").strip() or empfohlenes_modell(eintrag.id, {})
    if eintrag.id == OLLAMA:
        return _pruefe_ollama(aktuell, daten, registry, timeout)
    return _pruefe_cloud(eintrag, aktuell, schluessel, adresse, daten, timeout)


def _pruefe_ollama(aktuell: str, daten: dict, registry: bool,
                   timeout: float) -> Befund | None:
    modelle = ollama_modelle(daten)
    groessen = {m.modell: m.groesse_gb for m in modelle}
    for m in modelle:
        if not m.empfohlen or m.modell == aktuell:
            continue
        if aktuell in m.ersetzt or ollama_generation_groesser(m.modell, aktuell):
            groesse = f" ({_gb(m.groesse_gb)})" if m.groesse_gb else ""
            return Befund(OLLAMA, aktuell, m.modell,
                          f"Fleech empfiehlt jetzt {m.modell}{groesse} — an echten "
                          f"Diktaten gemessen.", gemessen=True)
    if not registry:
        return None
    name, groesse = ollama_nachfolger(aktuell, timeout)
    if not name:
        return None
    # Kennt der Katalog diese Generation schon, sagt er mehr als die Registry:
    # welches Tag sinnvoll ist und was die Messung ergab.
    for m in modelle:
        if _ollama_basis(m.modell)[:2] == _ollama_basis(name)[:2]:
            name, groesse = m.modell, m.groesse_gb or groesse
            if m.gemessen:
                gb = f" ({_gb(groesse)})" if groesse else ""
                return Befund(OLLAMA, aktuell, name,
                              f"Neue Generation: {name}{gb}. {m.notiz}", gemessen=True)
            break
    vorher = groessen.get(aktuell) or registry_groesse_gb(aktuell, timeout)
    # Ein Vielfaches an Groesse ist keine Alternative, sondern eine andere
    # Rechnerklasse: llama3.2:3b (2 GB) → llama4 (67 GB) waere kein Vorschlag.
    if groesse and vorher and groesse > MAX_WACHSTUM * vorher:
        log.info("Modellpruefung: %s (%.1f GB) zu gross gegenueber %s (%.1f GB).",
                 name, groesse, aktuell, vorher)
        return None
    vergleich = ""
    if groesse:
        vergleich = (f" ({_gb(groesse)} statt {_gb(vorher)})" if vorher
                     else f" ({_gb(groesse)})")
    return Befund(OLLAMA, aktuell, name,
                  f"Neue Generation bei Ollama: {name}{vergleich}. Noch nicht an "
                  f"Diktaten gemessen — neuer ist nicht immer schneller.")


def _pruefe_cloud(eintrag, aktuell: str, schluessel: str, adresse: str,
                  daten: dict, timeout: float) -> Befund | None:
    if eintrag.braucht_schluessel and not schluessel:
        return None
    try:
        namen = modelle_abrufen(eintrag, schluessel, adresse, timeout=timeout)
    except Exception as exc:
        log.info("Modellpruefung %s: Liste nicht abrufbar (%s).", eintrag.id, exc)
        return None
    if not namen:
        return None
    neuer = neuester_verwandter(aktuell, namen)
    if neuer:
        return Befund(eintrag.id, aktuell, neuer,
                      f"{eintrag.name} bietet ein neueres Modell derselben Klasse an: "
                      f"{neuer}.")
    if aktuell not in namen and "latest" not in aktuell:
        from .providers import modell_vorschlag

        ersatz = empfohlenes_modell(eintrag.id, daten)
        ersatz = ersatz if ersatz in namen else modell_vorschlag(eintrag, namen)
        if ersatz and ersatz != aktuell:
            return Befund(eintrag.id, aktuell, ersatz,
                          f"{aktuell} steht bei {eintrag.name} nicht mehr zur Wahl — "
                          f"Vorschlag: {ersatz}.")
    return None


# -- Auswahllisten fuer die Oberflaeche ------------------------------------------------


@dataclass(frozen=True)
class Wahl:
    """Ein Eintrag der Modell-Auswahl: Name, Beschriftung, Erklaerung."""

    modell: str
    label: str
    notiz: str = ""


def lokale_auswahl(daten: dict, installiert=(), nachfolger: tuple = ("", None)) -> list:
    """Katalog + installierte Modelle + Neuigkeit aus der Registry, ohne Doppelte.

    Reihenfolge: die Empfehlung zuerst, dann der Katalog, dann Installiertes, dann
    die Registry-Neuheit. Einbettungsmodelle koennen keinen Text bereinigen.
    """
    installiert = {n for n in installiert or () if "embed" not in n.lower()}
    raus, gesehen = [], set()
    modelle = sorted(ollama_modelle(daten), key=lambda m: not m.empfohlen)
    for m in modelle:
        teile = [m.modell]
        if m.groesse_gb:
            teile.append(_gb(m.groesse_gb))
        if m.empfohlen:
            teile.append("empfohlen")
        elif m.neu and not m.gemessen:
            teile.append("neu, noch nicht gemessen")
        if m.modell in installiert:
            teile.append("installiert")
        raus.append(Wahl(m.modell, " · ".join(teile), m.notiz))
        gesehen.add(m.modell)
    for name in sorted(installiert - gesehen):
        raus.append(Wahl(name, f"{name} · installiert",
                         "Schon auf diesem Rechner — von Fleech nicht gemessen."))
        gesehen.add(name)
    name, groesse = nachfolger or ("", None)
    # Steht dieselbe Generation schon im Katalog (gemma4:e4b), ist „gemma4" aus
    # der Registry nur ein zweiter Name dafuer.
    familien = {_ollama_basis(n)[:2] for n in gesehen}
    if name and _ollama_basis(name)[:2] not in familien:
        teile = [name] + ([_gb(groesse)] if groesse else []) + ["neu bei Ollama"]
        raus.append(Wahl(name, " · ".join(teile),
                         "Neue Generation, gerade erschienen. Noch nicht an Diktaten "
                         "gemessen — neuer ist nicht immer schneller."))
    return raus


def cloud_auswahl(anbieter_id: str, namen, daten: dict) -> tuple:
    """(Eintraege, empfohlen, neuer) fuer die Liste eines Cloud-Anbieters.

    Die Empfehlung steht oben, ein neueres Modell derselben Klasse direkt
    darunter — gewaehlt wird es nur, wenn der Nutzer es will.
    """
    from .providers import modell_vorschlag

    eintrag = anbieter(anbieter_id)
    namen = list(namen or ())
    empfohlen = empfohlenes_modell(eintrag.id, daten)
    if empfohlen not in namen:
        empfohlen = modell_vorschlag(eintrag, namen) if namen else empfohlen
    neuer = neuester_verwandter(empfohlen, namen)
    raus = [Wahl(empfohlen, f"{empfohlen} · empfohlen",
                 "Schnell und günstig — reicht zum Aufräumen von Diktaten.")]
    if neuer:
        raus.append(Wahl(neuer, f"{neuer} · neuer",
                         f"Neuere Fassung derselben Klasse wie {empfohlen}. Von "
                         f"Fleech noch nicht an Diktaten gemessen."))
    for name in namen:
        if name not in (empfohlen, neuer):
            raus.append(Wahl(name, name))
    return raus, empfohlen, neuer
