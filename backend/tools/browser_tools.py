import os
import subprocess
import time
import logging
import threading
import json
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

import psutil

from config import browser_debugging_enabled, browser_debugging_port, default_page
from backend.tools.base import Tool, ToolResult


CHROMIUM_PROCESS_CHANNELS = {
    "brave.exe": "chrome",
    "chrome.exe": "chrome",
    "msedge.exe": "msedge",
}

CDP_CONNECT_TIMEOUT_MS = 5000
BROWSER_LAUNCH_TIMEOUT_MS = 12000
DEFAULT_ACTION_TIMEOUT_MS = 8000
DEFAULT_NAVIGATION_TIMEOUT_MS = 15000
STARTUP_PAGE_SETTLE_SECONDS = 2.5
BROWSER_TASK_TIMEOUT_SECONDS = 35

_browser_state = threading.local()
_debug_browser_process = None


def _validate_url(url: str) -> ToolResult | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ToolResult(status="error", error="Use an absolute http or https URL")
    return None


def _normalized_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}{query}"


def _is_default_page(url: str) -> bool:
    if not str(default_page).strip():
        return False

    return _normalized_url(url) == _normalized_url(str(default_page).strip())


def _get_playwright():
    playwright = getattr(_browser_state, "playwright", None)

    if playwright is not None:
        return playwright, None

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, ToolResult(status="error", error="Playwright is not installed")

    logging.info("Starting Playwright driver")
    playwright = sync_playwright().start()
    _browser_state.playwright = playwright
    return playwright, None


def _reset_playwright_handles(stop_driver: bool = False) -> None:
    playwright = getattr(_browser_state, "playwright", None)

    _browser_state.context = None
    _browser_state.browser = None
    if stop_driver and playwright is not None:
        try:
            playwright.stop()
        except Exception:
            pass
        _browser_state.playwright = None


def _configure_context(context) -> None:
    try:
        context.set_default_timeout(DEFAULT_ACTION_TIMEOUT_MS)
        context.set_default_navigation_timeout(DEFAULT_NAVIGATION_TIMEOUT_MS)
    except Exception:
        pass


def _visible_pages(context) -> list:
    return [
        page for page in context.pages
        if not page.is_closed() and page.url != "about:blank"
    ]


def _wait_for_startup_pages(context) -> list:
    deadline = time.monotonic() + STARTUP_PAGE_SETTLE_SECONDS
    last_signature = None
    stable_since = None
    pages = []

    while time.monotonic() < deadline:
        pages = _visible_pages(context)
        signature = tuple(sorted(page.url for page in pages))

        if signature == last_signature:
            if stable_since is not None and time.monotonic() - stable_since >= 0.4:
                return pages
        else:
            stable_since = time.monotonic()
            last_signature = signature

        time.sleep(0.15)

    return pages


def _remote_debugging_endpoint() -> str | None:
    return _managed_debugging_endpoint()


def _debugging_endpoint_for_port(port: int) -> str | None:
    endpoint = f"http://127.0.0.1:{int(port)}"
    try:
        with urlopen(f"{endpoint}/json/version", timeout=0.4):
            return endpoint
    except Exception:
        return None


def _managed_debugging_endpoint() -> str | None:
    if not _managed_debug_browser_processes():
        return None

    return _debugging_endpoint_for_port(browser_debugging_port)


def _extract_remote_debugging_port(cmdline: list[str]) -> str | None:
    for index, arg in enumerate(cmdline):
        if arg.startswith("--remote-debugging-port="):
            return arg.split("=", 1)[1]
        if arg == "--remote-debugging-port" and index + 1 < len(cmdline):
            return cmdline[index + 1]

    return None


def _preferred_channel() -> str:
    for process in psutil.process_iter(["name"]):
        try:
            name = (process.info.get("name") or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        channel = CHROMIUM_PROCESS_CHANNELS.get(name)
        if channel:
            return channel

    return "chrome"


def _managed_profile_dir() -> str:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    path = Path(root) / "Jarvis" / "debug-browser-profile"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _browser_executable() -> str | None:
    candidates = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("PROGRAMFILES")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)")

    for root in (local_appdata, program_files, program_files_x86):
        if not root:
            continue
        candidates.extend([
            Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(root) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe",
        ])

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def _extract_user_data_dir(cmdline: list[str]) -> str | None:
    for index, arg in enumerate(cmdline):
        if arg.startswith("--user-data-dir="):
            return arg.split("=", 1)[1]
        if arg == "--user-data-dir" and index + 1 < len(cmdline):
            return cmdline[index + 1]

    return None


