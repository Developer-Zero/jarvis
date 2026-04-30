import os
import time
import ctypes
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from backend.tools.base import Tool, ToolResult

BLOCKED_EXECUTABLE_EXTENSIONS = {}


def _validate_url(url: str) -> ToolResult | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ToolResult(
            status="error",
            error="Only absolute http and https URLs can be opened",
        )
    return None


def _validate_openable_file(path: str) -> tuple[Path | None, ToolResult | None]:
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except OSError:
        return None, ToolResult(status="error", error="File path does not exist")

    if not resolved.is_file():
        return None, ToolResult(status="error", error="Path is not a file")

    if resolved.suffix.lower() in BLOCKED_EXECUTABLE_EXTENSIONS:
        return None, ToolResult(
            status="error",
            error="Opening executable or script files is blocked",
        )

    return resolved, None


def open_url(url: str) -> ToolResult:
    error = _validate_url(url)
    if error:
        return error

    webbrowser.open(url)
    return ToolResult(status="ok", content="Opened URL")


def open_file(path: str) -> ToolResult:
    resolved, error = _validate_openable_file(path)
    if error:
        return error

    os.startfile(str(resolved))
    return ToolResult(status="ok", content="Opened local file")


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

def get_time() -> ToolResult:
    return ToolResult(status="ok", content=time.strftime("%Y-%m-%d %H:%M:%S"))

def get_system_user() -> ToolResult:
    username = os.environ.get("USERNAME") or os.environ.get("USER")
    if not username:
        return ToolResult(status="error", error="Unable to determine system username")
    return ToolResult(status="ok", content=username)


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
                    "maximum": 100,
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
