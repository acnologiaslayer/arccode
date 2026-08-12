"""OAuth 2.0 support for arccode.

Two flows:
  - Authorization Code + PKCE (RFC 7636) with a local loopback callback, for
    desktop use where a browser is available.
  - Device Authorization Grant (RFC 8628) for headless/SSH environments.

Tokens are stored per-provider in ~/.arccode/credentials.json (0600) and are
transparently refreshed when expired. Providers use the bearer access token
when no static API key is configured.

Provider OAuth endpoints are declared in the model config (see config.py:
OAUTH_PROVIDERS) or overridden via ~/.arccode/oauth.json.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import pathlib
import secrets
import threading
import time
import urllib.parse
import webbrowser

import httpx

# ---- storage ----------------------------------------------------------------

def _home() -> pathlib.Path:
    d = pathlib.Path(os.environ.get("ARCCODE_HOME", pathlib.Path.home() / ".arccode"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cred_path() -> pathlib.Path:
    return _home() / "credentials.json"


class TokenStore:
    """Per-provider token storage with 0600 perms and atomic writes."""

    def __init__(self, path: pathlib.Path | None = None):
        self.path = path or _cred_path()
        self.data: dict = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except json.JSONDecodeError:
                self.data = {}

    def get(self, provider: str) -> dict | None:
        return self.data.get(provider)

    def set(self, provider: str, token: dict) -> None:
        self.data[provider] = token
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def delete(self, provider: str) -> bool:
        if provider in self.data:
            del self.data[provider]
            self.path.write_text(json.dumps(self.data, indent=2))
            return True
        return False

    def providers(self) -> list[str]:
        return list(self.data)


# ---- PKCE helpers -----------------------------------------------------------

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


# ---- provider config --------------------------------------------------------

class OAuthProvider:
    def __init__(self, name: str, cfg: dict):
        self.name = name
        self.auth_url = cfg["auth_url"]
        self.token_url = cfg["token_url"]
        self.client_id = cfg.get("client_id", "")
        self.client_secret = cfg.get("client_secret")  # optional (public clients omit)
        self.scopes = cfg.get("scopes", [])
        self.device_url = cfg.get("device_url")  # enables device flow
        self.audience = cfg.get("audience")


def load_providers() -> dict[str, OAuthProvider]:
    from .config import OAUTH_PROVIDERS
    merged = dict(OAUTH_PROVIDERS)
    override = _home() / "oauth.json"
    if override.exists():
        try:
            for name, cfg in (json.loads(override.read_text()).get("providers") or {}).items():
                merged[name] = cfg
        except json.JSONDecodeError:
            pass
    return {name: OAuthProvider(name, cfg) for name, cfg in merged.items()}


# ---- token math -------------------------------------------------------------

def _augment_expiry(token: dict) -> dict:
    if "expires_in" in token and "expires_at" not in token:
        token["expires_at"] = time.time() + float(token["expires_in"]) - 30  # 30s skew
    return token


def is_expired(token: dict) -> bool:
    exp = token.get("expires_at")
    return exp is not None and time.time() >= exp


# ---- local callback server (auth-code + PKCE) -------------------------------

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):
        qs = urllib.parse.urlparse(self.path).query
        params = dict(urllib.parse.parse_qsl(qs))
        _CallbackHandler.result = params
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        ok = "code" in params
        msg = ("Authentication complete. You can close this tab and return to the terminal."
               if ok else f"Authentication failed: {params.get('error', 'unknown error')}")
        self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'>"
                         f"<h2>arccode</h2><p>{msg}</p></body></html>".encode())

    def log_message(self, *a):  # silence
        pass


def _run_callback_server(port: int) -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    return server


def login_auth_code(provider: OAuthProvider, *, port: int = 8765,
                    open_browser: bool = True, timeout: int = 300) -> dict:
    """Run the Authorization Code + PKCE flow. Returns a token dict."""
    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(16)
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if provider.scopes:
        params["scope"] = " ".join(provider.scopes)
    if provider.audience:
        params["audience"] = provider.audience
    auth_url = provider.auth_url + "?" + urllib.parse.urlencode(params)

    _CallbackHandler.result = {}
    server = _run_callback_server(port)
    print(f"Opening browser to authorize arccode with {provider.name}...")
    print(f"If it does not open, visit:\n  {auth_url}")
    if open_browser:
        try:
            webbrowser.open(auth_url)
        except Exception:  # noqa: BLE001
            pass

    deadline = time.time() + timeout
    while not _CallbackHandler.result and time.time() < deadline:
        time.sleep(0.3)
    try:
        server.server_close()
    except Exception:  # noqa: BLE001
        pass

    res = _CallbackHandler.result
    if not res:
        raise TimeoutError("timed out waiting for the OAuth redirect")
    if res.get("state") != state:
        raise ValueError("OAuth state mismatch (possible CSRF); aborting")
    if "code" not in res:
        raise RuntimeError(f"authorization failed: {res.get('error', 'no code returned')}")

    return exchange_code(provider, res["code"], verifier, redirect_uri)


def exchange_code(provider: OAuthProvider, code: str, verifier: str,
                  redirect_uri: str) -> dict:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider.client_id,
        "code_verifier": verifier,
    }
    if provider.client_secret:
        data["client_secret"] = provider.client_secret
    resp = httpx.post(provider.token_url, data=data,
                      headers={"Accept": "application/json"}, timeout=30)
    resp.raise_for_status()
    return _augment_expiry(resp.json())


# ---- device code flow (headless) -------------------------------------------

def login_device(provider: OAuthProvider, *, poll_timeout: int = 300) -> dict:
    if not provider.device_url:
        raise RuntimeError(f"{provider.name} does not advertise a device_url")
    data = {"client_id": provider.client_id}
    if provider.scopes:
        data["scope"] = " ".join(provider.scopes)
    r = httpx.post(provider.device_url, data=data,
                   headers={"Accept": "application/json"}, timeout=30)
    r.raise_for_status()
    dev = r.json()
    verification = dev.get("verification_uri_complete") or dev.get("verification_uri")
    print(f"To authenticate, visit:\n  {verification}")
    if "user_code" in dev and "verification_uri_complete" not in dev:
        print(f"and enter the code: {dev['user_code']}")

    interval = int(dev.get("interval", 5))
    deadline = time.time() + poll_timeout
    while time.time() < deadline:
        time.sleep(interval)
        poll = httpx.post(provider.token_url, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": dev["device_code"],
            "client_id": provider.client_id,
        }, headers={"Accept": "application/json"}, timeout=30)
        body = poll.json()
        if poll.status_code == 200 and "access_token" in body:
            return _augment_expiry(body)
        err = body.get("error")
        if err in ("authorization_pending", "slow_down"):
            if err == "slow_down":
                interval += 5
            continue
        raise RuntimeError(f"device authorization failed: {err or poll.text}")
    raise TimeoutError("timed out waiting for device authorization")


# ---- refresh ----------------------------------------------------------------

def refresh_token(provider: OAuthProvider, token: dict) -> dict:
    rt = token.get("refresh_token")
    if not rt:
        raise RuntimeError("no refresh_token available; re-run 'arccode auth login'")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "client_id": provider.client_id,
    }
    if provider.client_secret:
        data["client_secret"] = provider.client_secret
    resp = httpx.post(provider.token_url, data=data,
                      headers={"Accept": "application/json"}, timeout=30)
    resp.raise_for_status()
    new = _augment_expiry(resp.json())
    # some providers omit refresh_token on refresh; keep the old one
    new.setdefault("refresh_token", rt)
    return new


# ---- high-level access ------------------------------------------------------

def get_access_token(provider_name: str, *, store: TokenStore | None = None) -> str | None:
    """Return a valid bearer access token for a provider, refreshing if needed.

    Returns None if the user has not logged in with OAuth for this provider.
    """
    store = store or TokenStore()
    token = store.get(provider_name)
    if not token or "access_token" not in token:
        return None
    if is_expired(token):
        providers = load_providers()
        prov = providers.get(provider_name)
        if not prov:
            return None
        try:
            token = refresh_token(prov, token)
            store.set(provider_name, token)
        except Exception:  # noqa: BLE001
            return None
    return token.get("access_token")


def login(provider_name: str, *, device: bool = False,
          store: TokenStore | None = None) -> dict:
    store = store or TokenStore()
    providers = load_providers()
    prov = providers.get(provider_name)
    if not prov:
        raise KeyError(f"no OAuth config for provider {provider_name!r}. "
                       f"Known: {list(providers)}")
    token = login_device(prov) if device else login_auth_code(prov)
    store.set(provider_name, token)
    return token


def logout(provider_name: str, *, store: TokenStore | None = None) -> bool:
    store = store or TokenStore()
    return store.delete(provider_name)


def status(*, store: TokenStore | None = None) -> list[dict]:
    store = store or TokenStore()
    out = []
    for name in store.providers():
        tok = store.get(name) or {}
        out.append({
            "provider": name,
            "has_access": "access_token" in tok,
            "has_refresh": "refresh_token" in tok,
            "expired": is_expired(tok),
            "expires_at": tok.get("expires_at"),
        })
    return out
