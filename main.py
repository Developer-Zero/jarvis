import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Tools
import threading
import numpy as np

# Frontend tools
from playsound import playsound

# Other files
import config
from frontend.wake_word import wake_word
from backend.record_speech import record_user_speech
from frontend.stt import transcribe
from backend.agent import ask_agent
import frontend.gui as gui
from frontend.tts import queue_tts, wait_for_tts

def listen_for_wake_word():
    gui.set_state("idle")
    while True:
        if wake_word():
            print(f"Wake word detected")
            playsound(r"Assets\audio\wake.mp3")

            # Get input audio
            record_speech()
            return

def record_speech():
    gui.set_state("listening")
    audio_np = record_user_speech()
    if audio_np is not None:
        gui.set_state("thinking")
        print("Recording ended succesfully: transcribing starting")
        text = transcribe(audio_np)
        if not text.strip():
            print("Transcription ended with no text: returning to sleep mode")
            listen_for_wake_word()
        else:
            print(f"Audio transcription done: {text}")
            agent(text)
    else:
        print("Recording ended with no audio: returning to sleep mode")
        listen_for_wake_word()

def agent(input):
    gui.set_state("talking")
    gui.send_message("User", input)

    response = ask_agent(input)

    if response:
        gui.send_message("Jarvis", response)
        queue_tts(response)
        wait_for_tts()

    print("Recording started")
    record_speech()

def main():
    print("Listening for wake word")
    listen_for_wake_word()

if __name__ == "__main__":
    threading.Thread(target=main, daemon=True).start()
    gui.root.mainloop()