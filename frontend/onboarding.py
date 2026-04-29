from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from userdata import (
    BASE_DIR,
    ensure_userdata,
    has_openai_api_key,
    store_openai_api_key as save_openai_api_key,
    update_onboarding_status,
)


APP_NAME = "Jarvis"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
SHORTCUT_ICON = BASE_DIR / "Assets" / "sprites" / "shortcut.ico"


def should_ask_for_desktop_shortcut() -> bool:
    data = ensure_userdata()
    onboarding = data.get("onboarding", {})
    return not bool(onboarding.get("desktop_shortcut_prompted"))


def needs_openai_api_key() -> bool:
    return not has_openai_api_key() and not bool(os.environ.get(OPENAI_API_KEY_ENV))


def decline_desktop_shortcut() -> None:
    update_onboarding_status(
        desktop_shortcut_prompted=True,
        desktop_shortcut_created=False,
        desktop_shortcut_error="",
    )


def create_desktop_shortcut() -> dict[str, object]:
    result = _create_desktop_shortcut()
    update_onboarding_status(
        desktop_shortcut_prompted=True,
        desktop_shortcut_created=result["success"],
        desktop_shortcut_error=result["error"],
    )
    return result


def store_openai_api_key(api_key: str) -> None:
    os.environ[OPENAI_API_KEY_ENV] = api_key
    save_openai_api_key(api_key)


def _create_desktop_shortcut() -> dict[str, object]:
    desktop = _desktop_path()
    desktop.mkdir(parents=True, exist_ok=True)
    shortcut_path = desktop / f"{APP_NAME}.lnk"
    target_path = _launcher_target()
    icon_location = _shortcut_icon_path(target_path)

    arguments = ""
    if target_path.suffix.lower() == ".py":
        pythonw = _pythonw_path()
        if pythonw:
            arguments = f'"{target_path}"'
            target_path = Path(pythonw)
        else:
            arguments = f'"{target_path}"'
            target_path = Path(sys.executable)

    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        (
            "$shell = New-Object -ComObject WScript.Shell; "
            f"$shortcut = $shell.CreateShortcut('{_ps_escape(shortcut_path)}'); "
            f"$shortcut.TargetPath = '{_ps_escape(target_path)}'; "
            f"$shortcut.Arguments = '{_ps_escape(arguments)}'; "
            f"$shortcut.WorkingDirectory = '{_ps_escape(BASE_DIR)}'; "
            f"$shortcut.IconLocation = '{_ps_escape(icon_location)}'; "
            "$shortcut.Save()"
        ),
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip()
        return {"success": False, "error": error or f"PowerShell exited with {completed.returncode}"}

    return {"success": True, "error": ""}


def _desktop_path() -> Path:
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        return Path(user_profile) / "Desktop"
    return Path.home() / "Desktop"


def _launcher_target() -> Path:
    exe_path = BASE_DIR / "Jarvis.exe"
    if exe_path.exists():
        return exe_path
    return BASE_DIR / "main.py"


def _shortcut_icon_path(fallback: Path) -> Path:
    if SHORTCUT_ICON.exists():
        return SHORTCUT_ICON
    return fallback


def _pythonw_path() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "python.exe":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return str(executable)


def _ps_escape(value: object) -> str:
    return str(value).replace("'", "''")
