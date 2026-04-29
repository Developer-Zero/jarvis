import shutil
import tempfile
import threading
from pathlib import Path

from playsound import playsound


BASE_DIR = Path(__file__).resolve().parents[2]
AUDIO_DIR = BASE_DIR / "Assets" / "audio"

WAKE_SOUND = AUDIO_DIR / "wake.mp3"
START_SOUND = AUDIO_DIR / "start.wav"
MUTE_SOUND = AUDIO_DIR / "mute.wav"
UNMUTE_SOUND = AUDIO_DIR / "unmute.wav"


def _cached_sound_path(sound_path: Path) -> Path:
    cache_path = Path(tempfile.gettempdir()) / f"jarvis_{sound_path.name}"
    if not cache_path.exists() or cache_path.stat().st_size != sound_path.stat().st_size:
        shutil.copyfile(sound_path, cache_path)
    return cache_path


def play_sound(sound_path: Path, label: str = "Sound") -> None:
    if not sound_path.exists():
        print(f"{label} not found: {sound_path}")
        return

    try:
        playsound(str(_cached_sound_path(sound_path)))
    except Exception as exc:
        print(f"{label} playback failed: {exc}")


def play_sound_async(sound_path: Path, label: str = "Sound") -> None:
    threading.Thread(target=play_sound, args=(sound_path, label), daemon=True).start()