def _same_path(left: str, right: str) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return left.casefold() == right.casefold()


def _managed_debug_browser_processes() -> list[psutil.Process]:
    matches = []
    expected_port = str(int(browser_debugging_port))
    expected_profile = _managed_profile_dir()

    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (process.info.get("name") or "").lower()
            if name not in CHROMIUM_PROCESS_CHANNELS:
                continue

            cmdline = process.info.get("cmdline") or []
            port = _extract_remote_debugging_port(cmdline)
            profile = _extract_user_data_dir(cmdline)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if port == expected_port and profile and _same_path(profile, expected_profile):
            matches.append(process)

    return matches


def ensure_debug_browser_started() -> ToolResult:
    global _debug_browser_process

    if not browser_debugging_enabled:
        return ToolResult(status="ok", content="Debug browser disabled")

    endpoint = _managed_debugging_endpoint()
    if endpoint:
        return ToolResult(status="ok", content=endpoint)

    if _debugging_endpoint_for_port(browser_debugging_port):
        return ToolResult(
            status="error",
            error="Browser debug port is already used by another process",
        )

    executable = _browser_executable()
    if not executable:
        return ToolResult(status="error", error="No Chromium browser found")

    args = [
        executable,
        f"--remote-debugging-port={int(browser_debugging_port)}",
        f"--user-data-dir={_managed_profile_dir()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--no-startup-window",
    ]

    try:
        logging.info("Starting debug browser: %s", executable)
        _debug_browser_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except Exception as exc:
        return ToolResult(status="error", error=f"Debug browser start failed: {exc}")

    for _ in range(20):
        endpoint = _debugging_endpoint_for_port(browser_debugging_port)
        if endpoint:
            return ToolResult(status="ok", content=endpoint)
        time.sleep(0.25)

    return ToolResult(status="error", error="Debug browser did not become ready")


def initialize_debug_browser() -> ToolResult:
    startup = ensure_debug_browser_started()
    if startup.status != "ok":
        return startup

    return reconcile_default_page()


def reconcile_default_page() -> ToolResult:
    if not _in_browser_task_child():
        return _run_browser_task("reconcile_default_page", {})

    return _reconcile_default_page_direct()


def _reconcile_default_page_direct() -> ToolResult:
    default_url = str(default_page).strip()
    if not default_url:
        return ToolResult(status="ok", content="Default page disabled")

    error = _validate_url(default_url)
    if error:
        return error

    context, error = _connect_context()
    if error:
        return error

    pages = _wait_for_startup_pages(context)
    default_pages = [page for page in pages if _is_default_page(page.url)]
    other_pages = [page for page in pages if not _is_default_page(page.url)]

    if other_pages:
        closed = 0
        for page in default_pages:
            try:
                page.close()
                closed += 1
            except Exception:
                pass
        return ToolResult(
            status="ok",
            content={"default_closed": closed, "other_pages": len(other_pages)},
        )

    if default_pages:
        try:
            default_pages[0].bring_to_front()
        except Exception:
            pass
        return ToolResult(status="ok", content="Default page already open")

    page = context.new_page()
    page.goto(default_url, wait_until="domcontentloaded", timeout=DEFAULT_NAVIGATION_TIMEOUT_MS)
    page.bring_to_front()
    pages = _wait_for_startup_pages(context)
    default_pages = [page for page in pages if _is_default_page(page.url)]
    other_pages = [page for page in pages if not _is_default_page(page.url)]
    if other_pages:
        closed = 0
        for page in default_pages:
            try:
                page.close()
                closed += 1
            except Exception:
                pass
        return ToolResult(
            status="ok",
            content={"default_closed": closed, "other_pages": len(other_pages)},
        )

    return ToolResult(status="ok", content="Default page opened")


def close_debug_browser() -> ToolResult:
    global _debug_browser_process

    processes = _managed_debug_browser_processes()
    if _debug_browser_process is not None and _debug_browser_process.poll() is None:
        try:
            processes.append(psutil.Process(_debug_browser_process.pid))
        except psutil.Error:
            pass

    unique_processes = {process.pid: process for process in processes}
    stopped = []
    failed = []

    for process in unique_processes.values():
        try:
            name = process.name()
            process.terminate()
            stopped.append({"pid": process.pid, "name": name})
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            failed.append({"pid": process.pid, "error": str(exc)})

    gone, alive = psutil.wait_procs(list(unique_processes.values()), timeout=2)
    for process in alive:
        try:
            process.kill()
            process.wait(timeout=1)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired) as exc:
            failed.append({"pid": process.pid, "error": str(exc)})

    _reset_playwright_handles(stop_driver=True)

    _debug_browser_process = None
    return ToolResult(status="ok", content={"stopped": stopped, "failed": failed})


