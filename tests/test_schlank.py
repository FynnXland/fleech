"""Die schlanke Fassung eines Sprachmodells (`fleech/llm/schlank.py`).

Geprueft wird vor allem, was nicht schiefgehen darf: Die Textgewichte muessen
Byte fuer Byte erhalten bleiben (sonst waere es ein anderes Modell), und wenn der
Umbau nicht klappt, muss Fleech mit dem Original weiterlaufen und das sagen.
"""

import io
import json
import struct
import urllib.error

import pytest

from fleech import provisioning
from fleech.config import LLMEndpointConfig
from fleech.llm import schlank
from fleech.llm.client import ensure_ollama_models


@pytest.fixture(autouse=True)
def _frisch():
    schlank._GESCHEITERT.clear()
    yield
    schlank._GESCHEITERT.clear()


# -- eine kleine GGUF-Datei mit Bildteil -----------------------------------------------


def _text(t: str) -> bytes:
    roh = t.encode("utf-8")
    return struct.pack("<Q", len(roh)) + roh


def _schluessel_str(name, wert):
    return _text(name) + struct.pack("<I", 8) + _text(wert)


def _schluessel_u32(name, wert):
    return _text(name) + struct.pack("<II", 4, wert)


def _schluessel_str_array(name, werte):
    return (_text(name) + struct.pack("<IIQ", 9, 8, len(werte))
            + b"".join(_text(w) for w in werte))


def _schluessel_f32_array(name, werte):
    return (_text(name) + struct.pack("<IIQ", 9, 6, len(werte))
            + b"".join(struct.pack("<f", w) for w in werte))


# Absichtlich gemischt: Bild- und Text-Tensoren wechseln sich in der Datei ab.
TENSOREN = [("blk.0.w", 32, b"A"), ("v.patch", 64, b"V"), ("token_embd", 32, b"T"),
            ("mm.proj", 32, b"M"), ("output_norm", 16, b"O")]


def _gguf() -> bytes:
    schluessel = [
        _schluessel_str("general.architecture", "gemma3"),
        _schluessel_u32("gemma3.block_count", 1),
        _schluessel_u32("gemma3.vision.block_count", 27),
        _schluessel_u32("gemma3.mm.tokens_per_image", 256),
        _schluessel_str_array("tokenizer.ggml.tokens", ["<s>", "hallo", "welt"]),
        _schluessel_f32_array("tokenizer.ggml.scores", [0.0, 1.5, -2.0]),
    ]
    kopf = b"GGUF" + struct.pack("<IQQ", 3, len(TENSOREN), len(schluessel))
    kopf += b"".join(schluessel)
    versatz, daten = 0, b""
    for name, laenge, fuell in TENSOREN:
        kopf += _text(name) + struct.pack("<I", 1) + struct.pack("<Q", laenge)
        kopf += struct.pack("<IQ", 0, versatz)
        stueck = fuell * laenge
        stueck += b"\0" * (-len(stueck) % 32)
        daten += stueck
        versatz += len(stueck)
    kopf += b"\0" * (-len(kopf) % 32)
    return kopf + daten


def _tensordaten(pfad, kopf):
    with open(pfad, "rb") as f:
        roh = f.read()
    return {t["name"]: roh[kopf["daten"] + t["versatz"]:kopf["daten"] + t["versatz"]
                           + t["laenge"]] for t in kopf["tensoren"]}


def test_bildteil_faellt_weg_textgewichte_bleiben_byte_gleich(tmp_path):
    quelle = tmp_path / "quelle.gguf"
    quelle.write_bytes(_gguf())
    vorher = schlank.lies_kopf(quelle)
    neu_kopf, abschnitte = schlank.ohne_bildteil(vorher)
    ziel = tmp_path / "ziel.gguf"
    ziel.write_bytes(b"".join(schlank.datenstrom(quelle, neu_kopf, abschnitte)))

    nachher = schlank.lies_kopf(ziel)
    assert [t["name"] for t in nachher["tensoren"]] == ["blk.0.w", "token_embd",
                                                         "output_norm"]
    namen = [n for n, _, _ in nachher["schluessel"]]
    assert "gemma3.vision.block_count" not in namen
    assert "gemma3.mm.tokens_per_image" not in namen
    assert {"general.architecture", "gemma3.block_count", "tokenizer.ggml.tokens",
            "tokenizer.ggml.scores"} <= set(namen)
    alt, neu = _tensordaten(quelle, vorher), _tensordaten(ziel, nachher)
    for name in ("blk.0.w", "token_embd", "output_norm"):
        assert neu[name] == alt[name]
    assert nachher["daten"] % 32 == 0
    assert all(t["versatz"] % 32 == 0 for t in nachher["tensoren"])


