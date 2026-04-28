from config import tts_mode, tts_model

import os
import tempfile
import edge_tts
import asyncio
import queue
import threading
from playsound import playsound

tts_queue = queue.Queue()

def _tts(text):
    async def _run():
        fd, filename = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        pitch = "-13Hz"
        rate = "+1%"
        communicate = edge_tts.Communicate(text=text, voice=tts_model, rate=rate, pitch=pitch)
        await communicate.save(filename)
        return filename
    filename = asyncio.run(_run())
    return filename

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


# II api keys: 
code = """
    voice_id = "M336tBVZHWWiWb4R54ui" # Jarvis voice
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = { "xi-api-key": II_api_key, "Content-Type": "application/json" } 
    payload = {
        "text": text, "model_id": "eleven_multilingual_v2", 
        "voice_settings": { "stability": 0.5, "similarity_boost": 0.75 } 
    }
    response = requests.post(url, json=payload, headers=headers) 
    if response.status_code != 200: 
        raise Exception(f"TTS failed: {response.text}") 
    # temp mp3 file with tempfile.NamedTemporaryFile(delete=True, suffix=".mp3") as f: 
        f.write(response.content) f.flush() playsound(f.name)
    """