def _connect_context():
    context = getattr(_browser_state, "context", None)
    if context is not None:
        try:
            context.pages
            return context, None
        except Exception:
            _reset_playwright_handles()

    playwright, error = _get_playwright()
    if error:
        return None, error

    startup = ensure_debug_browser_started()
    if startup.status != "ok":
        return None, startup

    endpoint = _remote_debugging_endpoint()
    if endpoint:
        try:
            logging.info("Connecting to debug browser: %s", endpoint)
            _browser = playwright.chromium.connect_over_cdp(
                endpoint,
                timeout=CDP_CONNECT_TIMEOUT_MS,
            )
            if _browser.contexts:
                _context = _browser.contexts[0]
            else:
                _context = _browser.new_context()
            _browser_state.browser = _browser
            _browser_state.context = _context
            _configure_context(_context)
            return _context, None
        except Exception as exc:
            logging.warning("Browser connect failed: %s", exc)
            close_debug_browser()

            playwright, error = _get_playwright()
            if error:
                return None, error

            startup = ensure_debug_browser_started()
            if startup.status != "ok":
                return None, startup

            endpoint = _remote_debugging_endpoint()
            if endpoint:
                try:
                    _browser = playwright.chromium.connect_over_cdp(
                        endpoint,
                        timeout=CDP_CONNECT_TIMEOUT_MS,
                    )
                    _context = _browser.contexts[0] if _browser.contexts else _browser.new_context()
                    _browser_state.browser = _browser
                    _browser_state.context = _context
                    _configure_context(_context)
                    return _context, None
                except Exception as retry_exc:
                    _reset_playwright_handles(stop_driver=True)
                    return None, ToolResult(
                        status="error",
                        error=f"Browser reconnect failed: {retry_exc}",
                    )

            return None, ToolResult(status="error", error=f"Browser connect failed: {exc}")

    try:
        logging.info("Launching fallback persistent browser")
        _context = playwright.chromium.launch_persistent_context(
            _managed_profile_dir(),
            channel=_preferred_channel(),
            headless=False,
            no_viewport=True,
            timeout=BROWSER_LAUNCH_TIMEOUT_MS,
        )
        _browser_state.context = _context
        _configure_context(_context)
        return _context, None
    except Exception as exc:
        return None, ToolResult(status="error", error=f"Browser start failed: {exc}")


def _in_browser_task_child() -> bool:
    return os.environ.get("JARVIS_BROWSER_TASK_CHILD") == "1"


def _run_browser_task(task: str, args: dict, timeout: int = BROWSER_TASK_TIMEOUT_SECONDS) -> ToolResult:
    script = (
        "import json,sys;"
        f"sys.path.insert(0,{json.dumps(str(Path(__file__).resolve().parents[2]))});"
        "from backend.tools.browser_tools import _browser_task_entry;"
        "payload=json.loads(sys.argv[1]);"
        "result=_browser_task_entry(payload['task'], payload.get('args', {}));"
        "print(json.dumps(result, ensure_ascii=False))"
    )
    env = os.environ.copy()
    env["JARVIS_BROWSER_TASK_CHILD"] = "1"
    payload = json.dumps({"task": task, "args": args}, ensure_ascii=False)

    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, payload],
            cwd=str(Path(__file__).resolve().parents[2]),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        logging.warning("Browser task timed out: %s", task)
        close_debug_browser()
        return ToolResult(status="error", error=f"Browser task timed out: {task}")

    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout or "").strip()
        logging.warning("Browser task failed: %s | %s", task, error)
        return ToolResult(status="error", error=error or f"Browser task failed: {task}")

    try:
        data = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        return ToolResult(status="error", error=f"Invalid browser task result: {exc}")

    return ToolResult(
        status=data.get("status", "error"),
        content=data.get("content"),
        error=data.get("error"),
    )


def _browser_task_entry(task: str, args: dict) -> dict:
    try:
        if task == "reconcile_default_page":
            return _reconcile_default_page_direct().to_dict()
        if task == "read_rendered_page":
            return _read_rendered_page_direct(**args).to_dict()
        if task == "open_or_reuse_page":
            return ToolResult(status="ok", content=_open_or_reuse_page_direct(**args)).to_dict()
        if task == "open_page":
            return _open_page_direct(**args).to_dict()
        if task == "list_open_pages":
            return _list_open_pages_direct().to_dict()
        if task == "close_page":
            return _close_page_direct(**args).to_dict()
        return ToolResult(status="error", error=f"Unknown browser task: {task}").to_dict()
    finally:
        _reset_playwright_handles(stop_driver=True)


