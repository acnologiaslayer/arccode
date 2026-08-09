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
        default_base, key_env = _ROUTES.get(provider, (None, "OPENAI_API_KEY"))
        self.base_url = base_url or os.environ.get(
            f"{provider.upper()}_BASE_URL", default_base)
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
            if not secret and self.provider == "ollama":
                secret, kind = "ollama", "api_key"  # local, key-less
            if not secret:
                raise RuntimeError(
                    f"No credentials for {self.provider}. Set the API key or run "
                    f"'arccode auth login {self.provider}'.")
            if kind == "oauth":
                self._client = openai.OpenAI(
                    api_key="oauth", base_url=self.base_url,
                    default_headers={"Authorization": f"Bearer {secret}"})
            else:
                self._client = openai.OpenAI(api_key=secret, base_url=self.base_url)
        return self._client

    def complete(self, *, model, system, messages, tools, effort="medium", max_out=4096):
        client = self._client_or_raise()
        model_name = model.split(":", 1)[1] if ":" in model else model
        payload = [{"role": "system", "content": system or "You are a helpful assistant."}]
        payload += [_msg(m) for m in messages]
        kwargs = {}
        if tools:
            kwargs["tools"] = [_tool(t) for t in tools]
        resp = client.chat.completions.create(
            model=model_name, messages=payload, max_tokens=max_out, **kwargs)
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
