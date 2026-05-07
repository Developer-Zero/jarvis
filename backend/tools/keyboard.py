import ctypes
import time


VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_CONTROL = 0x11
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_C = 0x43
VK_L = 0x4C
VK_V = 0x56
VK_W = 0x57


def press_key(key: int) -> None:
    ctypes.windll.user32.keybd_event(key, 0, 0, 0)
    ctypes.windll.user32.keybd_event(key, 0, 2, 0)


def press_hotkey(*keys: int) -> None:
    for key in keys:
        ctypes.windll.user32.keybd_event(key, 0, 0, 0)
        time.sleep(0.02)

    for key in reversed(keys):
        ctypes.windll.user32.keybd_event(key, 0, 2, 0)
        time.sleep(0.02)
