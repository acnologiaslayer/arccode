"""Minimal MCP (Model Context Protocol) stdio client.

Launches a server process, performs the JSON-RPC handshake, lists tools, and
exposes them so they can be registered into arccode's tool registry.
Config lives at ~/.arccode/mcp.json:  {"servers": {"name": {"command": [...],
"env": {...}}}}
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import threading


class MCPClient:
    def __init__(self, name: str, command: list[str], env: dict | None = None):
        self.name = name
        self.command = command
        self.env = {**os.environ, **(env or {})}
        self.proc: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()
        self.tools: list[dict] = []

    def start(self) -> None:
        self.proc = subprocess.Popen(
            self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, env=self.env, bufsize=1)
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {}, "clientInfo": {"name": "arccode", "version": "0.1.0"}})
        self._notify("notifications/initialized", {})
        resp = self._rpc("tools/list", {})
        self.tools = (resp or {}).get("tools", [])

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _send(self, obj: dict) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def _rpc(self, method: str, params: dict) -> dict | None:
        with self._lock:
            rid = self._next_id()
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            assert self.proc and self.proc.stdout
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == rid:
                    return msg.get("result") or msg.get("error")
        return None

    def _notify(self, method: str, params: dict) -> None:
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def call_tool(self, name: str, arguments: dict) -> str:
        res = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if not res:
            return "(no result)"
        content = res.get("content") if isinstance(res, dict) else None
        if isinstance(content, list):
            return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
        return json.dumps(res)

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()


def load_mcp_config(path: str | None = None) -> dict:
    p = pathlib.Path(path or (pathlib.Path.home() / ".arccode" / "mcp.json"))
    if not p.exists():
        return {"servers": {}}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {"servers": {}}


def connect_all(config: dict) -> dict[str, MCPClient]:
    clients: dict[str, MCPClient] = {}
    for name, cfg in (config.get("servers") or {}).items():
        cmd = cfg.get("command")
        if isinstance(cmd, str):
            cmd = [cmd, *cfg.get("args", [])]
        client = MCPClient(name, cmd, cfg.get("env"))
        try:
            client.start()
            clients[name] = client
        except Exception:  # noqa: BLE001
            continue
    return clients


def register_mcp_tools(clients: dict[str, MCPClient]) -> None:
    """Register each MCP tool into arccode's REGISTRY as 'mcp__<server>__<tool>'."""
    from .tools.base import REGISTRY, Tool

    for server, client in clients.items():
        for t in client.tools:
            tname = f"mcp__{server}__{t['name']}"
            schema = t.get("inputSchema") or {"type": "object", "properties": {}}

            def _make(cl, orig):
                def handler(args, ctx):
                    return cl.call_tool(orig, args)
                return handler

            REGISTRY[tname] = Tool(
                tname, t.get("description", f"MCP tool {t['name']} from {server}"),
                schema, _make(client, t["name"]), danger=True)
