from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RUNTIME_DIR = Path(__file__).resolve().parent
BASE_DIR = RUNTIME_DIR.parent
USERDATA_PATH = RUNTIME_DIR / "userdata.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_USERDATA: dict[str, Any] = {
    "user": {
        "name": "",
        "system_username": "",
        "language": "hu",
    },
    "app": {
        "created_at": "",
        "last_launch_at": "",
        "launch_count": 0,
        "last_launcher": "",
    },
    "setup": {
        "completed": False,
        "completed_at": "",
        "requirements_file": "runtime/requirements.txt",
        "model_assets_downloaded": False,
        "last_result": "",
        "last_error": "",
    },
    "onboarding": {
        "desktop_shortcut_prompted": False,
        "desktop_shortcut_created": False,
        "desktop_shortcut_error": "",
        "startup_shortcut_prompted": False,
        "startup_shortcut_created": False,
        "startup_shortcut_error": "",
        "openai_api_key_provided_at": "",
    },
    "credentials": {
        "openai_api_key": "",
    },
}


def _merge_defaults(data: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(value, merged[key])
        else:
            merged[key] = value
    return merged


def load_userdata() -> dict[str, Any]:
    if not USERDATA_PATH.exists():
        return deepcopy(DEFAULT_USERDATA)

    try:
        data = json.loads(USERDATA_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = deepcopy(DEFAULT_USERDATA)

    if not isinstance(data, dict):
        data = deepcopy(DEFAULT_USERDATA)

    return _merge_defaults(data, DEFAULT_USERDATA)


def save_userdata(data: dict[str, Any]) -> None:
    USERDATA_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def ensure_userdata() -> dict[str, Any]:
    data = load_userdata()
    if not data["app"].get("created_at"):
        data["app"]["created_at"] = _now()
    if not data["user"].get("system_username"):
        data["user"]["system_username"] = (
            os.environ.get("USERNAME")
            or os.environ.get("USER")
            or ""
        )
    save_userdata(data)
    return data


def update_setup_status(
    *,
    completed: bool,
    result: str,
    error: str = "",
    requirements_file: str = "runtime/requirements.txt",
    model_assets_downloaded: bool = False,
) -> dict[str, Any]:
    data = ensure_userdata()
    data["setup"]["completed"] = bool(completed)
    data["setup"]["requirements_file"] = requirements_file
    data["setup"]["model_assets_downloaded"] = bool(model_assets_downloaded)
    data["setup"]["last_result"] = result
    data["setup"]["last_error"] = error
    if completed:
        data["setup"]["completed_at"] = _now()
    save_userdata(data)
    return data


def register_launch(launcher: str) -> dict[str, Any]:
    data = ensure_userdata()
    data["app"]["launch_count"] = int(data["app"].get("launch_count", 0)) + 1
    data["app"]["last_launch_at"] = _now()
    data["app"]["last_launcher"] = launcher
    save_userdata(data)
    return data


def update_onboarding_status(**updates: Any) -> dict[str, Any]:
    data = ensure_userdata()
    data["onboarding"].update(updates)
    save_userdata(data)
    return data


def mark_openai_api_key_provided() -> dict[str, Any]:
    return update_onboarding_status(openai_api_key_provided_at=_now())


def get_openai_api_key() -> str:
    data = ensure_userdata()
    return str(data.get("credentials", {}).get("openai_api_key", "")).strip()


def has_openai_api_key() -> bool:
    return bool(get_openai_api_key())


def store_openai_api_key(api_key: str) -> dict[str, Any]:
    data = ensure_userdata()
    data["credentials"]["openai_api_key"] = api_key.strip()
    data["onboarding"]["openai_api_key_provided_at"] = _now()
    save_userdata(data)
    return data
