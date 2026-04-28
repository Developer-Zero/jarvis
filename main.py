import sys
from pathlib import Path

# Add parent directory to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Tools
import atexit
import shutil
import tempfile
import threading

# Frontend tools
from playsound import playsound

# Other files
from frontend.wake_word import WakeWordDetector
from backend.record_speech import record_user_speech
from frontend.stt import transcribe
from backend.agent import ask_agent
import frontend.gui as gui
from frontend.tts import queue_tts, wait_for_tts, stop_tts_worker

WAKE_SOUND = BASE_DIR / "Assets" / "audio" / "wake.mp3"
WAKE_SOUND_CACHE = Path(tempfile.gettempdir()) / "jarvis_wake.mp3"

atexit.register(stop_tts_worker)


def play_wake_sound() -> None:
    if not WAKE_SOUND.exists():
        print(f"Wake sound not found: {WAKE_SOUND}")
        return

    try:
        if (
            not WAKE_SOUND_CACHE.exists()
            or WAKE_SOUND_CACHE.stat().st_size != WAKE_SOUND.stat().st_size
        ):
            shutil.copyfile(WAKE_SOUND, WAKE_SOUND_CACHE)

        playsound(str(WAKE_SOUND_CACHE))
    except Exception as e:
        print(f"Wake sound playback failed: {e}")


def listen_for_wake_word() -> bool:
    gui.set_state("idle")

    with WakeWordDetector() as detector:
        while True:
            if detector.detect():
                print("Wake word detected")
                play_wake_sound()
                return True


def record_speech() -> str | None:
    gui.set_state("listening")
    audio_np = record_user_speech()
    if audio_np is not None:
        gui.set_state("thinking")
        print("Recording ended successfully: transcribing starting")
        text = transcribe(audio_np)
        if not text.strip():
            print("Transcription ended with no text: returning to sleep mode")
            return None
        else:
            print(f"Audio transcription done: {text}")
            return text
    else:
        print("Recording ended with no audio: returning to sleep mode")
        return None


def agent(user_input: str) -> None:
    gui.set_state("talking")
    gui.send_message("User", user_input)

    response = ask_agent(user_input)

    if response:
        gui.send_message("Jarvis", response)
        queue_tts(response)
        wait_for_tts()


def main() -> None:
    print("Listening for wake word")
    should_wait_for_wake_word = True

    while True:
        if should_wait_for_wake_word:
            listen_for_wake_word()

        print("Recording started")
        text = record_speech()
        if not text:
            should_wait_for_wake_word = True
            continue

        agent(text)
        should_wait_for_wake_word = False

if __name__ == "__main__":
    threading.Thread(target=main, daemon=True).start()
    gui.root.mainloop()
