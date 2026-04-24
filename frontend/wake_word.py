import numpy as np
import pyaudio
from openwakeword.model import Model

from config import wake_word_model, wake_word_threshold, block_size, samplerate

model = Model(wakeword_models=[wake_word_model],inference_framework="onnx")
p = pyaudio.PyAudio()
stream = p.open(
    format=pyaudio.paInt16,
    channels=1,
    rate=samplerate,
    input=True,
    frames_per_buffer=block_size
)

def wake_word():
    data = stream.read(block_size, exception_on_overflow=False)

    audio_chunk = np.frombuffer(data, dtype=np.int16)
    # prediction
    prediction = model.predict(audio_chunk)

    if prediction[wake_word_model] > wake_word_threshold:
        model.reset()
        return True
    return False