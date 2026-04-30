import sys
import os
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parent
BASE_DIR = RUNTIME_DIR.parent
sys.path.insert(0, str(BASE_DIR))

import atexit

from runtime.logging_setup import LOG_PATH, configure_logging


configure_logging()

_single_instance_mutex = None


def _ensure_single_instance() -> None:
    global _single_instance_mutex
    if sys.platform != "win32":
        return

    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    mutex = kernel32.CreateMutexW(None, False, "Local\\JarvisRuntimeSingleInstance")
    last_error = ctypes.get_last_error()
    if not mutex:
        return

    _single_instance_mutex = mutex
    if last_error == 183:
        print("Jarvis is already running.")
        sys.exit(0)


def _release_single_instance() -> None:
    if _single_instance_mutex is None or sys.platform != "win32":
        return

    import ctypes

    ctypes.windll.kernel32.CloseHandle(_single_instance_mutex)


_ensure_single_instance()
atexit.register(_release_single_instance)

from runtime.bootstrap import bootstrap_application

bootstrap_application()

import threading
import time

import logging

import frontend.gui as gui

gui.run_startup_onboarding()

import config
from backend.agent import ask_agent
from backend.audio.audio_ducking import restore as restore_audio_ducking
from backend.audio.sounds import START_SOUND, WAKE_SOUND, play_sound, play_sound_async
from backend.speech.record_speech import preload_vad_model, record_user_speech
from backend.speech.stt import transcribe
from backend.speech.wake_word import WakeWordDetector
from frontend.hotkeys import start_global_hotkeys
from backend.speech.tts import cancel_tts, queue_tts, wait_for_tts, stop_tts_worker

atexit.register(stop_tts_worker)
atexit.register(restore_audio_ducking)

_recording_lock = threading.Lock()
_active_recording_stop: threading.Event | None = None


def cancel_active_recording() -> None:
    with _recording_lock:
        if _active_recording_stop is not None:
            _active_recording_stop.set()


def watch_mute_cancellations() -> None:
    was_muted = gui.get_muted()

    while True:
        is_muted = gui.get_muted()
        if is_muted and not was_muted:
            cancel_tts()
            cancel_active_recording()
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
                try:
                    detected = detector.detect()
                except Exception as exc:
                    logging.exception("Wake word detection failed: %s", exc)
                    gui.send_message("Error", f"Wake word error: {exc}")
                    time.sleep(1.0)
                    return False

                if detected:
                    return True

def delay_listening(stop_event: threading.Event):
    time.sleep(config.calibration_seconds)
    if stop_event.is_set() or gui.get_muted():
        return
    gui.set_state("listening")
    play_wake_sound()


def record_speech() -> str | None:
    global _active_recording_stop

    if gui.get_muted():
        gui.set_state("muted")
        return None

    stop_event = threading.Event()
    with _recording_lock:
        _active_recording_stop = stop_event

    listening_thread = threading.Thread(
        target=delay_listening,
        args=(stop_event,),
        daemon=True,
    )
    listening_thread.start()

    try:
        audio_np = record_user_speech(
            should_stop=lambda: stop_event.is_set() or gui.get_muted()
        )
    finally:
        stop_event.set()
        with _recording_lock:
            if _active_recording_stop is stop_event:
                _active_recording_stop = None
        listening_thread.join(timeout=0.2)

    if audio_np is not None:
        if gui.get_muted():
            gui.set_state("muted")
            return None

        gui.set_state("thinking")
        text = transcribe(audio_np)
        if gui.get_muted():
            gui.set_state("muted")
            return None

        return text
    else:
        return None


def agent(user_input: str) -> None:
    gui.begin_thinking()
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
        gui.end_thinking()
        gui.set_state("muted" if gui.get_muted() else "idle")


def main() -> None:
    logging.info(
        "Jarvis runtime starting: executable=%s argv=%s cwd=%s launched_by=%s log=%s",
        sys.executable,
        sys.argv,
        Path.cwd(),
        os.environ.get("JARVIS_LAUNCHED_BY", ""),
        LOG_PATH,
    )
    print("Listening for wake word")
    preload_vad_model()
    should_wait_for_wake_word = True

    while True:
        if should_wait_for_wake_word:
            if not listen_for_wake_word():
                continue

        print("Recording started")
        text = record_speech()
        if not text:
            print("No text detected")
            should_wait_for_wake_word = True
            continue
        print(f"User: {text}")

        agent(text)
        should_wait_for_wake_word = False

if __name__ == "__main__":
    gui.set_text_command(agent)
    start_global_hotkeys(gui.toggle_mute)
    play_sound_async(START_SOUND, "Start sound")
    threading.Thread(target=watch_mute_cancellations, daemon=True).start()
    threading.Thread(target=main, daemon=True).start()
    gui.root.mainloop()