def test_modell_ohne_bildteil_wird_nicht_umgebaut(tmp_path):
    datei = tmp_path / "text.gguf"
    datei.write_bytes(_gguf())
    kopf, abschnitte = schlank.ohne_bildteil(schlank.lies_kopf(datei))
    datei.write_bytes(b"".join(schlank.datenstrom(datei, kopf, abschnitte)))
    with pytest.raises(schlank.SchlankFehler, match="keinen Bildteil"):
        schlank.ohne_bildteil(schlank.lies_kopf(datei))


def test_namen_und_erklaerung():
    assert schlank.quelle_von("gemma3:4b-text") == "gemma3:4b"
    assert schlank.quelle_von("gemma3:4b") == ""
    assert schlank.schlanke_fassung("gemma3:4b") == "gemma3:4b-text"
    assert schlank.bevorzugt("qwen3.5:2b") == "qwen3.5:2b"
    satz = schlank.erklaerung("gemma3:4b-text")
    assert "Bildteil" in satz and "0,8 GB" in satz and "gemma3:4b" in satz


# -- Bauen gegen ein nachgestelltes Ollama ---------------------------------------------


def _ablage(tmp_path, monkeypatch):
    """Ein Ollama-Modellordner mit gemma3:4b darin (Manifest + Schichten)."""
    ordner = tmp_path / "models"
    blobs = ordner / "blobs"
    blobs.mkdir(parents=True)
    schichten = []
    for art, inhalt in (("image.model", _gguf()),
                        ("image.template", b"{{ .Prompt }}"),
                        ("image.params", b'{"stop": ["<end_of_turn>"]}'),
                        ("image.license", b"Gemma Terms")):
        digest = f"sha256:{art.replace('.', '')}"
        (blobs / digest.replace(":", "-")).write_bytes(inhalt)
        schichten.append({"mediaType": f"application/vnd.ollama.{art}", "digest": digest})
    manifest = ordner / "manifests" / "registry.ollama.ai" / "library" / "gemma3" / "4b"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"layers": schichten}), encoding="utf-8")
    monkeypatch.setenv("OLLAMA_MODELS", str(ordner))
    return ordner


class _Antwort(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_baue_meldet_die_schlanke_fassung_bei_ollama_an(tmp_path, monkeypatch):
    _ablage(tmp_path, monkeypatch)
    gesendet, auftraege, prozente = {}, [], []

    def anfrage(url, daten=None, methode="POST", kopf=None, timeout=600.0):
        if methode == "HEAD":
            raise urllib.error.HTTPError(url, 404, "fehlt", {}, None)
        if url.endswith("/api/create"):
            auftraege.append(json.loads(daten))
            return _Antwort(b'{"status": "success"}')
        gesendet[url] = b"".join(daten)
        assert int(kopf["Content-Length"]) == len(gesendet[url])
        return _Antwort(b"")

    monkeypatch.setattr(schlank, "_anfrage", anfrage)
    schlank.baue("http://127.0.0.1:11434", "gemma3:4b-text", on_prozent=prozente.append)

    (url, datei), = gesendet.items()
    assert url.startswith("http://127.0.0.1:11434/api/blobs/sha256:")
    hochgeladen = tmp_path / "hoch.gguf"
    hochgeladen.write_bytes(datei)
    assert "v.patch" not in [t["name"] for t in schlank.lies_kopf(hochgeladen)["tensoren"]]
    auftrag, = auftraege
    assert auftrag["model"] == "gemma3:4b-text"
    assert list(auftrag["files"].values()) == [url.rsplit("/", 1)[1]]
    assert auftrag["template"] == "{{ .Prompt }}"
    assert auftrag["parameters"] == {"stop": ["<end_of_turn>"]}
    assert auftrag["license"] == "Gemma Terms"
    assert prozente[-1] == 100 and prozente == sorted(prozente)


def test_ohne_ablage_ein_verstaendlicher_grund(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "leer"))
    monkeypatch.setattr(schlank.Path, "home", lambda: tmp_path / "kein_home")
    monkeypatch.setattr(schlank, "_modellordner_kandidaten", lambda: [tmp_path / "leer"])
    with pytest.raises(schlank.SchlankFehler, match="nicht gefunden"):
        schlank.baue("http://127.0.0.1:11434", "gemma3:4b-text")


