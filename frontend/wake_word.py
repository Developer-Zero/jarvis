import numpy as np

from config import wake_word_model, wake_word_threshold
samplerate = 16000
block_size = 1024


class WakeWordDetector:
    def __init__(
        self,
        model_name: str = wake_word_model,
        threshold: float = wake_word_threshold,
        sample_rate: int = samplerate,
        frame_size: int = block_size,
    ):
        self.model_name = model_name
        self.threshold = threshold
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self.model = None
        self.pyaudio = None
        self.stream = None

    def start(self) -> None:
        if self.stream is not None:
            return

        import pyaudio
        from openwakeword.model import Model

        self.model = Model(
            wakeword_models=[self.model_name],
            inference_framework="onnx",
        )
        self.pyaudio = pyaudio.PyAudio()
        self.stream = self.pyaudio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.frame_size,
        )

    def detect(self) -> bool:
        self.start()
        data = self.stream.read(self.frame_size, exception_on_overflow=False)
        audio_chunk = np.frombuffer(data, dtype=np.int16)
        prediction = self.model.predict(audio_chunk)

        if prediction[self.model_name] > self.threshold:
            self.model.reset()
            return True
        return False

    def close(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop_stream()
            finally:
                self.stream.close()
                self.stream = None

        if self.pyaudio is not None:
            self.pyaudio.terminate()
            self.pyaudio = None

        self.model = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


_default_detector = None


def wake_word() -> bool:
    """Compatibility wrapper for older callers."""
    global _default_detector
    if _default_detector is None:
        _default_detector = WakeWordDetector()
    return _default_detector.detect()


def close_wake_word() -> None:
    global _default_detector
    if _default_detector is not None:
        _default_detector.close()
        _default_detector = None
