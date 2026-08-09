"""Web tools: fetch a URL and lightweight web search (DuckDuckGo HTML)."""
from __future__ import annotations

import html
import re
import urllib.parse

import httpx

from .base import tool

_UA = {"User-Agent": "Mozilla/5.0 (arccode agent)"}


def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+\n", "\n", re.sub(r"[ \t]+", " ", text)).strip()


@tool("web_fetch", "Fetch a URL and return text (or raw html with format=html).",
      {"type": "object", "properties": {
          "url": {"type": "string"},
          "format": {"type": "string", "enum": ["text", "html"]}},
       "required": ["url"]})
def web_fetch(args, ctx):
    try:
        r = httpx.get(args["url"], headers=_UA, follow_redirects=True, timeout=30)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return f"ERROR fetching {args['url']}: {e}"
    body = r.text
    if args.get("format") == "html":
        return body[:200_000]
    return _strip_html(body)[:120_000]


@tool("web_search", "Search the web (DuckDuckGo HTML). Returns title + url + snippet.",
      {"type": "object", "properties": {
          "query": {"type": "string"}, "num": {"type": "integer"}},
       "required": ["query"]})
def web_search(args, ctx):
    q = urllib.parse.quote(args["query"])
    url = f"https://html.duckduckgo.com/html/?q={q}"
    try:
        r = httpx.get(url, headers=_UA, timeout=30)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return f"ERROR searching: {e}"
    results = re.findall(
        r'result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?result__snippet"[^>]*>(.*?)</a>',
        r.text, re.S)
    num = int(args.get("num", 8))
    out = []
    for href, title, snip in results[:num]:
        out.append(f"- {_strip_html(title)}\n  {href}\n  {_strip_html(snip)}")
    return "\n".join(out) or "(no results)"
