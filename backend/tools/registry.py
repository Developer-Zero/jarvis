import json

from backend.tools.base import Tool, ToolResult
from backend.tools.app_tools import APP_TOOLS
from backend.tools.browser_tools import BROWSER_TOOLS
from backend.tools.file_tools import FILE_TOOLS
from backend.tools.music_tools import MUSIC_TOOLS
from backend.tools.system_tools import SYSTEM_TOOLS
from backend.tools.task_tools import TASK_TOOLS
from backend.tools.volume_tools import VOLUME_TOOLS
from backend.tools.web_search_tools import WEB_SEARCH_TOOLS
from backend.memory.episodic_tools import build_episodic_memory_tools
from backend.memory.semantic_tools import build_semantic_memory_tools


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


def build_default_registry(semantic_memory=None, episodic_memory=None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_many(APP_TOOLS)
    registry.register_many(BROWSER_TOOLS)
    registry.register_many(WEB_SEARCH_TOOLS)
    registry.register_many(MUSIC_TOOLS)
    registry.register_many(VOLUME_TOOLS)
    registry.register_many(SYSTEM_TOOLS)
    registry.register_many(TASK_TOOLS)
    registry.register_many(FILE_TOOLS)
    if semantic_memory is not None:
        registry.register_many(build_semantic_memory_tools(semantic_memory))
    if episodic_memory is not None:
        registry.register_many(build_episodic_memory_tools(episodic_memory))
    return registry


def tool_result_for_model(name: str, result: ToolResult) -> str:
    payload = {
        "name": name,
        **result.to_dict(),
    }

    return json.dumps(payload, ensure_ascii=False)