# -- Besorgen: alle Wege -----------------------------------------------------------------


def _ollama(monkeypatch, installiert, baue=None):
    import fleech.llm.client as client

    protokoll = []
    monkeypatch.setattr(client, "ollama_installed_models", lambda *a, **k: set(installiert))
    monkeypatch.setattr(client, "ollama_pull",
                        lambda base, m, on_progress=None, timeout=3600.0, on_bytes=None:
                        (protokoll.append(("pull", m)), True)[1])
    monkeypatch.setattr(schlank, "baue", baue or (lambda base, m, on_prozent=None:
                                                  protokoll.append(("baue", m))))
    monkeypatch.setattr(schlank, "entferne",
                        lambda base, m: (protokoll.append(("entferne", m)), True)[1])
    return protokoll


def test_original_fehlt_wird_geladen_umgebaut_und_wieder_entfernt(monkeypatch):
    protokoll = _ollama(monkeypatch, set())
    ergebnis = schlank.besorge("http://x", "gemma3:4b-text")
    assert protokoll == [("pull", "gemma3:4b"), ("baue", "gemma3:4b-text"),
                         ("entferne", "gemma3:4b")]
    assert ergebnis.modell == "gemma3:4b-text" and ergebnis.verschlankt
    assert "wieder entfernt" in ergebnis.hinweis


def test_vorhandenes_original_bleibt_und_das_wird_gesagt(monkeypatch):
    protokoll = _ollama(monkeypatch, {"gemma3:4b"})
    ergebnis = schlank.besorge("http://x", "gemma3:4b-text")
    assert protokoll == [("baue", "gemma3:4b-text")]
    assert "bleibt installiert" in ergebnis.hinweis and "ollama rm gemma3:4b" in ergebnis.hinweis


def test_gescheiterter_umbau_laeuft_mit_dem_original_und_versucht_es_nicht_dauernd(
        monkeypatch):
    versuche = []

    def kaputt(base, m, on_prozent=None):
        versuche.append(m)
        raise schlank.SchlankFehler("Ollamas Modellordner ist nicht lesbar")

    _ollama(monkeypatch, {"gemma3:4b"}, baue=kaputt)
    ergebnis = schlank.besorge("http://x", "gemma3:4b-text")
    assert ergebnis.modell == "gemma3:4b" and not ergebnis.verschlankt
    assert "nicht lesbar" in ergebnis.hinweis and "gemma3:4b" in ergebnis.hinweis
    assert schlank.grund("gemma3:4b-text") == "Ollamas Modellordner ist nicht lesbar"
    again = schlank.besorge("http://x", "gemma3:4b-text")
    assert again.modell == "gemma3:4b" and not again.hinweis and versuche == ["gemma3:4b-text"]


def test_normales_modell_wird_einfach_geladen(monkeypatch):
    protokoll = _ollama(monkeypatch, set())
    assert schlank.besorge("http://x", "qwen3.5:2b-q4_K_M").modell == "qwen3.5:2b-q4_K_M"
    assert protokoll == [("pull", "qwen3.5:2b-q4_K_M")]


# -- Beim Start: alle Endpunkte ziehen mit ------------------------------------------------


def test_start_rechnet_waehrend_des_umbaus_mit_dem_original(monkeypatch):
    import fleech.llm.client as client

    monkeypatch.setattr(client, "ollama_installed_models", lambda *a, **k: {"gemma3:4b"})
    entladen, hinweise = [], []
    monkeypatch.setattr(client, "ollama_unload", lambda ep: entladen.append(ep.model))
    alle = [LLMEndpointConfig(model="gemma3:4b-text") for _ in range(3)]
    waehrenddessen = []

    def besorge(base, modell, **k):
        waehrenddessen.append([ep.model for ep in alle])
        return schlank.Ergebnis("gemma3:4b-text", "verschlankt", verschlankt=True)

    monkeypatch.setattr(schlank, "besorge", besorge)
    ensure_ollama_models(alle[:1], on_hinweis=hinweise.append, alle=alle)
    assert waehrenddessen == [["gemma3:4b"] * 3]          # Diktate laufen weiter
    assert [ep.model for ep in alle] == ["gemma3:4b-text"] * 3
    assert entladen == ["gemma3:4b"]
    assert len(hinweise) == 2 and hinweise[1] == "verschlankt"
    assert "verschlankt das Sprachmodell" in hinweise[0] and "20 Sekunden" in hinweise[0]


