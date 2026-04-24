import time
import numpy as np
import sounddevice as sd
from collections import deque

from config import silence_duration, think_time, samplerate, block_size

# ---------------------------
# Utils
# ---------------------------

def rms(x):
    return np.sqrt(np.mean(x**2) + 1e-10)

def normalize(audio):
    peak = np.max(np.abs(audio)) + 1e-8
    audio = audio / peak
    return np.tanh(audio * 1.5).astype(np.float32)

# ---------------------------
# Main
# ---------------------------

def record_user_speech():
    print("Recording started")

    # ----------- KALIBRÁCIÓ -----------
    print("Calibrating noise...")
    with sd.InputStream(samplerate=samplerate, channels=1, dtype='float32', blocksize=block_size) as stream:
        noise_samples = []
        start = time.perf_counter()

        while time.perf_counter() - start < 0.5:
            data, _ = stream.read(block_size)
            audio_np = np.frombuffer(data, dtype=np.float32)
            noise_samples.append(rms(audio_np))

    noise_floor = np.mean(noise_samples)

    # CLAMP (kritikus stabilitás miatt)
    noise_floor = np.clip(noise_floor, 1e-4, 0.02)

    START_TH = noise_floor * 2.0 + 1e-4
    STOP_TH  = noise_floor * 1.3 + 1e-4
    prev_energy = 0.0

    print(f"Noise floor: {noise_floor:.5f}")
    print(f"START_TH: {START_TH:.5f}, STOP_TH: {STOP_TH:.5f}")

    # ----------- PREBUFFER -----------
    pre_buffer = deque(maxlen=int(0.3 * samplerate))
    full_audio = []

    speaking = False
    last_voice_time = None
    speech_start_time = None

    HARD_TIMEOUT = 10
    start_time = time.perf_counter()

    with sd.InputStream(samplerate=samplerate, channels=1, dtype='float32', blocksize=block_size) as stream:
        while True:
            data, _ = stream.read(block_size)
            audio_np = np.frombuffer(data, dtype=np.float32)

            e = rms(audio_np)
            delta = abs(e - prev_energy)
            prev_energy = e

            # DEBUG (ha kell)
            # print(f"energy={e:.5f}")

            pre_buffer.extend(audio_np)

            # -------- START DETECTION --------
            if not speaking:
                if e > START_TH:
                    speaking = True
                    speech_start_time = time.perf_counter()
                    last_voice_time = time.perf_counter()

                    full_audio.extend(pre_buffer)
                    print("Speech started")

            # -------- RECORD --------
            if speaking:
                full_audio.extend(audio_np)

                if e > STOP_TH and delta > noise_floor * 0.5:
                    last_voice_time = time.perf_counter()

                if time.perf_counter() - last_voice_time > silence_duration:
                    print("Speech ended (silence)")
                    break

            # -------- NO SPEECH --------
            if not speaking and (time.perf_counter() - start_time > think_time):
                print("No speech detected")
                return None

            # -------- HARD TIMEOUT --------
            if time.perf_counter() - start_time > HARD_TIMEOUT:
                print("Hard timeout")
                break

    # -------- VALIDÁLÁS --------
    if not speaking:
        return None

    audio_np = np.array(full_audio, dtype=np.float32)

    if len(audio_np) == 0:
        return None

    duration = len(audio_np) / samplerate

    # -------- FRAME ANALYSIS --------
    frame_size = int(0.02 * samplerate)
    usable_len = (len(audio_np) // frame_size) * frame_size

    if usable_len == 0:
        return None

    frames = audio_np[:usable_len].reshape(-1, frame_size)
    energies = np.sqrt(np.mean(frames**2, axis=1))

    speech_frames = energies > (noise_floor * 2.0)
    speech_ratio = np.mean(speech_frames)
    avg_energy = np.mean(energies)

    print(f"Speech ratio: {speech_ratio:.2f}, Avg energy: {avg_energy:.5f}, Duration: {duration:.2f}")

    # -------- DÖNTÉS --------
    if (
        duration < 1.6 or
        speech_ratio < 0.2 or
        avg_energy < noise_floor * 10
    ):
        print("Rejected: no real speech")
        return None

    # -------- ZAJGATE --------
    audio_np[np.abs(audio_np) < noise_floor * 1.5] = 0

    # -------- NORMALIZE --------
    audio_np = normalize(audio_np)

    print("Recording done")

    return audio_np