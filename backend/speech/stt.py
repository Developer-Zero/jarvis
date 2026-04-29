from config import stt_language, stt_mode, stt_model
from runtime.userdata import get_openai_api_key

samplerate = 16000

if stt_mode == "openai":
    from openai import OpenAI
    import os
    import tempfile
    import soundfile as sf

    api_key = get_openai_api_key()
    client = OpenAI(api_key=api_key) if api_key else OpenAI()

    def transcribe(audio_np):
        fd, filename = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

        try:
            sf.write(filename, audio_np, samplerate)

            with open(filename, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=stt_model,
                    file=audio_file,
                    language=stt_language
                )
            return transcript.text
        finally:
            try:
                os.remove(filename)
            except FileNotFoundError:
                pass


elif stt_mode == "whisper":
    from whisper import WhisperModel

    model = WhisperModel(stt_model, compute_type="float32")

    def transcribe(audio_np) -> str:
        
        segments, _ = model.transcribe(
            audio_np,
            language=stt_language,
            vad_filter=True
        )

        text = "".join(segment.text for segment in segments)
        return text.strip()
