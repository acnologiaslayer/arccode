"""OpenAI-compatible provider adapter.

Handles OpenAI, Ollama (OpenAI-compatible endpoint), and OpenRouter by
swapping base_url + api_key. Uses the Chat Completions tool-calling shape.
"""
from __future__ import annotations

import json
import os

from .base import Completion, Message, ToolCall

# provider -> (base_url env / default, api_key env)
_ROUTES = {
    "openai": (None, "OPENAI_API_KEY"),
    "ollama": ("http://localhost:11434/v1", "OLLAMA_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
}


class OpenAICompatProvider:
    def __init__(self, provider: str = "openai", api_key: str | None = None,
                 base_url: str | None = None):
        self.provider = provider
        # Resolve the endpoint from the service registry first, then legacy
        # _ROUTES, then an env override. This is what lets one adapter serve
        # groq/gemini/cerebras/mistral/openrouter/github/ollama/openai.
        svc_base, svc_keyenvs = _service_endpoint(provider)
        default_base = svc_base
        if default_base is None:
            default_base, _ = _ROUTES.get(provider, (None, None))
        self.base_url = base_url or os.environ.get(
            f"{provider.upper()}_BASE_URL", default_base)
        self._key_envs = svc_keyenvs or _legacy_key_envs(provider)
        self._explicit_key = api_key
        self._client = None

    def _client_or_raise(self):
        if self._client is None:
            try:
                import openai
            except ImportError as e:
                raise RuntimeError(
                    "openai SDK not installed. Run: pip install 'arccode[openai]'"
                ) from e
            from ..credentials import resolve
            if self._explicit_key:
                secret, kind = self._explicit_key, "api_key"
            else:
                secret, kind = resolve(self.provider)
            # Fall back to any of the service's declared key env vars.
            if not secret:
                for env in self._key_envs:
                    v = os.environ.get(env)
                    if v:
                        secret, kind = v, "api_key"
                        break
            if not secret and self.provider == "ollama":
                secret, kind = "ollama", "api_key"  # local, key-less
            if not secret:
                hint = _signup_hint(self.provider)
                raise RuntimeError(
                    f"No credentials for {self.provider}. Set the API key"
                    + (f" ({hint})" if hint else "")
                    + f" or run 'arccode auth login {self.provider}'.")
            if kind == "oauth":
                self._client = openai.OpenAI(
                    api_key="oauth", base_url=self.base_url,
                    default_headers={"Authorization": f"Bearer {secret}"})
            else:
                self._client = openai.OpenAI(api_key=secret, base_url=self.base_url)
        return self._client

    def complete(self, *, model, system, messages, tools, effort="medium", max_out=4096,
                 on_text=None):
        client = self._client_or_raise()
        model_name = model.split(":", 1)[1] if ":" in model else model
        payload = [{"role": "system", "content": system or "You are a helpful assistant."}]
        payload += [_msg(m) for m in messages]
        kwargs = {}
        if tools:
            kwargs["tools"] = [_tool(t) for t in tools]
        if on_text is not None:
            return self._complete_stream(client, model_name, payload, max_out, on_text, kwargs)
        # Newer OpenAI models reject `max_tokens` and require
        # `max_completion_tokens`. Try the classic param, then fall back.
        try:
            resp = client.chat.completions.create(
                model=model_name, messages=payload, max_tokens=max_out, **kwargs)
        except Exception as e:
            if _wants_completion_tokens(e):
                resp = client.chat.completions.create(
                    model=model_name, messages=payload,
                    max_completion_tokens=max_out, **kwargs)
            else:
                raise
        choice = resp.choices[0]
        msg = choice.message
        calls = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(tc.id, tc.function.name, args))
        usage = resp.usage
        return Completion(
            msg.content or "", calls,
            {"in": getattr(usage, "prompt_tokens", 0),
             "out": getattr(usage, "completion_tokens", 0)},
            choice.finish_reason or "stop",
        )

    def _complete_stream(self, client, model_name, payload, max_out, on_text, kwargs):
        """Streaming variant: emits text deltas via on_text(delta) as they arrive.

        Accumulates any tool-call deltas so the agent loop still works with tools.
        """
        opts = {"stream": True, "stream_options": {"include_usage": True}, **kwargs}

        def _create(token_kw):
            return client.chat.completions.create(
                model=model_name, messages=payload, **token_kw, **opts)

        try:
            stream = _create({"max_tokens": max_out})
        except Exception as e:
            if _wants_completion_tokens(e):
                stream = _create({"max_completion_tokens": max_out})
            elif _no_stream_options(e):
                # Some OpenAI-compatible servers reject stream_options; drop it.
                opts.pop("stream_options", None)
                stream = _create({"max_tokens": max_out})
            else:
                raise

        text = ""
        finish = "stop"
        usage = {"in": 0, "out": 0}
        tool_frags: dict[int, dict] = {}
        for chunk in stream:
            u = getattr(chunk, "usage", None)
            if u:
                usage = {"in": getattr(u, "prompt_tokens", 0),
                         "out": getattr(u, "completion_tokens", 0)}
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish = choice.finish_reason
            delta = choice.delta
            if getattr(delta, "content", None):
                text += delta.content
                try:
                    on_text(delta.content)
                except Exception:  # noqa: BLE001, S110
                    pass
            for tc in (getattr(delta, "tool_calls", None) or []):
                frag = tool_frags.setdefault(tc.index, {"id": None, "name": "", "args": ""})
                if tc.id:
                    frag["id"] = tc.id
                if tc.function and tc.function.name:
                    frag["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    frag["args"] += tc.function.arguments

        calls = []
        for _, frag in sorted(tool_frags.items()):
            try:
                args = json.loads(frag["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(frag["id"] or "", frag["name"], args))
        return Completion(text, calls, usage, finish)


def _service_endpoint(provider: str):
    """(base_url, key_envs) for a provider from the service registry, or (None, ())."""
    try:
        from ..services import SERVICES
        svc = SERVICES.get(provider)
        if svc:
            return svc.base_url, svc.key_envs
    except Exception:  # noqa: BLE001
        pass
    return None, ()


def _legacy_key_envs(provider: str) -> tuple:
    _, key_env = _ROUTES.get(provider, (None, "OPENAI_API_KEY"))
    return (key_env,) if key_env else ()


def _signup_hint(provider: str) -> str:
    try:
        from ..services import SERVICES
        svc = SERVICES.get(provider)
        return svc.signup if svc else ""
    except Exception:  # noqa: BLE001
        return ""


def _wants_completion_tokens(err: Exception) -> bool:
    """True if the error indicates the model wants max_completion_tokens."""
    msg = str(err).lower()
    return "max_completion_tokens" in msg or (
        "max_tokens" in msg and "unsupported" in msg) or (
        "max_tokens" in msg and "not supported" in msg)


def _no_stream_options(err: Exception) -> bool:
    """True if the server rejects the stream_options param."""
    msg = str(err).lower()
    return "stream_options" in msg


def _tool(t: dict) -> dict:
    return {"type": "function", "function": {
        "name": t["name"], "description": t["description"], "parameters": t["schema"]}}


def _msg(m: Message) -> dict:
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    if m.role == "assistant" and m.tool_calls:
        return {"role": "assistant", "content": m.content or None, "tool_calls": [
            {"id": c.id, "type": "function",
             "function": {"name": c.name, "arguments": json.dumps(c.args)}}
            for c in m.tool_calls]}
    return {"role": m.role, "content": m.content}
