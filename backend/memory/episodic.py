from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import (
    episodic_memory_max_context_chars,
    episodic_memory_max_items,
    episodic_memory_min_score,
    episodic_memory_top_k,
    memory_model,
)
from backend.memory.semantic import _clean_text, _cosine_similarity, _lexical_similarity, _now
from runtime.userdata import RUNTIME_DIR, get_openai_api_key


EPISODIC_MEMORY_PATH = RUNTIME_DIR / "episodic_memory.json"


@dataclass
class EpisodicMemoryItem:
    id: str
    timestamp: str
    session_id: str
    type: str
    summary: str
    raw_text: str | None = None
    raw_ref: str | None = None
    topics: list[str] = field(default_factory=list)
    project_refs: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    importance: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None
    updated_at: str | None = None
    hits: int = 0


@dataclass
class EpisodicQuery:
    query: str = ""
    start_time: str | None = None
    end_time: str | None = None
    topics: list[str] = field(default_factory=list)
    project_refs: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    limit: int = episodic_memory_top_k
    min_score: float = episodic_memory_min_score


class EpisodicMemory:
    def __init__(
        self,
        path: Path = EPISODIC_MEMORY_PATH,
        client: Any | None = None,
    ):
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
                model=memory_model,
                input=text,
            )
            return list(response.data[0].embedding)
        except Exception as exc:
            print(f"Episodic memory embedding failed: {exc}")
            return None

    def remember_event(
        self,
        *,
        session_id: str,
        event_type: str,
        summary: str,
        raw_text: str | None = None,
        raw_ref: str | None = None,
        topics: list[str] | None = None,
        project_refs: list[str] | None = None,
        decisions: list[str] | None = None,
        action_items: list[str] | None = None,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        summary = _clean_text(summary)
        raw_text = _clean_text(raw_text or "") or None
        if not summary and raw_text:
            summary = raw_text[:240]
        if not summary:
            raise ValueError("Episodic memory summary cannot be empty")

        now = _now()
        fingerprint = "|".join(
            [session_id, event_type, summary, raw_text or raw_ref or "", now]
        )
        item_id = self._item_id(fingerprint)
        search_text = self._searchable_text(
            summary=summary,
            topics=topics or [],
            project_refs=project_refs or [],
            decisions=decisions or [],
            action_items=action_items or [],
        )

        item = EpisodicMemoryItem(
            id=item_id,
            timestamp=now,
            session_id=session_id,
            type=event_type or "turn",
            summary=summary,
            raw_text=raw_text,
            raw_ref=raw_ref,
            topics=self._clean_list(topics),
            project_refs=self._clean_list(project_refs),
            decisions=self._clean_list(decisions),
            action_items=self._clean_list(action_items),
            importance=self._clean_importance(importance),
            metadata=dict(metadata or {}),
            embedding=self._embedding(search_text),
            updated_at=now,
        )

        with self._lock:
            data = self._load()
            data["items"].append(asdict(item))
            data["items"] = self._prune_items(data["items"])
            self._save(data)
            return self._public_item(asdict(item))

    def upsert_session_summary(
        self,
        *,
        session_id: str,
        summary: str,
        topics: list[str] | None = None,
        project_refs: list[str] | None = None,
        decisions: list[str] | None = None,
        action_items: list[str] | None = None,
        source_event_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        summary = _clean_text(summary)
        if not summary:
            raise ValueError("Session summary cannot be empty")

        now = _now()
        summary_id = self._item_id(f"session_summary|{session_id}")
        incoming_metadata = dict(metadata or {})
        incoming_metadata["source_event_ids"] = self._clean_list(source_event_ids)
        search_text = self._searchable_text(
            summary=summary,
            topics=topics or [],
            project_refs=project_refs or [],
            decisions=decisions or [],
            action_items=action_items or [],
        )

        with self._lock:
            data = self._load()
            for item in data["items"]:
                if item.get("id") == summary_id:
                    item["summary"] = summary
                    item["topics"] = self._merge_lists(item.get("topics"), topics)
                    item["project_refs"] = self._merge_lists(
                        item.get("project_refs"), project_refs
                    )
                    item["decisions"] = self._merge_lists(
                        item.get("decisions"), decisions
                    )
                    item["action_items"] = self._merge_lists(
                        item.get("action_items"), action_items
                    )
                    item["importance"] = max(float(item.get("importance", 0.5)), 0.7)
                    item["metadata"] = {
                        **dict(item.get("metadata") or {}),
                        **incoming_metadata,
                    }
                    item["updated_at"] = now
                    item["embedding"] = self._embedding(search_text)
                    self._save(data)
                    return self._public_item(item)

            item = EpisodicMemoryItem(
                id=summary_id,
                timestamp=now,
                session_id=session_id,
                type="session_summary",
                summary=summary,
                topics=self._clean_list(topics),
                project_refs=self._clean_list(project_refs),
                decisions=self._clean_list(decisions),
                action_items=self._clean_list(action_items),
                importance=0.7,
                metadata=incoming_metadata,
                embedding=self._embedding(search_text),
                updated_at=now,
            )
            data["items"].append(asdict(item))
            data["items"] = self._prune_items(data["items"])
            self._save(data)
            return self._public_item(asdict(item))

    def retrieve(self, query: EpisodicQuery | str) -> list[dict[str, Any]]:
        if isinstance(query, str):
            query = EpisodicQuery(query=query)

        with self._lock:
            data = self._load()
            if not data["items"]:
                return []

            query_text = _clean_text(query.query)
            query_embedding = self._embedding(query_text) if query_text else None
            start_dt = self._parse_time(query.start_time)
            end_dt = self._parse_time(query.end_time)
            topics = self._normalized_set(query.topics)
            project_refs = self._normalized_set(query.project_refs)
            types = self._normalized_set(query.types)
            scored: list[tuple[float, dict[str, Any]]] = []

            for item in data["items"]:
                if types and str(item.get("type", "")).casefold() not in types:
                    continue
                timestamp = self._parse_time(item.get("timestamp"))
                if start_dt and timestamp and timestamp < start_dt:
                    continue
                if end_dt and timestamp and timestamp > end_dt:
                    continue

                topic_score = self._overlap_score(topics, item.get("topics"))
                project_score = self._overlap_score(
                    project_refs, item.get("project_refs")
                )
                text = self._item_search_text(item)
                embedding = item.get("embedding")
                if query_embedding and isinstance(embedding, list):
                    text_score = _cosine_similarity(query_embedding, embedding)
                elif query_text:
                    text_score = _lexical_similarity(query_text, text)
                else:
                    text_score = 0.0

                score = max(text_score, topic_score, project_score)
                if start_dt or end_dt:
                    score = max(score, 0.25)
                if not query_text and not topics and not project_refs:
                    score = max(score, float(item.get("importance", 0.5)) * 0.25)
                score += min(max(float(item.get("importance", 0.5)), 0.0), 1.0) * 0.05

                if score >= query.min_score:
                    scored.append((score, item))

            scored.sort(
                key=lambda pair: (
                    pair[0],
                    pair[1].get("updated_at") or pair[1].get("timestamp") or "",
                ),
                reverse=True,
            )
            results = []
            for score, item in scored[: max(1, int(query.limit))]:
                item["hits"] = int(item.get("hits", 0)) + 1
                public_item = self._public_item(item)
                public_item["score"] = round(float(score), 4)
                results.append(public_item)

            if results:
                self._save(data)

            return results

    def list_session_events(
        self,
        session_id: str,
        *,
        limit: int = 20,
        include_summaries: bool = False,
    ) -> list[dict[str, Any]]:
        with self._lock:
            data = self._load()
            items = [
                item
                for item in data["items"]
                if item.get("session_id") == session_id
                and (include_summaries or item.get("type") != "session_summary")
            ]
            items = items[-max(1, int(limit)) :]
            return [self._public_item(item) for item in items]

    def _public_item(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id", ""),
            "timestamp": item.get("timestamp", ""),
            "session_id": item.get("session_id", ""),
            "type": item.get("type", ""),
            "summary": item.get("summary", ""),
            "raw_text": item.get("raw_text"),
            "raw_ref": item.get("raw_ref"),
            "topics": item.get("topics", []),
            "project_refs": item.get("project_refs", []),
            "decisions": item.get("decisions", []),
            "action_items": item.get("action_items", []),
            "importance": item.get("importance", 0.5),
            "hits": item.get("hits", 0),
        }

    def _prune_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        summaries = [item for item in items if item.get("type") == "session_summary"]
        events = [item for item in items if item.get("type") != "session_summary"]
        max_events = max(1, episodic_memory_max_items - len(summaries))
        return summaries + events[-max_events:]

    def _item_id(self, text: str) -> str:
        digest = hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()
        return digest[:16]

    def _searchable_text(
        self,
        *,
        summary: str,
        topics: list[str],
        project_refs: list[str],
        decisions: list[str],
        action_items: list[str],
    ) -> str:
        return _clean_text(
            " ".join([summary, *topics, *project_refs, *decisions, *action_items])
        )

    def _item_search_text(self, item: dict[str, Any]) -> str:
        return self._searchable_text(
            summary=str(item.get("summary", "")),
            topics=list(item.get("topics") or []),
            project_refs=list(item.get("project_refs") or []),
            decisions=list(item.get("decisions") or []),
            action_items=list(item.get("action_items") or []),
        )

    def _clean_list(self, values: list[Any] | None) -> list[str]:
        cleaned = []
        for value in values or []:
            text = _clean_text(str(value))
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    def _merge_lists(
        self,
        existing: list[Any] | None,
        incoming: list[Any] | None,
    ) -> list[str]:
        return self._clean_list([*(existing or []), *(incoming or [])])

    def _normalized_set(self, values: list[Any] | None) -> set[str]:
        return {
            str(value).strip().casefold()
            for value in values or []
            if str(value).strip()
        }

    def _overlap_score(
        self,
        query_values: set[str],
        item_values: list[Any] | None,
    ) -> float:
        if not query_values:
            return 0.0
        item_set = self._normalized_set(item_values)
        if not item_set:
            return 0.0
        return len(query_values & item_set) / len(query_values | item_set)

    def _clean_importance(self, value: float) -> float:
        try:
            return min(max(float(value), 0.0), 1.0)
        except (TypeError, ValueError):
            return 0.5

    def _parse_time(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if not value:
            return None
        try:
            text = str(value).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def format_episodic_memories_for_prompt(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return ""

    lines = ["Relevant episodic memories:"]
    remaining = episodic_memory_max_context_chars

    for episodic_memory in memories:
        summary = _clean_text(str(episodic_memory.get("summary", "")))
        if not summary:
            continue

        timestamp = str(episodic_memory.get("timestamp", ""))[:10]
        memory_type = str(episodic_memory.get("type", "event"))
        line = f"- [{timestamp} / {memory_type}] {summary}"
        decisions = episodic_memory.get("decisions") or []
        action_items = episodic_memory.get("action_items") or []
        if decisions:
            line += " Decisions: " + "; ".join(map(str, decisions[:3]))
        if action_items:
            line += " Action items: " + "; ".join(map(str, action_items[:3]))
        if len(line) > remaining:
            line = line[: max(0, remaining - 3)].rstrip() + "..."
        lines.append(line)
        remaining -= len(line)
        if remaining <= 0:
            break

    return "\n".join(lines) if len(lines) > 1 else ""
