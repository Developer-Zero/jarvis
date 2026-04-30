from __future__ import annotations

from backend.memory import SemanticMemory
from backend.tools.base import Tool, ToolResult


def build_memory_tools(memory: SemanticMemory) -> list[Tool]:
    def save_memory(text: str, category: str = "general") -> ToolResult:
        item = memory.remember(
            text,
            metadata={"category": category, "source": "agent"},
        )
        return ToolResult(status="ok", content=item)

    def search_memory(query: str, limit: int = 5) -> ToolResult:
        results = memory.search(query, limit=limit, min_score=0.01)
        return ToolResult(status="ok", content=results)

    def list_memories(limit: int = 20) -> ToolResult:
        return ToolResult(status="ok", content=memory.list_recent(limit=limit))

    def forget_memory(memory_id: str) -> ToolResult:
        if memory.forget(memory_id):
            return ToolResult(status="ok", content=f"Forgot memory: {memory_id}")
        return ToolResult(status="error", error="Memory not found")

    return [
        Tool(
            name="save_memory",
            description=(
                "Save a durable long-term memory about the user or their stable "
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
            function=save_memory,
        ),
        Tool(
            name="search_memory",
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
            function=search_memory,
        ),
        Tool(
            name="list_memories",
            description="List the most recent long-term memories.",
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
            function=list_memories,
        ),
        Tool(
            name="forget_memory",
            description="Delete a long-term memory by its id.",
            parameters={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string"},
                },
                "required": ["memory_id"],
            },
            function=forget_memory,
        ),
    ]
