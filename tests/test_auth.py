"""OAuth tests with a REAL in-process mock OAuth server.

Exercises the full flows against a running HTTP server (no live provider):
PKCE code exchange, refresh, device-code polling, token store with 0600 perms,
expiry math, and the credentials resolver's bearer-token injection.
"""
import http.server
import json
import os
import threading
import time
import urllib.parse

import pytest

from arccode import auth
from arccode.auth import (
    OAuthProvider,
    TokenStore,
    exchange_code,
    is_expired,
    make_pkce,
    refresh_token,
)

# ---- a real mock OAuth server ----------------------------------------------

class MockOAuthHandler(http.server.BaseHTTPRequestHandler):
    issued = {"access": 0, "refresh": 0}
    device_ready_after = 0  # polls before returning a token
    device_polls = 0

    def _json(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        form = dict(urllib.parse.parse_qsl(body))
        path = self.path

        if path == "/token":
            grant = form.get("grant_type")
            if grant == "authorization_code":
                if not form.get("code_verifier"):
                    return self._json(400, {"error": "missing code_verifier"})
                MockOAuthHandler.issued["access"] += 1
                return self._json(200, {
                    "access_token": f"access-{MockOAuthHandler.issued['access']}",
                    "refresh_token": "refresh-abc",
                    "token_type": "Bearer", "expires_in": 3600,
                    "scope": "openid profile"})
            if grant == "refresh_token":
                MockOAuthHandler.issued["refresh"] += 1
                return self._json(200, {
                    "access_token": f"access-refreshed-{MockOAuthHandler.issued['refresh']}",
                    "token_type": "Bearer", "expires_in": 3600})
            if grant == "urn:ietf:params:oauth:grant-type:device_code":
                MockOAuthHandler.device_polls += 1
                if MockOAuthHandler.device_polls < MockOAuthHandler.device_ready_after:
                    return self._json(400, {"error": "authorization_pending"})
                return self._json(200, {
                    "access_token": "device-access", "token_type": "Bearer",
                    "expires_in": 3600})
            return self._json(400, {"error": "unsupported_grant_type"})

        if path == "/device":
            return self._json(200, {
                "device_code": "dev-123", "user_code": "WXYZ-1234",
                "verification_uri": "https://example/device",
                "verification_uri_complete": "https://example/device?code=WXYZ-1234",
                "interval": 1, "expires_in": 300})
        self._json(404, {"error": "not_found"})

    def log_message(self, *a):
        pass


@pytest.fixture
def mock_server():
    MockOAuthHandler.issued = {"access": 0, "refresh": 0}
    MockOAuthHandler.device_polls = 0
    MockOAuthHandler.device_ready_after = 0
    srv = http.server.HTTPServer(("127.0.0.1", 0), MockOAuthHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


def _provider(base):
    return OAuthProvider("mock", {
        "auth_url": base + "/authorize",
        "token_url": base + "/token",
        "device_url": base + "/device",
        "client_id": "test-client",
        "scopes": ["openid", "profile"],
    })


# ---- PKCE ----

def test_pkce_challenge_is_s256_of_verifier():
    import base64
    import hashlib
    v, c = make_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    assert c == expected
    assert v != c and len(v) > 40


# ---- token exchange (real HTTP to mock) ----

def test_exchange_code_roundtrip(mock_server):
    prov = _provider(mock_server)
    verifier, _ = make_pkce()
    tok = exchange_code(prov, "the-code", verifier, "http://127.0.0.1:8765/callback")
    assert tok["access_token"] == "access-1"
    assert tok["refresh_token"] == "refresh-abc"
    assert "expires_at" in tok and tok["expires_at"] > time.time()


def test_exchange_requires_verifier(mock_server):
    prov = _provider(mock_server)
    # empty verifier -> server rejects -> httpx raises for 400
    import httpx
    with pytest.raises(httpx.HTTPStatusError):
        exchange_code(prov, "code", "", "http://127.0.0.1:8765/callback")


# ---- refresh ----

def test_refresh_token(mock_server):
    prov = _provider(mock_server)
    tok = {"access_token": "old", "refresh_token": "refresh-abc", "expires_at": 0}
    new = refresh_token(prov, tok)
    assert new["access_token"].startswith("access-refreshed-")
    assert new["refresh_token"] == "refresh-abc"  # preserved when omitted


# ---- device flow ----

def test_device_flow_polls_until_ready(mock_server):
    MockOAuthHandler.device_ready_after = 3  # pending twice, then success
    prov = _provider(mock_server)
    tok = auth.login_device(prov, poll_timeout=30)
    assert tok["access_token"] == "device-access"
    assert MockOAuthHandler.device_polls >= 3


def test_auth_code_full_loopback(mock_server, monkeypatch):
    """Drive the real login_auth_code flow: loopback callback + code exchange."""
    import urllib.parse
    import urllib.request

    prov = _provider(mock_server)

    def fake_browser(url):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        cb = f"http://127.0.0.1:8791/callback?code=THECODE&state={q['state'][0]}"

        def hit():
            time.sleep(0.4)
            urllib.request.urlopen(cb).read()

        threading.Thread(target=hit, daemon=True).start()

    monkeypatch.setattr(auth.webbrowser, "open", fake_browser)
    tok = auth.login_auth_code(prov, port=8791, open_browser=True, timeout=15)
    assert tok["access_token"] == "access-1"      # exchanged via /token
    assert tok["refresh_token"] == "refresh-abc"


def test_auth_code_rejects_state_mismatch(mock_server, monkeypatch):
    import urllib.request
    prov = _provider(mock_server)

    def bad_browser(url):
        def hit():
            time.sleep(0.4)
            urllib.request.urlopen("http://127.0.0.1:8792/callback?code=X&state=WRONG").read()
        threading.Thread(target=hit, daemon=True).start()

    monkeypatch.setattr(auth.webbrowser, "open", bad_browser)
    with pytest.raises(ValueError, match="state mismatch"):
        auth.login_auth_code(prov, port=8792, open_browser=True, timeout=15)


# ---- token store ----

def test_token_store_roundtrip_and_perms(tmp_path):
    store = TokenStore(tmp_path / "creds.json")
    store.set("openai", {"access_token": "x", "expires_at": time.time() + 100})
    assert TokenStore(tmp_path / "creds.json").get("openai")["access_token"] == "x"
    mode = oct(os.stat(tmp_path / "creds.json").st_mode)[-3:]
    assert mode == "600"
    assert store.delete("openai") is True
    assert TokenStore(tmp_path / "creds.json").get("openai") is None


def test_is_expired():
    assert is_expired({"expires_at": time.time() - 1})
    assert not is_expired({"expires_at": time.time() + 100})
    assert not is_expired({})  # no expiry known -> treat as valid


# ---- high-level get_access_token with auto-refresh ----

def test_get_access_token_refreshes_when_expired(mock_server, tmp_path, monkeypatch):
    store = TokenStore(tmp_path / "creds.json")
    store.set("mock", {"access_token": "stale", "refresh_token": "refresh-abc",
                       "expires_at": time.time() - 10})
    monkeypatch.setattr(auth, "load_providers",
                        lambda: {"mock": _provider(mock_server)})
    tok = auth.get_access_token("mock", store=store)
    assert tok.startswith("access-refreshed-")
    # persisted back
    assert TokenStore(tmp_path / "creds.json").get("mock")["access_token"].startswith("access-refreshed-")


def test_get_access_token_none_when_not_logged_in(tmp_path):
    store = TokenStore(tmp_path / "creds.json")
    assert auth.get_access_token("openai", store=store) is None


# ---- credentials resolver: API key precedence, then OAuth bearer ----

def test_resolver_prefers_api_key(monkeypatch):
    from arccode import credentials
    monkeypatch.setenv("OPENAI_API_KEY", "sk-static")
    secret, kind = credentials.resolve("openai")
    assert kind == "api_key" and secret == "sk-static"


def test_resolver_falls_back_to_oauth(monkeypatch):
    from arccode import credentials
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "bearer_token",
                        lambda p: "oauth-token" if p == "openai" else None)
    secret, kind = credentials.resolve("openai")
    assert kind == "oauth" and secret == "oauth-token"


def test_resolver_none_when_no_creds(monkeypatch):
    from arccode import credentials
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "bearer_token", lambda p: None)
    secret, kind = credentials.resolve("anthropic")
    assert kind == "none" and secret is None


# ---- provider Bearer injection (whole-result integration) -------------------

def test_provider_uses_bearer_when_oauth(monkeypatch):
    """The OpenAI-compat adapter must build its client with a Bearer header when
    credentials resolve to OAuth (no API key). Captures the header without a
    live call by stubbing the openai client constructor."""
    from arccode import credentials
    from arccode.providers.openai_compat import OpenAICompatProvider

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "bearer_token",
                        lambda p: "tok-123" if p == "openai" else None)

    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import openai
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)

    prov = OpenAICompatProvider(provider="openai")
    prov._client_or_raise()
    assert captured.get("default_headers", {}).get("Authorization") == "Bearer tok-123"


def test_anthropic_uses_auth_token_when_oauth(monkeypatch):
    from arccode import credentials
    from arccode.providers.anthropic import AnthropicProvider

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "bearer_token",
                        lambda p: "atok" if p == "anthropic" else None)

    captured = {}

    class FakeAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)

    prov = AnthropicProvider()
    prov._client_or_raise()
    assert captured.get("auth_token") == "atok"
    assert "api_key" not in captured
