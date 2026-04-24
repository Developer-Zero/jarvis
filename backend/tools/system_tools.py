import os
import time
import ctypes
import webbrowser

from backend.tools.base import Tool, ToolResult


def open_url(url: str) -> ToolResult:
    webbrowser.open(url)
    return ToolResult(status="ok", content=f"Opened URL: {url}")


def open_file(path: str) -> ToolResult:
    if not os.path.exists(path):
        return ToolResult(status="error", error="File path does not exist")

    os.startfile(path)
    return ToolResult(status="ok", content=f"Opened file: {path}")


def press_key(key: int) -> None:
    ctypes.windll.user32.keybd_event(key, 0, 0, 0)
    ctypes.windll.user32.keybd_event(key, 0, 2, 0)


def set_volume(direction: str, amount: int) -> ToolResult:
    if direction not in {"up", "down"}:
        return ToolResult(status="error", error="Direction must be 'up' or 'down'")

    key = 0xAF if direction == "up" else 0xAE

    for _ in range(int(amount)):
        press_key(key)

    return ToolResult(status="ok", content=f"Volume changed {direction} by {amount}")


def wait(seconds: float) -> ToolResult:
    time.sleep(seconds)
    return ToolResult(status="ok", content=f"Waited {seconds} seconds")


SYSTEM_TOOLS = [
    Tool(
        name="open_url",
        description="Open a website in the default browser.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"}
            },
            "required": ["url"],
        },
        function=open_url,
    ),
    Tool(
        name="open_file",
        description="Launch a local file using the default application.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"],
        },
        function=open_file,
    ),
    Tool(
        name="set_volume",
        description="Change system volume using media keys.",
        parameters={
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                },
                "amount": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["direction", "amount"],
        },
        function=set_volume,
    ),
    Tool(
        name="wait",
        description="Pause execution for a given number of seconds.",
        parameters={
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 60,
                }
            },
            "required": ["seconds"],
        },
        function=wait,
    ),
]