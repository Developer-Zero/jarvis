from __future__ import annotations

from runtime.setup import run_setup
from runtime.userdata import ensure_userdata, register_launch


def _show_setup_error(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Jarvis setup failed", message)
        root.destroy()
    except Exception:
        print(message)


def bootstrap_application() -> None:
    data = ensure_userdata()
    setup_data = data.get("setup", {})

    if not setup_data.get("completed") or not setup_data.get("model_assets_downloaded"):
        print("Setup incomplete. Running runtime/setup.py...")
        result = run_setup()
        if not result.get("success"):
            error = result.get("error") or "Unknown setup error"
            _show_setup_error(f"Setup failed: {error}")
            raise RuntimeError(f"Setup failed: {error}")

    register_launch("runtime/main.py")
