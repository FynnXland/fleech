from fleech.llm.client import strip_reasoning


def test_strip_reasoning_removes_think_block():
    assert strip_reasoning("<think>hm, mal überlegen…</think>Der Text.") == "Der Text."


def test_strip_reasoning_multiline():
    assert strip_reasoning("<think>zeile 1\nzeile 2</think>\n\nErgebnis") == "Ergebnis"


def test_strip_reasoning_leaves_plain_text():
    assert strip_reasoning("Ganz normaler Text.") == "Ganz normaler Text."


def test_strip_reasoning_covers_common_tag_variants():
    """Bei einem Modellwechsel wuerde ein unbekanntes Denkblock-Tag sonst sichtbar
    im eingefuegten Text landen — ein peinlicher Fehler mitten im Zieltext."""
    from fleech.llm.client import strip_reasoning

    for tag in ("think", "thinking", "thought", "reasoning", "scratchpad", "analysis"):
        text = f"<{tag}>Ich ueberlege kurz.</{tag}>\nDer saubere Text."
        assert strip_reasoning(text) == "Der saubere Text."
    # Gross-/Kleinschreibung egal, mehrzeilig ebenso.
    assert strip_reasoning("<THINK>\nviel\ntext\n</THINK>Ergebnis") == "Ergebnis"
    # Normaler Text mit spitzen Klammern bleibt unangetastet.
    assert strip_reasoning("a < b und b > c") == "a < b und b > c"


def test_strip_reasoning_extra_patterns_and_broken_regex():
    from fleech.llm.client import strip_reasoning

    text = "[[REASON]]intern[[/REASON]]Das Ergebnis."
    assert strip_reasoning(text, [r"\[\[REASON\]\].*?\[\[/REASON\]\]"]) == "Das Ergebnis."
    # Kaputtes Muster darf nie raisen (kommt aus der Nutzer-config.yaml).
    assert strip_reasoning("Text", ["(unbalanced"]) == "Text"


# -- Direktweg zu Ollama (v3.6.0: OpenAI-SDK entfallen) ----------------------------
# Loest tests/test_llm_retry.py ab — der dort gepruefte 429-Backoff gehoerte zum
# multimodalen Cloud-Pfad, den es seit v3.0.0 nicht mehr gibt.

import io
import json

import pytest

from fleech.config import LLMEndpointConfig
from fleech.llm.client import ChatClient, ensure_ollama_models, ollama_root


