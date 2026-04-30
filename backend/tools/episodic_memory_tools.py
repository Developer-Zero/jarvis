from __future__ import annotations

from typing import Any

from backend.episodic_memory import EpisodicMemory, EpisodicQuery
from backend.semantic_memory import _clean_text
from backend.tools.base import Tool, ToolResult


def build_episodic_memory_tools(episodic_memory: EpisodicMemory) -> list[Tool]:
    def search_episodic_memory(
        query: str = "",
        topics: list[str] | None = None,
        project_refs: list[str] | None = None,
        types: list[str] | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 5,
        min_score: float | None = None,
        include_raw: bool = False,
    ) -> ToolResult:
        if not _has_search_input(
            query=query,
            topics=topics,
            project_refs=project_refs,
            types=types,
            start_time=start_time,
            end_time=end_time,
        ):
            return ToolResult(
                status="error",
                error=(
                    "Provide a query or at least one episodic filter "
                    "(topics, project_refs, types, start_time, end_time)."
                ),
            )

        episodic_query = EpisodicQuery(
            query=query,
            topics=_clean_list(topics),
            project_refs=_clean_list(project_refs),
            types=_clean_list(types),
            start_time=_clean_optional_text(start_time),
            end_time=_clean_optional_text(end_time),
            limit=max(1, min(int(limit or 5), 20)),
            min_score=0.01 if min_score is None else float(min_score),
        )
        results = episodic_memory.retrieve(episodic_query)
        return ToolResult(
            status="ok",
            content=_compact_results(results, include_raw=include_raw),
        )

    return [
        Tool(
            name="search_episodic_memory",
            description="Search past conversation summaries",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                    },
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "project_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Project/file filters.",
                    },
                    "types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Types, e.g. turn or session_summary.",
                    },
                    "start_time": {
                        "type": "string",
                        "description": "ISO start time.",
                    },
                    "end_time": {
                        "type": "string",
                        "description": "ISO end time.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                    },
                    "min_score": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "include_raw": {
                        "type": "boolean",
                        "description": "Include raw_text/raw_ref.",
                    },
                },
            },
            function=search_episodic_memory,
        ),
    ]


def _has_search_input(
    *,
    query: str,
    topics: list[str] | None,
    project_refs: list[str] | None,
    types: list[str] | None,
    start_time: str | None,
    end_time: str | None,
) -> bool:
    return any(
        [
            _clean_text(query),
            _clean_list(topics),
            _clean_list(project_refs),
            _clean_list(types),
            _clean_optional_text(start_time),
            _clean_optional_text(end_time),
        ]
    )


def _compact_results(
    results: list[dict[str, Any]],
    *,
    include_raw: bool,
) -> list[dict[str, Any]]:
    compacted = []
    for item in results:
        compact_item = {
            "id": item.get("id", ""),
            "timestamp": item.get("timestamp", ""),
            "session_id": item.get("session_id", ""),
            "type": item.get("type", ""),
            "summary": item.get("summary", ""),
            "topics": item.get("topics", []),
            "project_refs": item.get("project_refs", []),
            "decisions": item.get("decisions", []),
            "action_items": item.get("action_items", []),
            "importance": item.get("importance", 0.5),
            "score": item.get("score"),
        }
        if include_raw:
            compact_item["raw_text"] = item.get("raw_text")
            compact_item["raw_ref"] = item.get("raw_ref")
        compacted.append(compact_item)
    return compacted


def _clean_list(values: list[Any] | None) -> list[str]:
    cleaned = []
    for value in values or []:
        text = _clean_text(str(value))
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _clean_optional_text(value: Any) -> str | None:
    text = _clean_text(str(value or ""))
    return text or None
