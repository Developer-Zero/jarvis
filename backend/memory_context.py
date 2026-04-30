from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from config import episodic_memory_min_score, episodic_memory_top_k, ttt_model
from backend.episodic_memory import (
    EpisodicMemory,
    EpisodicQuery,
    format_episodic_memories_for_prompt,
)
from backend.semantic_memory import (
    SemanticMemory,
    _clean_text,
    format_semantic_memories_for_prompt,
)


class MemoryContextBuilder:
    def __init__(
        self,
        *,
        semantic_memory: SemanticMemory | None = None,
        episodic_memory: EpisodicMemory | None = None,
        client: Any | None = None,
        model: str = ttt_model,
    ):
        self.semantic_memory = semantic_memory
        self.episodic_memory = episodic_memory
        self.client = client
        self.model = model

    def build(self, user_query: str) -> str:
        sections = []
        if self.semantic_memory:
            try:
                semantic = self.semantic_memory.search(user_query)
                formatted = format_semantic_memories_for_prompt(semantic)
                if formatted:
                    sections.append(formatted)
            except Exception as exc:
                print(f"Semantic memory context build failed: {exc}")

        if self.episodic_memory:
            try:
                episodic_query = self._build_episodic_query(user_query)
                episodic = self.episodic_memory.retrieve(episodic_query)
                formatted = format_episodic_memories_for_prompt(episodic)
                if formatted:
                    sections.append(formatted)
            except Exception as exc:
                print(f"Episodic memory context build failed: {exc}")

        return "\n\n".join(sections)

    def _build_episodic_query(self, user_query: str) -> EpisodicQuery:
        analysis = self._analyze_query(user_query)
        return EpisodicQuery(
            query=user_query,
            start_time=analysis.get("start_time"),
            end_time=analysis.get("end_time"),
            topics=self._clean_list(analysis.get("topics")),
            project_refs=self._clean_list(analysis.get("project_refs")),
            types=self._clean_list(analysis.get("types")),
            limit=episodic_memory_top_k,
            min_score=episodic_memory_min_score,
        )

    def _analyze_query(self, user_query: str) -> dict[str, Any]:
        if self.client is None:
            return {}

        now = datetime.now(timezone.utc).isoformat()
        prompt = (
            "Analyze this user query for episodic memory retrieval. "
            "Return only JSON with keys: topics, project_refs, start_time, end_time, types. "
            "Use ISO 8601 UTC timestamps for time ranges when the user asks about time. "
            "Leave fields null or empty when uncertain. Do not use hardcoded project guesses.\n\n"
            f"Current UTC time: {now}\n"
            f"Query: {_clean_text(user_query)}"
        )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You create strict JSON retrieval filters for memory search.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""
            data = json.loads(content)
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            print(f"Episodic query analysis failed: {exc}")
            return {}

    def _clean_list(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        cleaned = []
        for value in values:
            text = _clean_text(str(value))
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned
