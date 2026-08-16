"""Tests for the free-service registry, detection, and dynamic catalog build.

Detection is exercised with a stubbed environment and a stubbed Ollama probe so
it is deterministic and needs no network.
"""
import importlib

from arccode import services


def test_registry_has_free_services():
    names = set(services.SERVICES)
    for expected in ("ollama", "groq", "gemini", "cerebras", "mistral",
                     "openrouter", "github", "openai", "anthropic"):
        assert expected in names
    # free tier providers are marked free
    assert services.SERVICES["groq"].free
    assert not services.SERVICES["openai"].free


def test_detect_key_based_service(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setattr(services, "_ollama_up", lambda timeout=1.0: [])
    det = services.detect()
    assert det["groq"].connected
    assert "GROQ_API_KEY" in det["groq"].reason
    assert not det["gemini"].connected  # no key -> off


def test_detect_ollama_live(monkeypatch):
    monkeypatch.setattr(services, "_ollama_up", lambda timeout=1.0: ["llama3", "qwen"])
    det = services.detect()
    assert det["ollama"].connected
    assert det["ollama"].live_models == ["llama3", "qwen"]


def test_detect_ollama_down(monkeypatch):
    monkeypatch.setattr(services, "_ollama_up", lambda timeout=1.0: [])
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    det = services.detect()
    assert not det["ollama"].connected
    assert "ollama serve" in det["ollama"].reason


def test_connected_services_filters(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "m-test")
    monkeypatch.setattr(services, "_ollama_up", lambda timeout=1.0: [])
    conn = services.connected_services()
    assert set(conn) == {"mistral"}


def test_api_key_precedence(monkeypatch):
    # first declared env var wins
    monkeypatch.setenv("GOOGLE_API_KEY", "g2")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert services.SERVICES["gemini"].api_key() == "g2"
    monkeypatch.setenv("GEMINI_API_KEY", "g1")
    assert services.SERVICES["gemini"].api_key() == "g1"


def test_dynamic_catalog_build(monkeypatch):
    """With a key set and autodetect on, the catalog contains that provider's seeds."""
    monkeypatch.delenv("ARCCODE_NO_AUTODETECT", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setattr(services, "_ollama_up", lambda timeout=1.0: [])
    from arccode import config
    importlib.reload(config)
    models = config.load_models()
    groq_models = [k for k in models if k.startswith("groq/")]
    assert groq_models, "expected groq seed models in the catalog"
    # embedding models are filtered from dynamic (ollama) discovery
    assert not any("embed" in k for k in models)
    # restore deterministic catalog for the rest of the suite
    monkeypatch.setenv("ARCCODE_NO_AUTODETECT", "1")
    importlib.reload(config)


def test_embedding_filter():
    from arccode import config
    assert config._is_embedding_model("nomic-embed-text:latest")
    assert config._is_embedding_model("bge-large")
    assert not config._is_embedding_model("qwen2.5-coder")


def test_openai_compat_resolves_service_endpoint():
    from arccode.providers.openai_compat import _service_endpoint
    base, envs = _service_endpoint("groq")
    assert base == "https://api.groq.com/openai/v1"
    assert "GROQ_API_KEY" in envs
    base2, _ = _service_endpoint("gemini")
    assert "generativelanguage.googleapis.com" in base2


def test_router_prefers_usable_provider(monkeypatch):
    """With autodetect on and only one provider's key set, routing must pick a
    usable model even if a higher-scoring one is unauthenticated."""
    import importlib
    monkeypatch.delenv("ARCCODE_NO_AUTODETECT", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setattr(services, "_ollama_up", lambda timeout=1.0: [])
    import arccode.config as config
    import arccode.router as router
    importlib.reload(config)
    importlib.reload(router)
    d = router.route("architect a distributed migration plan")
    # only groq is usable -> chosen model must be a groq model
    assert d.model.provider == "groq", d.model.id
    # restore
    monkeypatch.setenv("ARCCODE_NO_AUTODETECT", "1")
    importlib.reload(config)
    importlib.reload(router)
