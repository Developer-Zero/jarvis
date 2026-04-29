import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from bootstrap import bootstrap_application

bootstrap_application()

import atexit
import threading
import time

import frontend.gui as gui

gui.run_startup_onboarding()

from backend.agent import ask_agent
from backend.audio.audio_ducking import restore as restore_audio_ducking
from backend.audio.sounds import START_SOUND, WAKE_SOUND, play_sound, play_sound_async
from backend.speech.record_speech import record_user_speech
from backend.speech.stt import transcribe
from backend.speech.wake_word import WakeWordDetector
from frontend.hotkeys import start_global_hotkeys
from backend.speech.tts import cancel_tts, queue_tts, wait_for_tts, stop_tts_worker

atexit.register(stop_tts_worker)
atexit.register(restore_audio_ducking)


def watch_mute_cancellations() -> None:
    was_muted = gui.get_muted()

    while True:
        is_muted = gui.get_muted()
        if is_muted and not was_muted:
            cancel_tts()
        was_muted = is_muted
        time.sleep(0.05)


def play_wake_sound() -> None:
    play_sound(WAKE_SOUND, "Wake sound")


def listen_for_wake_word() -> bool:
    gui.set_state("idle")

    while True:
        if gui.get_muted():
            gui.set_state("muted")
            time.sleep(0.1)
            continue

        with WakeWordDetector() as detector:
            while not gui.get_muted():
                if detector.detect():
                    print("Wake word detected")
                    play_wake_sound()
                    return True


def record_speech() -> str | None:
    if gui.get_muted():
        gui.set_state("muted")
        return None

    gui.set_state("listening")
    audio_np = record_user_speech(should_stop=gui.get_muted)
    if audio_np is not None:
        if gui.get_muted():
            gui.set_state("muted")
            return None

        gui.set_state("thinking")
        print("Recording ended successfully: transcribing starting")
        text = transcribe(audio_np)
        if gui.get_muted():
            gui.set_state("muted")
            return None

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
    try:
        gui.send_message("User", user_input)
        gui.set_state("thinking")

        response = ask_agent(user_input)
        if gui.get_muted():
            return

        if response:
            gui.send_message("Jarvis", response)
            if gui.get_muted():
                cancel_tts()
                return

            queue_tts(response)
            wait_for_tts()
    finally:
        gui.set_state("muted" if gui.get_muted() else "idle")


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
    gui.set_text_command(agent)
    start_global_hotkeys(gui.toggle_mute)
    play_sound_async(START_SOUND, "Start sound")
    threading.Thread(target=watch_mute_cancellations, daemon=True).start()
    threading.Thread(target=main, daemon=True).start()
    gui.root.mainloop()
