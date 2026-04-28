import asyncio
import ctypes
import os
import queue
import sys
import tempfile
import threading
import time

from playsound import playsound

from config import (
    II_API_KEY,
    tts_mode,
    tts_model,
    tts_pitch,
    tts_rate,
    tts_similarity_boost,
    tts_stability,
)


# 1. Queue / worker
_tts_queue = queue.Queue()
_tts_stop_event = threading.Event()
_worker_stop_item = object()


def queue_tts(text):
    if text:
        _tts_stop_event.clear()
        _tts_queue.put(text)


def wait_for_tts():
    """Wait for all queued TTS tasks to complete."""
    _tts_queue.join()


def cancel_tts():
    _tts_stop_event.set()
    _clear_pending_tts()


def stop_tts_worker():
    cancel_tts()
    if _worker_thread.is_alive():
        _tts_queue.put(_worker_stop_item)


def _clear_pending_tts():
    while True:
        try:
            _tts_queue.get_nowait()
        except queue.Empty:
            break
        _tts_queue.task_done()


def _tts_worker():
    while True:
        item = _tts_queue.get()
        filename = None

        try:
            if item is _worker_stop_item:
                break

            if _tts_stop_event.is_set():
                continue

            filename = synthesize_to_file(item)
            if not _tts_stop_event.is_set():
                play_file_interruptible(filename)
        except Exception as e:
            print(f"TTS error: {e}")
        finally:
            if filename:
                _delete_temp_file(filename)
            _tts_queue.task_done()


def _delete_temp_file(filename):
    try:
        os.remove(filename)
    except FileNotFoundError:
        pass


# 2. Model call -> file creation
if tts_mode == "edge":
    import edge_tts

    def synthesize_to_file(text):
        async def _run():
            fd, filename = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            communicate = edge_tts.Communicate(
                text=text,
                voice=tts_model,
                rate=tts_rate,
                pitch=tts_pitch,
            )
            await communicate.save(filename)
            return filename

        return asyncio.run(_run())
elif tts_mode == "pyttsx3":
    import pyttsx3

    engine = pyttsx3.init()
    engine.setProperty("voice", tts_model)
    engine.setProperty("rate", 200 + int(tts_rate.replace("%", "")))
    engine.setProperty("pitch", 50 + int(tts_pitch.replace("Hz", "")))

    def synthesize_to_file(text):
        fd, filename = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        engine.save_to_file(text, filename)
        engine.runAndWait()
        return filename
elif tts_mode == "openai":
    from openai import OpenAI

    client = OpenAI()

    def synthesize_to_file(text):
        response = client.audio.speech.create(
            model=tts_model,
            input=text,
            voice_settings={"pitch": tts_pitch, "rate": tts_rate},
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

    def synthesize_to_file(text):
        voice_id = tts_model
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {"xi-api-key": II_API_KEY, "Content-Type": "application/json"}
        payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": tts_stability,
                "similarity_boost": tts_similarity_boost,
            },
        }
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            raise Exception(f"TTS failed: {response.text}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            f.write(response.content)
            return f.name
else:
    raise ValueError(f"Unsupported tts_mode: {tts_mode}")


# 3. Playsound + interruption
def play_file_interruptible(filename):
    if sys.platform == "win32":
        _play_audio_windows(filename)
    else:
        playsound(filename)


def _mci(command):
    error_buffer = ctypes.create_unicode_buffer(255)
    result = ctypes.windll.winmm.mciSendStringW(command, None, 0, None)
    if result:
        ctypes.windll.winmm.mciGetErrorStringW(result, error_buffer, len(error_buffer))
        raise RuntimeError(error_buffer.value or f"MCI error {result}")


def _mci_status(alias, item):
    buffer = ctypes.create_unicode_buffer(255)
    result = ctypes.windll.winmm.mciSendStringW(
        f"status {alias} {item}",
        buffer,
        len(buffer),
        None,
    )
    if result:
        return ""
    return buffer.value


def _play_audio_windows(filename):
    alias = f"jarvis_tts_{threading.get_ident()}"
    escaped = filename.replace('"', '\\"')

    try:
        _mci(f'open "{escaped}" type mpegvideo alias {alias}')
        _mci(f"play {alias}")

        while not _tts_stop_event.is_set():
            mode = _mci_status(alias, "mode")
            if mode in ("stopped", "not ready", ""):
                break
            time.sleep(0.05)

        if _tts_stop_event.is_set():
            try:
                _mci(f"stop {alias}")
            except Exception:
                pass
    finally:
        try:
            _mci(f"close {alias}")
        except Exception:
            pass


_worker_thread = threading.Thread(target=_tts_worker, daemon=True)
_worker_thread.start()
