import ctypes
import os
from ctypes import wintypes

import psutil

from backend.tools.base import Tool, ToolResult


def _visible_windows() -> dict[int, list[str]]:
    user32 = ctypes.windll.user32
    windows: dict[int, list[str]] = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_window(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not _is_useful_window_title(title):
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        windows.setdefault(int(pid.value), []).append(title)
        return True

    user32.EnumWindows(enum_window, 0)
    return windows


INSIGNIFICANT_PROCESS_NAMES = {
    "applicationframehost.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
    "textinputhost.exe",
    "SystemSettings.exe",
}

INSIGNIFICANT_TITLES = {
    "Program Manager",
    "Windows Input Experience",
}


def _is_useful_window_title(title: str) -> bool:
    return bool(title and title not in INSIGNIFICANT_TITLES)


def _process_summary(process: psutil.Process, titles: list[str] | None = None) -> dict:
    info = process.info if hasattr(process, "info") else {}
    name = info.get("name") or process.name()
    data = {"pid": process.pid, "name": name}
    if titles:
        data["titles"] = titles[:3]
    return data


def list_foreground_apps() -> ToolResult:
    windows = _visible_windows()
    apps = []

    for process in psutil.process_iter(["name"]):
        titles = windows.get(process.pid)
        if not titles:
            continue
        try:
            name = process.name()
            if name.lower() in INSIGNIFICANT_PROCESS_NAMES:
                continue
            titles = [title for title in titles if _is_useful_window_title(title)]
            if not titles:
                continue
            apps.append(_process_summary(process, titles))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    apps.sort(key=lambda item: item["name"].lower())
    return ToolResult(status="ok", content=apps)


def _matching_processes(app: str) -> list[psutil.Process]:
    query = app.strip().lower()
    if not query:
        return []

    if query.isdigit():
        try:
            return [psutil.Process(int(query))]
        except psutil.Error:
            return []

    exact = []
    partial = []
    title_matches = []
    windows = _visible_windows()

    for process in psutil.process_iter(["name", "exe"]):
        if process.pid == os.getpid():
            continue

        try:
            name = (process.info.get("name") or "").lower()
            stem = name.removesuffix(".exe")
            exe = (process.info.get("exe") or "").lower()
            titles = [title.lower() for title in windows.get(process.pid, [])]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if query in {name, stem}:
            exact.append(process)
        elif query in name or query in exe:
            partial.append(process)
        elif any(query in title for title in titles):
            title_matches.append(process)

    return exact or partial or title_matches


def stop_app(app: str) -> ToolResult:
    matches = _matching_processes(app)
    if not matches:
        return ToolResult(status="error", error="No matching app found")

    stopped = []
    failed = []
    for process in matches:
        try:
            name = process.name()
            process.terminate()
            try:
                process.wait(timeout=3)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            stopped.append({"pid": process.pid, "name": name})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired) as exc:
            failed.append({"pid": process.pid, "error": str(exc)})

    if not stopped:
        return ToolResult(status="error", error="Could not stop app", content=failed)

    content = {}
    if stopped:
        content["stopped"] = stopped
    elif failed:
        content["failed"] = failed
    return ToolResult(status="ok", content=content)


APP_TOOLS = [
    Tool(
        name="list_foreground_apps",
        description="List open user apps.",
        parameters={"type": "object", "properties": {}},
        function=list_foreground_apps,
    ),
    Tool(
        name="stop_app",
        description="Stop an app by name, title, or PID.",
        parameters={
            "type": "object",
            "properties": {"app": {"type": "string"}},
            "required": ["app"],
        },
        function=stop_app,
    ),
]
