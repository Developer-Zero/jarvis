# Important
language = "hu"

# Fix
samplerate = 16000
block_size = 1024

# Wake word detection
wake_word_model = "hey_jarvis" # models: "hey_jarvis", "hey_alexa", "hey_google", etc.
wake_word_threshold = 0.22 # sensitive 0-1 non-sensitive

# Speech recording
silence_duration = 1 # To end recording in seconds
think_time = 4 # Time to think when recording starts

# Speech To Text
stt_mode = "openai" # "openai", "whisper"
stt_model = "gpt-4o-mini-transcribe" # "openai": "gpt-4o-mini-transcribe" | "whisper": "tiny", "base", "small", "medium", "large"
stt_language = language

# Text To Speech
tts_mode = "openai" # "edge", "II", "pyttsx3", "openai"
tts_model = "hu-HU-TamasNeural"# "edge": "hu-HU-TamasNeural"

# Text To Text
ttt_mode = "openai" # "openai", "ollama"
ttt_model = "gpt-4.1-mini" # "openai": "gpt-4.1-mini" | "ollama": "mistral:7b", "llama3"
ttt_language = language

# Agent
max_message_history = 10 # +1 the default prompt
max_query_length = 800 # characters a query can return (example: website text)
max_steps = 5 # How many times can the model be asked in 1 input

