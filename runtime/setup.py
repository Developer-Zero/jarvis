from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parent
BASE_DIR = RUNTIME_DIR.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from runtime.userdata import update_setup_status


REQUIREMENTS_PATH = RUNTIME_DIR / "requirements.txt"


def _python_for_pip() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        console_python = executable.with_name("python.exe")
        if console_python.exists():
            return str(console_python)
    return sys.executable


def install_requirements() -> dict[str, object]:
    if not REQUIREMENTS_PATH.exists():
        return {
            "success": False,
            "returncode": 1,
            "stage": "requirements",
            "error": f"Missing requirements file: {REQUIREMENTS_PATH}",
        }

    command = [
        _python_for_pip(),
        "-m",
        "pip",
        "install",
        "-r",
        str(REQUIREMENTS_PATH),
    ]

    try:
        completed = subprocess.run(command, cwd=BASE_DIR)
    except Exception as exc:
        return {
            "success": False,
            "returncode": 1,
            "stage": "requirements",
            "error": str(exc),
        }

    return {
        "success": completed.returncode == 0,
        "returncode": completed.returncode,
        "stage": "requirements",
        "error": "" if completed.returncode == 0 else f"pip exited with {completed.returncode}",
    }


def download_model_assets() -> dict[str, object]:
    try:
        print("Downloading openWakeWord models...")
        import openwakeword.utils

        openwakeword.utils.download_models()

        print("Downloading Silero VAD model...")
        import torch

        torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
    except Exception as exc:
        return {
            "success": False,
            "returncode": 1,
            "stage": "model assets",
            "error": str(exc),
        }

    return {
        "success": True,
        "returncode": 0,
        "stage": "model assets",
        "error": "",
    }


def run_setup() -> dict[str, object]:
    result = install_requirements()
    success = bool(result.get("success"))
    error = str(result.get("error") or "")
    stage = str(result.get("stage") or "requirements")

    if success:
        result = download_model_assets()
        success = bool(result.get("success"))
        error = str(result.get("error") or "")
        stage = str(result.get("stage") or "model assets")

    status = "setup complete" if success else f"{stage} failed"

    update_setup_status(
        completed=success,
        result=status,
        error=error,
        requirements_file=str(REQUIREMENTS_PATH.relative_to(BASE_DIR)),
        model_assets_downloaded=success,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Jarvis requirements and speech models.")
    parser.parse_args()

    result = run_setup()
    if result.get("success"):
        print("Setup complete.")
        return 0

    print(f"Setup failed: {result.get('error')}")
    return int(result.get("returncode") or 1)


if __name__ == "__main__":
    raise SystemExit(main())