def _page_summary(page, index: int) -> dict:
    try:
        title = page.title()
    except Exception:
        title = ""

    return {
        "index": index,
        "title": title,
        "url": page.url,
    }


def _pages() -> tuple[list | None, ToolResult | None]:
    context, error = _connect_context()
    if error:
        return None, error

    pages = _visible_pages(context)
    return pages, None


def read_rendered_page(url: str, max_chars: int, start: int = 0) -> ToolResult:
    if not _in_browser_task_child():
        return _run_browser_task(
            "read_rendered_page",
            {"url": url, "max_chars": max_chars, "start": start},
        )

    return _read_rendered_page_direct(url, max_chars, start)


def _read_rendered_page_direct(url: str, max_chars: int, start: int = 0) -> ToolResult:
    error = _validate_url(url)
    if error:
        return error

    context, error = _connect_context()
    if error:
        return error

    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        try:
            page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass

        title = page.title()
        text = page.locator("body").inner_text(timeout=8000)
        start = max(0, int(start))
        end = start + max_chars
        return ToolResult(
            status="ok",
            content={
                "title": title,
                "url": page.url,
                "text": text[start:end],
                "start": start,
                "next_start": end if end < len(text) else None,
                "has_more": end < len(text),
            },
        )
    except Exception as exc:
        return ToolResult(status="error", error=f"Rendered page read failed: {exc}")
    finally:
        try:
            page.close()
        except Exception:
            pass


def open_or_reuse_page(url: str, match: str) -> bool:
    if not _in_browser_task_child():
        result = _run_browser_task("open_or_reuse_page", {"url": url, "match": match})
        return result.status == "ok" and bool(result.content)

    return _open_or_reuse_page_direct(url, match)


def _open_or_reuse_page_direct(url: str, match: str) -> bool:
    error = _validate_url(url)
    if error:
        return False

    pages, error = _pages()
    if error:
        return False

    query = match.lower()
    for page in pages:
        try:
            if query in page.url.lower() or query in page.title().lower():
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                page.bring_to_front()
                return True
        except Exception:
            continue

    context, error = _connect_context()
    if error:
        return False

    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=15000)
    page.bring_to_front()
    return True


def open_page(url: str) -> ToolResult:
    if not _in_browser_task_child():
        return _run_browser_task("open_page", {"url": url})

    return _open_page_direct(url)


def _open_page_direct(url: str) -> ToolResult:
    error = _validate_url(url)
    if error:
        return error

    context, error = _connect_context()
    if error:
        return error

    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=15000)
    page.bring_to_front()
    return ToolResult(status="ok", content="Opened page")


def list_open_pages() -> ToolResult:
    if not _in_browser_task_child():
        return _run_browser_task("list_open_pages", {})

    return _list_open_pages_direct()


def _list_open_pages_direct() -> ToolResult:
    pages, error = _pages()
    if error:
        return error

    return ToolResult(
        status="ok",
        content=[_page_summary(page, index) for index, page in enumerate(pages)],
    )


def close_page(title: str | None = None) -> ToolResult:
    if not _in_browser_task_child():
        return _run_browser_task("close_page", {"title": title})

    return _close_page_direct(title)


def _close_page_direct(title: str | None = None) -> ToolResult:
    pages, error = _pages()
    if error:
        return error

    if title:
        query = title.lower()
        matches = []
        for page in pages:
            try:
                if query in page.url.lower() or query in page.title().lower():
                    matches.append(page)
            except Exception:
                continue
    else:
        matches = pages[-1:] if pages else []

    if not matches:
        return ToolResult(status="error", error="No browser page found")

    matches[0].close()
    return ToolResult(status="ok", content="Closed page")


BROWSER_TOOLS = [
    Tool(
        name="open_page",
        description="Open a URL in the browser.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        function=open_page,
    ),
    Tool(
        name="close_page",
        description="Close a browser tab; optional title filter.",
        parameters={
            "type": "object",
            "properties": {"title": {"type": "string"}},
        },
        function=close_page,
    ),
    Tool(
        name="list_open_pages",
        description="List browser tabs.",
        parameters={"type": "object", "properties": {}},
        function=list_open_pages,
    ),
]
