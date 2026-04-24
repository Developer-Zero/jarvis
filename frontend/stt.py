from config import samplerate, stt_language, stt_mode, stt_model

if stt_mode == "openai":
    from openai import OpenAI
    import tempfile
    import soundfile as sf

    client = OpenAI()

    def transcribe(audio_np):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            sf.write(f.name, audio_np, samplerate)

            with open(f.name, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=stt_model,
                    file=audio_file,
                    language=stt_language
                )
        return transcript.text


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