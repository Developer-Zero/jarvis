import ctypes
import ctypes.wintypes
import threading

from config import vk_mute


def start_global_hotkeys(on_mute) -> None:
    if not hasattr(ctypes, "windll"):
        print("Global F6 hotkey unavailable: ctypes windll missing.")
        return

    threading.Thread(target=_global_hotkey_worker, args=(on_mute,), daemon=True).start()


def _global_hotkey_worker(on_mute) -> None:
    user32 = ctypes.windll.user32
    hotkey_id = 1
    mod_norepeat = 0x4000
    vk_f6 = vk_mute
    wm_hotkey = 0x0312

    if not user32.RegisterHotKey(None, hotkey_id, mod_norepeat, vk_f6):
        print("Global F6 hotkey registration failed.")
        return

    try:
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == wm_hotkey and msg.wParam == hotkey_id:
                on_mute()
    finally:
        user32.UnregisterHotKey(None, hotkey_id)