def test_start_bleibt_beim_original_wenn_der_umbau_scheitert(monkeypatch):
    import fleech.llm.client as client

    monkeypatch.setattr(client, "ollama_installed_models", lambda *a, **k: {"gemma3:4b"})
    monkeypatch.setattr(client, "ollama_unload", lambda ep: pytest.fail("nichts entladen"))
    monkeypatch.setattr(schlank, "besorge",
                        lambda base, modell, **k: schlank.Ergebnis("gemma3:4b", "ging nicht"))
    alle = [LLMEndpointConfig(model="gemma3:4b-text") for _ in range(3)]
    hinweise = []
    ensure_ollama_models(alle[:1], on_hinweis=hinweise.append, alle=alle)
    assert [ep.model for ep in alle] == ["gemma3:4b"] * 3
    assert hinweise[-1] == "ging nicht"


# -- Die Einrichtung sagt, was passiert ------------------------------------------------------


class _Endpunkt:
    def __init__(self, model):
        self.model = model
        self.base_url = "http://127.0.0.1:11434"


@pytest.mark.parametrize("installiert, erwartet", [
    ({"gemma3:4b"}, "wird aus gemma3:4b gebaut (kein Download)"),
    (set(), "lädt gemma3:4b (etwa 3,3 GB), danach wird der Bildteil entfernt"),
])
def test_einrichtung_beschreibt_den_umbau(monkeypatch, installiert, erwartet):
    from fleech import ollama_setup
    import fleech.llm.client as client

    monkeypatch.setattr(provisioning, "whisper_present", lambda _m: True)
    monkeypatch.setattr(ollama_setup, "status", lambda *a, **k: "ready")
    monkeypatch.setattr(client, "ollama_installed_models", lambda *a, **k: set(installiert))
    schritte = provisioning.build_steps([_Endpunkt("gemma3:4b-text")], "large-v3-turbo",
                                        "http://127.0.0.1:11434")
    llm = next(s for s in schritte if s.key == "llm:gemma3:4b-text")
    assert llm.note == erwartet
    assert "Bildteil" in llm.detail and "0,8 GB" in llm.detail


# -- Erstes Diktat, bevor die schlanke Fassung gebaut ist ---------------------------------


def _chat_attrappe(monkeypatch, fehlt):
    gefragt = []

    def urlopen(anfrage, timeout=None):
        modell = json.loads(anfrage.data)["model"]
        gefragt.append(modell)
        if modell in fehlt:
            raise urllib.error.HTTPError(anfrage.full_url, 404, "Not Found", {},
                                         io.BytesIO(b'{"error": "model not found"}'))
        return _Antwort(json.dumps({"message": {"content": "Sauber."},
                                    "done_reason": "stop"}).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return gefragt


def test_fehlt_die_schlanke_fassung_noch_bereinigt_das_original(monkeypatch):
    from fleech.llm.client import ChatClient

    gefragt = _chat_attrappe(monkeypatch, {"gemma3:4b-text"})
    ep = LLMEndpointConfig(model="gemma3:4b-text")
    assert ChatClient(ep).complete("System", "roh") == "Sauber."
    assert gefragt == ["gemma3:4b-text", "gemma3:4b"]
    assert ep.model == "gemma3:4b-text"          # die Einstellung bleibt, wie sie ist


def test_anderes_fehlendes_modell_bleibt_ein_fehler(monkeypatch):
    from fleech.llm.client import ChatClient

    _chat_attrappe(monkeypatch, {"qwen3.5:2b"})
    with pytest.raises(urllib.error.HTTPError):
        ChatClient(LLMEndpointConfig(model="qwen3.5:2b")).complete("System", "roh")
