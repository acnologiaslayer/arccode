"""Simple JSONL-backed long-term memory store."""
from __future__ import annotations

import json
import pathlib
import time
import uuid


class MemoryStore:
    def __init__(self, path: str):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.items: list[dict] = []
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    try:
                        self.items.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    def remember(self, content: str, category: str = "fact",
                 tags: list[str] | None = None) -> str:
        mid = uuid.uuid4().hex[:8]
        item = {"id": mid, "content": content, "category": category,
                "tags": tags or [], "ts": time.time()}
        self.items.append(item)
        with self.path.open("a") as f:
            f.write(json.dumps(item) + "\n")
        return mid

    def search(self, query: str, limit: int = 5) -> list[dict]:
        q = query.lower()
        scored = []
        for it in self.items:
            hay = (it["content"] + " " + " ".join(it.get("tags", []))).lower()
            score = sum(1 for w in q.split() if w in hay)
            if score:
                scored.append((score, it))
        scored.sort(key=lambda x: (-x[0], -x[1]["ts"]))
        return [it for _, it in scored[:limit]]

    def all(self) -> list[dict]:
        return list(self.items)
