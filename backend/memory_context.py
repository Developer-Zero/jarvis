from __future__ import annotations

from typing import Any

from config import episodic_memory_min_score, episodic_memory_top_k, ttt_model
from backend.episodic_memory import (
    EpisodicMemory,
    EpisodicQuery,
    format_episodic_memories_for_prompt,
)
from backend.semantic_memory import (
    SemanticMemory,
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
        return EpisodicQuery(
            query=user_query,
            limit=episodic_memory_top_k,
            min_score=episodic_memory_min_score,
        )
