from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolResult:
    status: str
    content: Any = None
    error: str | None = None

    def to_dict(self) -> dict:
        data = {"status": self.status}

        if self.content is not None:
            data["content"] = self.content

        if self.error is not None:
            data["error"] = self.error

        return data


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    function: Callable[..., ToolResult]

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, args: dict) -> ToolResult:
        try:
            return self.function(**args)
        except TypeError as e:
            return ToolResult(
                status="error",
                error=f"Invalid arguments for tool '{self.name}': {e}",
            )
        except Exception as e:
            return ToolResult(
                status="error",
                error=f"Tool '{self.name}' failed: {e}",
            )