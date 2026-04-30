from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from config import (
    episodic_memory_event_raw_chars,
    episodic_memory_summary_mode,
    episodic_memory_summary_source_events,
    episodic_memory_summary_model,
)
from backend.episodic_memory import EpisodicMemory
from backend.semantic_memory import _clean_text
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

        extracted = self._extract_turn(raw_text, tool_events or [])
        try:
            event = self.episodic_memory.remember_event(
                session_id=session_id,
                event_type=extracted.get("type") or "turn",
                summary=extracted.get("summary") or raw_text[:240],
                raw_text=raw_text[:episodic_memory_event_raw_chars],
                topics=extracted.get("topics") or [],
                project_refs=extracted.get("project_refs") or [],
                decisions=extracted.get("decisions") or [],
                action_items=extracted.get("action_items") or [],
                importance=extracted.get("importance", 0.5),
                metadata={
                    "source": "memory_observer",
                    "tool_events": tool_events or [],
                },
            )
        except Exception as exc:
            print(f"Episodic memory event save failed: {exc}")
            return None

        self.refresh_session_summary(session_id)
        return event

    def refresh_session_summary(self, session_id: str) -> dict[str, Any] | None:
        events = self.episodic_memory.list_session_events(
            session_id,
            limit=episodic_memory_summary_source_events,
        )
        if not events:
            return None

        extracted = self._summarize_session(events)
        source_event_ids = [
            str(event.get("id", "")) for event in events if event.get("id")
        ]
        try:
            return self.episodic_memory.upsert_session_summary(
                session_id=session_id,
                summary=extracted.get("summary") or self._fallback_session_summary(events),
                topics=extracted.get("topics") or [],
                project_refs=extracted.get("project_refs") or [],
                decisions=extracted.get("decisions") or [],
                action_items=extracted.get("action_items") or [],
                source_event_ids=source_event_ids,
                metadata={"source": "memory_observer"},
            )
        except Exception as exc:
            print(f"Episodic session summary save failed: {exc}")
            return None

    def _extract_turn(
        self,
        raw_text: str,
        tool_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = (
            "Extract an episodic memory event from this Jarvis conversation turn. "
            "Return only JSON with keys: type, summary, topics, project_refs, "
            "decisions, action_items, importance, metadata. "
            "Use concise Hungarian text when the conversation is Hungarian. "
            "Do not invent facts; use empty arrays when uncertain. "
            "Importance must be a number between 0 and 1.\n\n"
            f"Tool events JSON: {json.dumps(tool_events, ensure_ascii=False)}\n\n"
            f"Turn:\n{raw_text}"
        )
        result = self._json_from_model(prompt)
        if result:
            return self._normalize_extraction(result)
        return {
            "type": "turn",
            "summary": raw_text[:240],
            "topics": [],
            "project_refs": [],
            "decisions": [],
            "action_items": [],
            "importance": 0.4,
            "metadata": {"extraction": "fallback"},
        }

    def _summarize_session(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        event_lines = []
        for event in events:
            event_lines.append(
                json.dumps(
                    {
                        "timestamp": event.get("timestamp"),
                        "type": event.get("type"),
                        "summary": event.get("summary"),
                        "topics": event.get("topics", []),
                        "project_refs": event.get("project_refs", []),
                        "decisions": event.get("decisions", []),
                        "action_items": event.get("action_items", []),
                    },
                    ensure_ascii=False,
                )
            )

        prompt = (
            "Create or refresh a concise episodic session summary from these events. "
            "Return only JSON with keys: summary, topics, project_refs, decisions, "
            "action_items. Keep it compact, merge duplicates, and preserve open tasks.\n\n"
            + "\n".join(event_lines)
        )
        result = self._json_from_model(prompt)
        if result:
            return self._normalize_extraction(result)

        return {
            "summary": self._fallback_session_summary(events),
            "topics": self._merge_event_lists(events, "topics"),
            "project_refs": self._merge_event_lists(events, "project_refs"),
            "decisions": self._merge_event_lists(events, "decisions"),
            "action_items": self._merge_event_lists(events, "action_items"),
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
