import time
from collections import deque

import numpy as np
import sounddevice as sd

from config import samplerate as config_samplerate

block_size = 512
_vad_model = None


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2) + 1e-10))


def normalize(audio: np.ndarray) -> np.ndarray:
    peak = np.max(np.abs(audio)) + 1e-8
    audio = audio / peak
    return np.tanh(audio * 1.4).astype(np.float32)


def get_vad_model():
    global _vad_model
    if _vad_model is None:
        import torch

        model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        _vad_model = model
    return _vad_model


def record_user_speech(
    vad_model=None,
    sample_rate: int = config_samplerate,
    block_size: int = 512,
    should_stop=None,

    calibration_seconds: float = 1.0,
    no_speech_timeout: float = 4.0,
    max_record_seconds: float = 15.0,

    min_speech_seconds: float = 0.35,
    silence_after_speech: float = 0.9,

    start_vad_threshold: float = 0.52,
    stop_vad_threshold: float = 0.38,

    start_energy_multiplier: float = 2.0,
    stop_energy_multiplier: float = 1.45,

    speech_start_frames: int = 2,
    speech_stop_frames: int = 10,

    prebuffer_seconds: float = 0.8,
):
    """
    Returns:
        np.ndarray audio, or None if no real speech was detected.
    """

    if vad_model is None:
        vad_model = get_vad_model()

    import torch

    print("Calibrating noise...")

    prebuffer_max_frames = int(prebuffer_seconds * sample_rate / block_size)
    prebuffer = deque(maxlen=prebuffer_max_frames)

    recorded = []
    noise_rms_values = []

    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
        blocksize=block_size
    ) as stream:

        # -------------------------
        # 1. Noise calibration
        # -------------------------
        calibration_end = time.perf_counter() + calibration_seconds

        while time.perf_counter() < calibration_end:
            if should_stop is not None and should_stop():
                print("Recording cancelled.")
                return None

            data, overflowed = stream.read(block_size)
            frame = data[:, 0].copy()

            frame_rms = rms(frame)
            noise_rms_values.append(frame_rms)

        if not noise_rms_values:
            return None

        # Robusztusabb, mint az átlag, mert kevésbé érzékeny zajtüskére
        noise_floor = float(np.percentile(noise_rms_values, 65))

        # Minimum, hogy teljes csendben se legyen irreálisan alacsony
        noise_floor = max(noise_floor, 0.0015)

        print(f"Noise floor: {noise_floor:.5f}")

        # -------------------------
        # 2. Recording state
        # -------------------------
        started = False
        speech_frames = 0
        silence_frames = 0

        speech_start_time = None
        last_real_speech_time = None
        global_start_time = time.perf_counter()

        while True:
            if should_stop is not None and should_stop():
                print("Recording cancelled.")
                return None

            now = time.perf_counter()

            # Emergency stop
            if now - global_start_time > max_record_seconds:
                print("Max recording time reached.")
                break

            data, overflowed = stream.read(block_size)
            frame = data[:, 0].copy()
            prebuffer.append(frame)

            frame_rms = rms(frame)

            # Silero VAD probability
            tensor = torch.from_numpy(frame)
            vad_prob = float(vad_model(tensor, sample_rate).item())

            # Adaptív energia-alapú feltétel
            start_energy_ok = frame_rms > noise_floor * start_energy_multiplier
            stop_energy_ok = frame_rms > noise_floor * stop_energy_multiplier

            # Külön start és stop logika hysteresis miatt
            if not started:
                is_speech = vad_prob >= start_vad_threshold and start_energy_ok

                if is_speech:
                    speech_frames += 1
                else:
                    speech_frames = max(0, speech_frames - 1)

                # Csak akkor induljon, ha több egymást követő frame beszéd
                if speech_frames >= speech_start_frames:
                    print("Speech started.")

                    started = True
                    speech_start_time = now
                    last_real_speech_time = now

                    recorded.extend(list(prebuffer))
                    prebuffer.clear()

                # Ha sokáig nincs valódi beszéd, return None
                if now - global_start_time > no_speech_timeout:
                    print("No speech detected.")
                    return None

            else:
                recorded.append(frame)

                is_still_speech = vad_prob >= stop_vad_threshold and stop_energy_ok

                if is_still_speech:
                    silence_frames = 0
                    last_real_speech_time = now
                else:
                    silence_frames += 1

                silence_duration = now - last_real_speech_time

                # Csak akkor álljon le, ha tényleg volt elég beszéd
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

    # Túl rövid “beszéd” kidobása
    duration = len(audio) / sample_rate
    if duration < min_speech_seconds:
        print("Rejected: too short.")
        return None

    audio = normalize(audio)
    return audio
