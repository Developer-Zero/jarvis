from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    semantic_memory_max_context_chars,
    semantic_memory_max_items,
    semantic_memory_min_score,
    semantic_memory_model,
    semantic_memory_top_k,
)
from runtime.userdata import RUNTIME_DIR, get_openai_api_key


MEMORY_PATH = RUNTIME_DIR / "memory.json"
WORD_RE = re.compile(r"\w+", re.UNICODE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(text: str) -> str:
    return " ".join(str(text or "").split())


def _memory_id(text: str) -> str:
    digest = hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()
    return digest[:16]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0

    return dot / (left_norm * right_norm)


def _lexical_similarity(query: str, text: str) -> float:
    query_terms = set(WORD_RE.findall(query.lower()))
    text_terms = set(WORD_RE.findall(text.lower()))
    if not query_terms or not text_terms:
        return 0.0

    return len(query_terms & text_terms) / len(query_terms | text_terms)


class SemanticMemory:
    def __init__(self, path: Path = MEMORY_PATH, client: Any | None = None):
        self.path = path
        self.client = client
        self._lock = threading.RLock()

    def _default_data(self) -> dict[str, Any]:
        return {"version": 1, "items": []}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_data()

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self._default_data()

        if not isinstance(data, dict):
            return self._default_data()
        if not isinstance(data.get("items"), list):
            data["items"] = []
        data.setdefault("version", 1)
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _embedding(self, text: str) -> list[float] | None:
        if not text.strip():
            return None

        client = self.client
        if client is None:
            try:
                from openai import OpenAI

                api_key = get_openai_api_key()
                client = OpenAI(api_key=api_key) if api_key else OpenAI()
            except Exception:
                return None

        try:
            response = client.embeddings.create(
                model=semantic_memory_model,
                input=text,
            )
            return list(response.data[0].embedding)
        except Exception as exc:
            print(f"Semantic memory embedding failed: {exc}")
            return None

    def remember(self, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        text = _clean_text(text)
        if not text:
            raise ValueError("Memory text cannot be empty")

        metadata = dict(metadata or {})
        memory_id = _memory_id(text)

        with self._lock:
            data = self._load()
            now = _now()
            embedding = self._embedding(text)

            for item in data["items"]:
                if item.get("id") == memory_id:
                    item["text"] = text
                    item["metadata"] = {**item.get("metadata", {}), **metadata}
                    if embedding is not None:
                        item["embedding"] = embedding
                    item["updated_at"] = now
                    self._save(data)
                    return self._public_item(item)

            item = {
                "id": memory_id,
                "text": text,
                "metadata": metadata,
                "embedding": embedding,
                "created_at": now,
                "updated_at": now,
                "hits": 0,
            }
            data["items"].append(item)
            data["items"] = data["items"][-semantic_memory_max_items:]
            self._save(data)
            return self._public_item(item)

    def search(
        self,
        query: str,
        *,
        limit: int = semantic_memory_top_k,
        min_score: float = semantic_memory_min_score,
    ) -> list[dict[str, Any]]:
        query = _clean_text(query)
        if not query:
            return []

        with self._lock:
            data = self._load()
            if not data["items"]:
                return []

            query_embedding = self._embedding(query)
            scored: list[tuple[float, dict[str, Any]]] = []

            for item in data["items"]:
                text = str(item.get("text", ""))
                embedding = item.get("embedding")

                if query_embedding and isinstance(embedding, list):
                    score = _cosine_similarity(query_embedding, embedding)
                else:
                    score = _lexical_similarity(query, text)

                if score >= min_score:
                    scored.append((score, item))

            scored.sort(key=lambda pair: pair[0], reverse=True)
            results = []
            for score, item in scored[: max(1, int(limit))]:
                item["hits"] = int(item.get("hits", 0)) + 1
                public_item = self._public_item(item)
                public_item["score"] = round(float(score), 4)
                results.append(public_item)

            if results:
                self._save(data)

            return results

    def forget(self, memory_id: str) -> bool:
        memory_id = str(memory_id or "").strip()
        if not memory_id:
            return False

        with self._lock:
            data = self._load()
            original_count = len(data["items"])
            data["items"] = [
                item for item in data["items"] if item.get("id") != memory_id
            ]
            changed = len(data["items"]) != original_count
            if changed:
                self._save(data)
            return changed

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load()
            items = data["items"][-max(1, int(limit)) :]
            return [self._public_item(item) for item in reversed(items)]

    def _public_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id", ""),
            "text": item.get("text", ""),
            "metadata": item.get("metadata", {}),
            "created_at": item.get("created_at", ""),
            "updated_at": item.get("updated_at", ""),
            "hits": item.get("hits", 0),
        }


def format_memories_for_prompt(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return ""

    lines = ["Relevant long-term memories:"]
    remaining = semantic_memory_max_context_chars

    for memory in memories:
        text = _clean_text(str(memory.get("text", "")))
        if not text:
            continue

        line = f"- {text}"
        if len(line) > remaining:
            line = line[: max(0, remaining - 3)].rstrip() + "..."
        lines.append(line)
        remaining -= len(line)
        if remaining <= 0:
            break

    return "\n".join(lines) if len(lines) > 1 else ""
