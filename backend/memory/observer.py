from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from config import (
    episodic_memory_event_raw_chars,
    episodic_memory_storage_mode,
    episodic_memory_summary_every_turns,
    episodic_memory_summary_min_turns,
    episodic_memory_summary_mode,
    episodic_memory_summary_source_events,
    episodic_memory_summary_model,
)
from backend.memory.episodic import EpisodicMemory
from backend.memory.semantic import _clean_text, _now
from runtime.userdata import get_openai_api_key


OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"


class MemoryObserver:
    def __init__(
        self,
        episodic_memory: EpisodicMemory,
        *,
        client: Any | None = None,
        model: str = episodic_memory_summary_model,
    ):
        self.episodic_memory = episodic_memory
        self.client = client
        self.model = model
        self._session_turns: dict[str, list[dict[str, Any]]] = {}
        self._session_turn_counts: dict[str, int] = {}
        self._last_summary_turn_count: dict[str, int] = {}

    def observe_turn(
        self,
        *,
        session_id: str,
        user_text: str,
        assistant_text: str,
        tool_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        raw_text = self._build_raw_turn(user_text, assistant_text, tool_events)
        if not raw_text:
            return None

        turn = self._build_turn_record(
            session_id=session_id,
            user_text=user_text,
            assistant_text=assistant_text,
            raw_text=raw_text,
            tool_events=tool_events or [],
        )
        self._remember_buffered_turn(session_id, turn)

        event = None
        if self._storage_mode() == "events_and_summaries":
            event = self._save_turn_event(session_id, turn)

        if self._should_refresh_session_summary(session_id):
            summary = self.refresh_session_summary(session_id)
            if summary is not None:
                return summary

        return event

    def refresh_session_summary(self, session_id: str) -> dict[str, Any] | None:
        turns = self._session_turns.get(session_id, [])[
            -max(1, int(episodic_memory_summary_source_events)) :
        ]
        if not turns:
            turns = self.episodic_memory.list_session_events(
                session_id,
                limit=episodic_memory_summary_source_events,
            )
        if not turns:
            return None

        extracted = self._summarize_session(turns)
        source_event_ids = [
            str(turn.get("id", "")) for turn in turns if turn.get("id")
        ]
        try:
            summary = self.episodic_memory.upsert_session_summary(
                session_id=session_id,
                summary=extracted.get("summary") or self._fallback_session_summary(turns),
                topics=extracted.get("topics") or [],
                project_refs=extracted.get("project_refs") or [],
                decisions=extracted.get("decisions") or [],
                action_items=extracted.get("action_items") or [],
                source_event_ids=source_event_ids,
                metadata={
                    "source": "memory_observer",
                    "storage_mode": self._storage_mode(),
                    "turn_count": self._session_turn_counts.get(session_id, 0),
                    "buffered_turn_count": len(self._session_turns.get(session_id, [])),
                },
            )
            self._last_summary_turn_count[session_id] = self._session_turn_counts.get(
                session_id,
                0,
            )
            return summary
        except Exception as exc:
            print(f"Episodic session summary save failed: {exc}")
            return None

    def _summarize_session(self, turns: list[dict[str, Any]]) -> dict[str, Any]:
        turn_lines = []
        for turn in turns:
            turn_lines.append(
                json.dumps(
                    {
                        "timestamp": turn.get("timestamp"),
                        "type": turn.get("type", "turn"),
                        "summary": turn.get("summary"),
                        "raw_text": turn.get("raw_text"),
                        "tool_events": (turn.get("metadata") or {}).get("tool_events", []),
                        "topics": turn.get("topics", []),
                        "project_refs": turn.get("project_refs", []),
                        "decisions": turn.get("decisions", []),
                        "action_items": turn.get("action_items", []),
                    },
                    ensure_ascii=False,
                )
            )

        prompt = (
            "Create or refresh a concise episodic session summary from these turns. "
            "Return only JSON with keys: summary, topics, project_refs, decisions, "
            "action_items. Keep it compact, merge duplicates, and preserve open tasks.\n\n"
            + "\n".join(turn_lines)
        )
        result = self._json_from_model(prompt)
        if result:
            return self._normalize_extraction(result)

        return {
            "summary": self._fallback_session_summary(turns),
            "topics": self._merge_event_lists(turns, "topics"),
            "project_refs": self._merge_event_lists(turns, "project_refs"),
            "decisions": self._merge_event_lists(turns, "decisions"),
            "action_items": self._merge_event_lists(turns, "action_items"),
        }

    def _json_from_model(self, prompt: str) -> dict[str, Any] | None:
        mode = str(episodic_memory_summary_mode or "openai").strip().lower()
        if mode == "ollama":
            return self._json_from_ollama(prompt)
        if mode == "openai":
            return self._json_from_openai(prompt)

        print(f"Unsupported episodic memory summary mode: {episodic_memory_summary_mode}")
        return None

    def _json_from_openai(self, prompt: str) -> dict[str, Any] | None:
        client = self.client
        if client is None:
            try:
                from openai import OpenAI

                api_key = get_openai_api_key()
                client = OpenAI(api_key=api_key) if api_key else OpenAI()
            except Exception as exc:
                print(f"Episodic memory OpenAI client setup failed: {exc}")
                return None

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You extract structured memory as strict JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""
            data = json.loads(content)
            return data if isinstance(data, dict) else None
        except Exception as exc:
            print(f"Episodic memory OpenAI extraction failed: {exc}")
            return None

    def _json_from_ollama(self, prompt: str) -> dict[str, Any] | None:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {
                    "role": "system",
                    "content": "You extract structured memory as strict JSON.",
                },
                {"role": "user", "content": prompt},
            ],
        }

        try:
            request = urllib.request.Request(
                OLLAMA_CHAT_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                response_data = json.loads(response.read().decode("utf-8"))

            message = response_data.get("message") or {}
            content = message.get("content") or ""
            data = json.loads(content)
            return data if isinstance(data, dict) else None
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"Episodic memory Ollama request failed: {exc}")
            return None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f"Episodic memory Ollama JSON parsing failed: {exc}")
            return None

    def _normalize_extraction(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": _clean_text(str(data.get("type") or "turn")) or "turn",
            "summary": _clean_text(str(data.get("summary") or "")),
            "topics": self._clean_list(data.get("topics")),
            "project_refs": self._clean_list(data.get("project_refs")),
            "decisions": self._clean_list(data.get("decisions")),
            "action_items": self._clean_list(data.get("action_items")),
            "importance": self._clean_importance(data.get("importance", 0.5)),
            "metadata": data.get("metadata")
            if isinstance(data.get("metadata"), dict)
            else {},
        }

    def _build_raw_turn(
        self,
        user_text: str,
        assistant_text: str,
        tool_events: list[dict[str, Any]] | None,
    ) -> str:
        parts = [
            f"User: {_clean_text(user_text)}",
            f"Assistant: {_clean_text(assistant_text)}",
        ]
        if tool_events:
            tool_names = [
                str(event.get("name", ""))
                for event in tool_events
                if event.get("name")
            ]
            if tool_names:
                parts.append("Tools used: " + ", ".join(tool_names))
        return _clean_text("\n".join(part for part in parts if part.strip()))

    def _build_turn_record(
        self,
        *,
        session_id: str,
        user_text: str,
        assistant_text: str,
        raw_text: str,
        tool_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        timestamp = _now()
        summary = self._fallback_turn_summary(user_text, assistant_text, tool_events)
        return {
            "id": f"{session_id}:{timestamp}",
            "timestamp": timestamp,
            "session_id": session_id,
            "type": "turn",
            "summary": summary,
            "raw_text": raw_text[:episodic_memory_event_raw_chars],
            "raw_ref": None,
            "topics": [],
            "project_refs": [],
            "decisions": [],
            "action_items": [],
            "importance": 0.4,
            "metadata": {
                "source": "memory_observer_buffer",
                "tool_events": tool_events,
            },
        }

    def _remember_buffered_turn(self, session_id: str, turn: dict[str, Any]) -> None:
        self._session_turn_counts[session_id] = (
            self._session_turn_counts.get(session_id, 0) + 1
        )
        turns = self._session_turns.setdefault(session_id, [])
        turns.append(turn)
        max_turns = max(1, int(episodic_memory_summary_source_events) * 2)
        if len(turns) > max_turns:
            del turns[:-max_turns]

    def _save_turn_event(
        self,
        session_id: str,
        turn: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            return self.episodic_memory.remember_event(
                session_id=session_id,
                event_type="turn",
                summary=turn.get("summary") or turn.get("raw_text", "")[:240],
                raw_text=turn.get("raw_text"),
                raw_ref=turn.get("raw_ref"),
                topics=turn.get("topics") or [],
                project_refs=turn.get("project_refs") or [],
                decisions=turn.get("decisions") or [],
                action_items=turn.get("action_items") or [],
                importance=turn.get("importance", 0.4),
                metadata=turn.get("metadata") or {},
            )
        except Exception as exc:
            print(f"Episodic memory event save failed: {exc}")
            return None

    def _should_refresh_session_summary(self, session_id: str) -> bool:
        turn_count = self._session_turn_counts.get(session_id, 0)
        min_turns = max(1, int(episodic_memory_summary_min_turns))
        every_turns = max(1, int(episodic_memory_summary_every_turns))
        if turn_count < min_turns:
            return False

        last_count = self._last_summary_turn_count.get(session_id, 0)
        if last_count == 0:
            return True

        return turn_count - last_count >= every_turns

    def _storage_mode(self) -> str:
        mode = str(episodic_memory_storage_mode or "summaries_only").strip().lower()
        if mode in {"summaries_only", "events_and_summaries"}:
            return mode
        print(f"Unsupported episodic memory storage mode: {episodic_memory_storage_mode}")
        return "summaries_only"

    def _fallback_turn_summary(
        self,
        user_text: str,
        assistant_text: str,
        tool_events: list[dict[str, Any]],
    ) -> str:
        user = _clean_text(user_text)[:180]
        assistant = _clean_text(assistant_text)[:220]
        parts = []
        if user:
            parts.append(f"User: {user}")
        if assistant:
            parts.append(f"Assistant: {assistant}")
        tool_names = [
            str(event.get("name", ""))
            for event in tool_events
            if event.get("name")
        ]
        if tool_names:
            parts.append("Tools: " + ", ".join(tool_names[:8]))
        return " | ".join(parts)[:500]

    def _fallback_session_summary(self, events: list[dict[str, Any]]) -> str:
        summaries = [
            _clean_text(str(event.get("summary", "")))
            for event in events[-5:]
            if event.get("summary")
        ]
        return " ".join(summaries)[:500] or "Session activity was recorded."

    def _merge_event_lists(self, events: list[dict[str, Any]], key: str) -> list[str]:
        values = []
        for event in events:
            values.extend(event.get(key) or [])
        return self._clean_list(values)

    def _clean_list(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        cleaned = []
        for value in values:
            text = _clean_text(str(value))
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned

    def _clean_importance(self, value: Any) -> float:
        try:
            return min(max(float(value), 0.0), 1.0)
        except (TypeError, ValueError):
            return 0.5
