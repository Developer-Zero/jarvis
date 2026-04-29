import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

from backend.speech.audio_session import input_stream_lock
from config import (
    calibration_seconds,
    max_record_seconds,
    min_speech_seconds,
    no_speech_timeout,
    prebuffer_seconds,
    silence_after_speech,
    speech_start_frames,
    speech_stop_frames,
    start_energy_multiplier,
    start_vad_threshold,
    stop_energy_multiplier,
    stop_vad_threshold,
)


block_size = 512
samplerate = 16000
_vad_model = None
_vad_model_lock = threading.Lock()


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2) + 1e-10))


def normalize(audio: np.ndarray) -> np.ndarray:
    peak = np.max(np.abs(audio)) + 1e-8
    audio = audio / peak
    return np.tanh(audio * 1.4).astype(np.float32)


def get_vad_model():
    global _vad_model
    if _vad_model is not None:
        return _vad_model

    with _vad_model_lock:
        if _vad_model is None:
            print("Loading VAD model...")
            import torch

            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                trust_repo=True,
            )
            _vad_model = model
    return _vad_model


def preload_vad_model() -> threading.Thread:
    thread = threading.Thread(target=get_vad_model, daemon=True)
    thread.start()
    return thread


def _cancelled(should_stop) -> bool:
    return should_stop is not None and should_stop()


def record_user_speech(
    vad_model=None,
    sample_rate: int = samplerate,
    block_size: int = block_size,
    should_stop=None,
    calibration_seconds: float = calibration_seconds,
    no_speech_timeout: float = no_speech_timeout,
    max_record_seconds: float = max_record_seconds,
    min_speech_seconds: float = min_speech_seconds,
    silence_after_speech: float = silence_after_speech,
    start_vad_threshold: float = start_vad_threshold,
    stop_vad_threshold: float = stop_vad_threshold,
    start_energy_multiplier: float = start_energy_multiplier,
    stop_energy_multiplier: float = stop_energy_multiplier,
    speech_start_frames: int = speech_start_frames,
    speech_stop_frames: int = speech_stop_frames,
    prebuffer_seconds: float = prebuffer_seconds,
):
    """
    Returns np.ndarray audio, or None if no real speech was detected.
    """

    if vad_model is None:
        vad_model = get_vad_model()

    import torch

    prebuffer_max_frames = int(prebuffer_seconds * sample_rate / block_size)
    prebuffer = deque(maxlen=prebuffer_max_frames)
    recorded = []
    noise_rms_values = []

    with input_stream_lock:
        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=block_size,
        ) as stream:
            calibration_end = time.perf_counter() + calibration_seconds

            while time.perf_counter() < calibration_end:
                if _cancelled(should_stop):
                    print("Recording cancelled.")
                    return None

                data, _overflowed = stream.read(block_size)
                if _cancelled(should_stop):
                    print("Recording cancelled.")
                    return None

                frame = data[:, 0].copy()
                noise_rms_values.append(rms(frame))

            if not noise_rms_values:
                return None

            noise_floor = float(np.percentile(noise_rms_values, 65))
            noise_floor = max(noise_floor, 0.0015)
            print(f"Noise floor: {noise_floor:.5f}")

            started = False
            speech_frames = 0
            silence_frames = 0
            speech_start_time = None
            last_real_speech_time = None
            global_start_time = time.perf_counter()

            while True:
                if _cancelled(should_stop):
                    print("Recording cancelled.")
                    return None

                now = time.perf_counter()
                if now - global_start_time > max_record_seconds:
                    print("Max recording time reached.")
                    break

                data, _overflowed = stream.read(block_size)
                if _cancelled(should_stop):
                    print("Recording cancelled.")
                    return None

                frame = data[:, 0].copy()
                prebuffer.append(frame)
                frame_rms = rms(frame)

                tensor = torch.from_numpy(frame)
                vad_prob = float(vad_model(tensor, sample_rate).item())
                start_energy_ok = frame_rms > noise_floor * start_energy_multiplier
                stop_energy_ok = frame_rms > noise_floor * stop_energy_multiplier

                if not started:
                    is_speech = vad_prob >= start_vad_threshold and start_energy_ok
                    if is_speech:
                        speech_frames += 1
                    else:
                        speech_frames = max(0, speech_frames - 1)

                    if speech_frames >= speech_start_frames:
                        print("Speech started.")
                        started = True
                        speech_start_time = now
                        last_real_speech_time = now
                        recorded.extend(list(prebuffer))
                        prebuffer.clear()

                    if now - global_start_time > no_speech_timeout:
                        print("No speech detected.")
                        return None
                    continue

                recorded.append(frame)
                is_still_speech = vad_prob >= stop_vad_threshold and stop_energy_ok

                if is_still_speech:
                    silence_frames = 0
                    last_real_speech_time = now
                else:
                    silence_frames += 1

                silence_duration = now - last_real_speech_time
                speech_duration = now - speech_start_time

                enough_speech = speech_duration >= min_speech_seconds
                enough_silence = silence_duration >= silence_after_speech
                enough_silent_frames = silence_frames >= speech_stop_frames

                if enough_speech and enough_silence and enough_silent_frames:
                    print("Speech ended.")
                    break

    if not recorded:
        return None

    audio = np.concatenate(recorded).astype(np.float32)
    duration = len(audio) / sample_rate
    if duration < min_speech_seconds:
        print("Rejected: too short.")
        return None

    return normalize(audio)
