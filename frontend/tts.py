from config import tts_mode, tts_model

import tempfile
import edge_tts
import asyncio
import queue
import threading
from playsound import playsound

tts_queue = queue.Queue()

def _tts(text):
    async def _run():
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            filename = f.name
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
        if text is None:
            break
        filename = _tts(text)
        playsound(filename)
        tts_queue.task_done()

thread = threading.Thread(target=worker, daemon=True)
thread.start()

def queue_tts(text):
    if text:
        tts_queue.put(text)

def wait_for_tts():
    """Wait for all queued TTS tasks to complete"""
    tts_queue.join()


# II api keys: 
code = """
    voice_id = "M336tBVZHWWiWb4R54ui"
    II_api_key = "sk_bb4beba0668dc9fdfe582f2dfcf16b10674f11bb6bc243c1"
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