def test_ollama_root_schneidet_das_v1_suffix_ab():
    """Bestands-config.yaml traegt noch `/v1` aus der OpenAI-Zeit — das darf nicht
    zu einer 404 fuehren, nur weil eine alte Datei weiterbenutzt wird."""
    assert ollama_root("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434"
    assert ollama_root("http://127.0.0.1:11434/v1/") == "http://127.0.0.1:11434"
    assert ollama_root("http://127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert ollama_root("") == "http://127.0.0.1:11434"


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(monkeypatch, antwort: dict, aufzeichnung: list):
    def urlopen(request, timeout=None):
        aufzeichnung.append({"url": request.full_url,
                             "body": json.loads(request.data.decode("utf-8"))})
        return _FakeResponse(json.dumps(antwort).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)


def test_chat_sendet_num_ctx_an_ollama(monkeypatch):
    """`num_ctx` ist der Grund fuer den Direktweg: Ohne den Wert laedt Ollama mit
    4096 Token, und lange Diktate brechen mitten im Satz ab."""
    calls = []
    _fake_urlopen(monkeypatch, {"message": {"content": "Sauber."},
                               "done_reason": "stop"}, calls)
    client = ChatClient(LLMEndpointConfig(num_ctx=8192, reasoning_effort=""))

    assert client.complete("SYS", "roher text") == "Sauber."
    assert calls[0]["url"] == "http://127.0.0.1:11434/api/chat"
    assert calls[0]["body"]["options"]["num_ctx"] == 8192
    assert calls[0]["body"]["stream"] is False
    assert "think" not in calls[0]["body"]        # gemma3 denkt nicht
    assert not client.last_truncated


def test_thinking_modell_bekommt_think_false(monkeypatch):
    """reasoning_effort "none" muss auf dem Direktweg ankommen — sonst denkt ein
    Thinking-Modell 30–50 s pro Diktat."""
    calls = []
    _fake_urlopen(monkeypatch, {"message": {"content": "x"}}, calls)
    ChatClient(LLMEndpointConfig(reasoning_effort="none")).complete("SYS", "text")
    assert calls[0]["body"]["think"] is False


def test_abgeschnittene_antwort_wird_gemeldet(monkeypatch):
    """done_reason "length" = Kontextfenster voll. Die Pipeline braucht das Signal,
    weil der gelieferte Text korrekt AUSSIEHT — ihm fehlt nur das Ende."""
    _fake_urlopen(monkeypatch, {"message": {"content": "Halber Satz, der"},
                               "done_reason": "length"}, [])
    client = ChatClient(LLMEndpointConfig())
    client.complete("SYS", "sehr langes diktat")
    assert client.last_truncated


def test_denkblock_wird_auch_auf_dem_direktweg_entfernt(monkeypatch):
    _fake_urlopen(monkeypatch, {"message": {"content": "<think>hm</think>Der Text."}}, [])
    assert ChatClient(LLMEndpointConfig()).complete("SYS", "text") == "Der Text."


def test_fehlendes_modell_wird_nachgeladen(monkeypatch):
    """Frische Installation: Fleech holt sich selbst, was es braucht."""
    geholt = []
    monkeypatch.setattr("fleech.llm.client.ollama_installed_models",
                        lambda base, timeout=10.0: {"anderes:7b"})
    monkeypatch.setattr("fleech.llm.client.ollama_pull",
                        lambda base, model, on_progress=None, timeout=3600.0:
                        (geholt.append(model), True)[1])

    assert ensure_ollama_models([LLMEndpointConfig(model="gemma3:4b")]) == ["gemma3:4b"]
    assert geholt == ["gemma3:4b"]


def test_vorhandenes_modell_wird_nicht_erneut_geladen(monkeypatch):
    monkeypatch.setattr("fleech.llm.client.ollama_installed_models",
                        lambda base, timeout=10.0: {"gemma3:4b"})
    monkeypatch.setattr("fleech.llm.client.ollama_pull",
                        lambda *a, **k: pytest.fail("darf nicht geladen werden"))
    assert ensure_ollama_models([LLMEndpointConfig(model="gemma3:4b")]) == []


def test_dasselbe_modell_wird_nur_einmal_geholt(monkeypatch):
    """cleanup und cleanup_fast teilen sich seit dem Modellvergleich ein Modell."""
    geholt = []
    monkeypatch.setattr("fleech.llm.client.ollama_installed_models",
                        lambda base, timeout=10.0: {"alt:1b"})
    monkeypatch.setattr("fleech.llm.client.ollama_pull",
                        lambda base, model, on_progress=None, timeout=3600.0:
                        (geholt.append(model), True)[1])

    ensure_ollama_models([LLMEndpointConfig(model="gemma3:4b"),
                          LLMEndpointConfig(model="gemma3:4b")])
    assert geholt == ["gemma3:4b"]


def test_ohne_erreichbares_ollama_passiert_nichts(monkeypatch):
    """Ollama startet gerade neu → App trotzdem hochfahren lassen, statt den Start
    an einem Download aufzuhaengen."""
    monkeypatch.setattr("fleech.llm.client.ollama_installed_models",
                        lambda base, timeout=10.0: set())
    monkeypatch.setattr("fleech.llm.client.ollama_pull",
                        lambda *a, **k: pytest.fail("kein Download ohne Ollama"))
    assert ensure_ollama_models([LLMEndpointConfig(model="gemma3:4b")]) == []


def test_entfernte_endpoints_werden_nicht_verwaltet(monkeypatch):
    """Fremde Server bespielt Fleech nicht — dort hat es nichts zu installieren."""
    monkeypatch.setattr("fleech.llm.client.ollama_installed_models",
                        lambda *a, **k: pytest.fail("kein Zugriff auf fremde Server"))
    cfg = LLMEndpointConfig(base_url="https://api.example.com/v1", model="fremd:1b")
    assert ensure_ollama_models([cfg]) == []


def test_localhost_wird_zur_ip_umgeschrieben():
    """Der Name `localhost` kostet unter Windows 2,05 s PRO ANFRAGE.

    Windows fragt zuerst die IPv6-Adresse ::1 ab, auf der Ollama standardmaessig
    nicht lauscht, und wartet den Verbindungs-Timeout ab, bevor es IPv4 versucht.
    Gemessen: 3,43 s Wanduhr mit Namen gegen 1,19 s mit IP — bei identischer
    Rechenzeit laut Ollama. Das lag auf JEDEM Diktat.

    Die Ersetzung greift in `ollama_root`, damit auch bestehende config.yaml und
    settings ohne Zutun profitieren.
    """
    assert ollama_root("http://localhost:11434") == "http://127.0.0.1:11434"
    assert ollama_root("http://localhost:11434/v1") == "http://127.0.0.1:11434"
    # Ein fremder Host mit "localhost" im Namen darf NICHT angefasst werden.
    assert ollama_root("http://localhost.fritz.box:11434") == \
        "http://localhost.fritz.box:11434"
    assert ollama_root("http://192.168.1.5:11434") == "http://192.168.1.5:11434"


def test_chat_geht_an_die_ip(monkeypatch):
    """Gegenprobe auf dem echten Aufrufweg — nicht nur in der Hilfsfunktion."""
    calls = []
    _fake_urlopen(monkeypatch, {"message": {"content": "ok"}}, calls)
    ChatClient(LLMEndpointConfig(base_url="http://localhost:11434/v1")).complete("S", "t")
    assert calls[0]["url"] == "http://127.0.0.1:11434/api/chat"


def test_preload_setzt_num_ctx_mit(monkeypatch):
    """Ohne num_ctx beim Vorladen ist das Warmhalten wertlos.

    Ollama bindet die Kontextgroesse an die geladene Instanz. Laedt der Preload
    mit dem Default 4096 und will der Diktat-Aufruf 8192, laedt Ollama das Modell
    JEDES MAL neu — real gemessen 5 s statt 1,3 s Cleanup-Zeit, und `ollama ps`
    zeigte CONTEXT 4096 trotz konfigurierter 8192.
    """
    from fleech.llm.client import ollama_preload, ollama_unload

    calls = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout=None):
        calls.append(json.loads(request.data.decode("utf-8")))
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    cfg = LLMEndpointConfig(num_ctx=8192)

    ollama_preload(cfg)
    assert calls[0]["options"]["num_ctx"] == 8192
    assert calls[0]["keep_alive"]

    # Beim ENTLADEN ist die Kontextgroesse bedeutungslos — kein Ballast im Request.
    calls.clear()
    ollama_unload(cfg)
    assert calls[0]["keep_alive"] == 0
    assert "options" not in calls[0]



def test_chat_haelt_das_modell_selbst_warm(monkeypatch):
    """Ohne `keep_alive` setzt Ollama nach jedem Diktat seine eigene Vorgabe
    (5 min) — kuerzer als Fleechs Warmhaltefenster. Deshalb musste ein Takt das
    Modell jede Minute neu „vorladen". Jetzt traegt schon das Diktat den Wert."""
    from fleech.llm.client import OLLAMA_KEEP_ALIVE

    calls = []
    _fake_urlopen(monkeypatch, {"message": {"content": "Sauber."},
                               "done_reason": "stop"}, calls)
    ChatClient(LLMEndpointConfig(num_ctx=8192, reasoning_effort="")).complete("S", "t")
    assert calls[0]["body"]["keep_alive"] == OLLAMA_KEEP_ALIVE


@pytest.mark.parametrize("ps, erwartet", [
    ({"models": [{"name": "gemma3:4b", "size": 3_000_000_000, "size_vram": 0}]}, True),
    ({"models": [{"name": "gemma3:4b", "size": 3_000_000_000,
                  "size_vram": 3_000_000_000}]}, False),
    ({"models": []}, None),                                   # nicht geladen
    ({"models": [{"name": "anderes:1b", "size": 1, "size_vram": 0}]}, None),
])
def test_erkennt_ki_auf_dem_prozessor(monkeypatch, ps, erwartet):
    """Am 2026-10-02 rechnete Ollama nach einem Selbst-Update auf dem Prozessor
    (size_vram 0): 13–27 s je Bereinigung statt ~0,5 s, und Fleech merkte nichts."""
    from fleech.llm.client import ollama_auf_cpu

    abgefragt = []

    def urlopen(url, timeout=None):
        abgefragt.append(url)
        return _FakeResponse(json.dumps(ps).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert ollama_auf_cpu(LLMEndpointConfig(model="gemma3:4b")) is erwartet
    assert abgefragt == ["http://127.0.0.1:11434/api/ps"]


def test_ki_pruefung_fasst_keinen_entfernten_server_an():
    from fleech.llm.client import ollama_auf_cpu

    assert ollama_auf_cpu(LLMEndpointConfig(model="gemma3:4b",
                                            base_url="http://192.168.1.9:11434")) is None
