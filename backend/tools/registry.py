import json

from backend.tools.base import Tool, ToolResult
from backend.tools.file_tools import FILE_TOOLS
from backend.tools.memory_tools import build_memory_tools
from backend.tools.system_tools import SYSTEM_TOOLS


class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise ValueError(f"Tool already registered: {tool.name}")

        self.tools[tool.name] = tool

    def register_many(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def get_openai_schemas(self) -> list[dict]:
        return [tool.openai_schema() for tool in self.tools.values()]

    def execute(self, name: str, args: dict) -> ToolResult:
        tool = self.tools.get(name)

        if tool is None:
            return ToolResult(
                status="error",
                error=f"Requested tool does not exist: {name}",
            )

        return tool.execute(args)


def build_default_registry(memory=None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_many(SYSTEM_TOOLS)
    registry.register_many(FILE_TOOLS)
    if memory is not None:
        registry.register_many(build_memory_tools(memory))
    return registry


def tool_result_for_model(name: str, result: ToolResult) -> str:
    payload = {
        "name": name,
        **result.to_dict(),
    }

    return json.dumps(payload, ensure_ascii=False)
