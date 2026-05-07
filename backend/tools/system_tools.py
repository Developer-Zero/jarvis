import os
import time

from backend.tools.base import Tool, ToolResult


def wait(seconds: float) -> ToolResult:
    time.sleep(seconds)
    return ToolResult(status="ok", content=f"Waited {seconds} seconds")

def get_time() -> ToolResult:
    return ToolResult(status="ok", content=time.strftime("%Y-%m-%d %H:%M:%S"))

def get_system_user() -> ToolResult:
    username = os.environ.get("USERNAME") or os.environ.get("USER")
    if not username:
        return ToolResult(status="error", error="Unable to determine system username")
    return ToolResult(status="ok", content=username)


SYSTEM_TOOLS = [
    Tool(
        name="wait",
        description="Pause execution for a given number of seconds.",
        parameters={
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 300,
                }
            },
            "required": ["seconds"],
        },
        function=wait,
    ),
    Tool(
        name="get_time",
        description="Get the current time.",
        parameters={},
        function=get_time,
    ),
    Tool(
        name="get_system_user",
        description="Get the current system user.",
        parameters={},
        function=get_system_user,
    ),
]
