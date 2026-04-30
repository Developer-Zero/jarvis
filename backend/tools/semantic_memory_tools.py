from __future__ import annotations

from backend.semantic_memory import SemanticMemory
from backend.tools.base import Tool, ToolResult


def build_semantic_memory_tools(semantic_memory: SemanticMemory) -> list[Tool]:
    def save_semantic_memory(text: str, category: str = "general") -> ToolResult:
        item = semantic_memory.remember(
            text,
            metadata={"category": category, "source": "agent"},
        )
        return ToolResult(status="ok", content=item)

    def search_semantic_memory(query: str, limit: int = 5) -> ToolResult:
        results = semantic_memory.search(query, limit=limit, min_score=0.01)
        return ToolResult(status="ok", content=results)

    def list_semantic_memories(limit: int = 20) -> ToolResult:
        return ToolResult(status="ok", content=semantic_memory.list_recent(limit=limit))

    def forget_semantic_memory(semantic_memory_id: str) -> ToolResult:
        if semantic_memory.forget(semantic_memory_id):
            return ToolResult(
                status="ok",
                content=f"Forgot semantic memory: {semantic_memory_id}",
            )
        return ToolResult(status="error", error="Semantic memory not found")

    return [
        Tool(
            name="save_semantic_memory",
            description=(
                "Save a durable semantic memory about the user or their stable "
                "preferences. Do not save secrets, credentials, or one-off commands."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "A concise factual memory to store.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Short category label.",
                    },
                },
                "required": ["text"],
            },
            function=save_semantic_memory,
        ),
        Tool(
            name="search_semantic_memory",
            description="Search long-term semantic memory for relevant past user facts or preferences.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["query"],
            },
            function=search_semantic_memory,
        ),
        Tool(
            name="list_semantic_memories",
            description="List the most recent long-term semantic memories.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
            },
            function=list_semantic_memories,
        ),
        Tool(
            name="forget_semantic_memory",
            description="Delete a semantic memory by its id.",
            parameters={
                "type": "object",
                "properties": {
                    "semantic_memory_id": {"type": "string"},
                },
                "required": ["semantic_memory_id"],
            },
            function=forget_semantic_memory,
        ),
    ]
