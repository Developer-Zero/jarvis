from config import tts_mode, tts_model, tts_pitch, tts_rate, tts_stability, tts_similarity_boost, II_API_KEY

import os
import tempfile
import edge_tts
import asyncio
import queue
import threading
from playsound import playsound

tts_queue = queue.Queue()

if tts_mode == "edge":
    def _tts(text):
        async def _run():
            fd, filename = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            pitch = tts_pitch
            rate = tts_rate
            communicate = edge_tts.Communicate(text=text, voice=tts_model, rate=rate, pitch=pitch)
            await communicate.save(filename)
            return filename
        filename = asyncio.run(_run())
        return filename
elif tts_mode == "pyttsx3":
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty('voice', tts_model)
    engine.setProperty('rate', 200 + int(tts_rate.replace("%", "")))
    engine.setProperty('pitch', 50 + int(tts_pitch.replace("Hz", "")))

    def _tts(text):
        fd, filename = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        engine.save_to_file(text, filename)
        engine.runAndWait()
        return filename
elif tts_mode == "openai":
    from openai import OpenAI
    client = OpenAI()

    def _tts(text):
        response = client.audio.speech.create(
            model=tts_model,
            input=text,
            voice_settings={"pitch": tts_pitch, "rate": tts_rate}
        )
        audio_data = response.audio.data
        fd, filename = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        with open(filename, "wb") as f:
            f.write(audio_data)
        return filename
elif tts_mode == "elevenlabs":
    import requests

    if not II_API_KEY:
        raise Exception("ElevenLabs API key not found. Please set the II_API_KEY variable in config.py.")

    def _tts(text):
         voice_id = tts_model # Jarvis voice
         url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
         headers = { "xi-api-key": II_API_KEY, "Content-Type": "application/json" } 
         payload = {
             "text": text, "model_id": "eleven_multilingual_v2", 
             "voice_settings": { "stability": tts_stability, "similarity_boost": tts_similarity_boost } 
         }
         response = requests.post(url, json=payload, headers=headers) 
         if response.status_code != 200: 
             raise Exception(f"TTS failed: {response.text}") 
         with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f: 
             f.write(response.content) 
             return f.name

def worker():
    while True:
        text = tts_queue.get()
        filename = None
        try:
            if text is None:
                break

            filename = _tts(text)
            playsound(filename)
        except Exception as e:
            print(f"TTS error: {e}")
        finally:
            if filename:
                try:
                    os.remove(filename)
                except FileNotFoundError:
                    pass
            tts_queue.task_done()

thread = threading.Thread(target=worker, daemon=True)
thread.start()

def queue_tts(text):
    if text:
        tts_queue.put(text)

def wait_for_tts():
    """Wait for all queued TTS tasks to complete"""
    tts_queue.join()


def stop_tts_worker():
    if thread.is_alive():
        tts_queue.put(None)