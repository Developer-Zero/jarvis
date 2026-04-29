# * = only change this if you are sure about what you are doin
# These usually have other requirements than 'requirements.txt'


# Important
language = "hu"


# Wake word detection
wake_word_model = "hey_jarvis" # models: "hey_jarvis", "hey_alexa", "hey_google", etc.
wake_word_threshold = 0.35 # sensitive 0-1 non-sensitive


# Speech recording
calibration_seconds = 0.45 # The recording will listen to the environment for this long to calibrate the noise floor
no_speech_timeout = 4.0 # If no speech is detected for this long -> no speech
max_record_seconds = 15.0 # Max recording time, recording will cut after this long
min_speech_seconds = 0.35 # Speech need to be at least this long to be considered real speech
silence_after_speech = 1.0 # This much silence is needed before the speech is considered ended

start_vad_threshold = 0.52 # Noise reduction threshold. sensitive 0-1 non-sensitive, this is used to determine when speech starts
stop_vad_threshold = 0.38 # Smaller than start_vad_threshold, this is used to determine when speech ends

start_energy_multiplier = 1.65 # Multiplier for the noise_floor's volume to determine the start of speech
stop_energy_multiplier = 1.35 # Multiplier for the noise_floor's volume to determine the end of speech

speech_start_frames = 2 # Number of consecutive frames that need to be above the start threshold to consider speech started
speech_stop_frames = 10 # Number of consecutive frames that need to be below the stop threshold
prebuffer_seconds = 0.8 # This much audio will be kept in memory before the speech start to avoid cutting the beginning of the speech

# Speech To Text
stt_mode = "openai" # * "openai", "whisper" (local, free, less accurate)
stt_model = "gpt-4o-mini-transcribe" # * "openai": "gpt-4o-mini-transcribe" | "whisper": "tiny", "base", "small", "medium", "large"
stt_language = language # *


# Text To Speech
tts_mode = "edge" # * "edge", "elevenlabs", "pyttsx3", "openai" (only "edge" is tested, others may not work)
tts_model = "hu-HU-TamasNeural"# * "edge": "hu-HU-TamasNeural" | "elevenlabs": "M336tBVZHWWiWb4R54ui" (Jarvis-like) | "pyttsx3": system voices | "openai": "alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse", "marin", "cedar"
tts_pitch = "-15Hz" # Deepness of voice. deeper -20Hz-+20Hz higher
tts_rate = "+1%" # Speed of voice. slower -20%-+20% faster

# Text To Speech (ElevenLabs)
tts_stability = 0.5 # Stability of voice. 0.0 = very unstable, 1.0 = very stable
tts_similarity_boost = 0.75 # Similarity boost of voice. 0.0 = no boost, 1.0 = maximum boost
II_API_KEY = "" # Your ElevenLabs API key.


# Text To Text
ttt_mode = "openai" # * "openai", "ollama"
ttt_model = "gpt-4.1-mini" # * "openai": "gpt-4o-mini", "gpt-4.1-mini", "gpt-5-mini", "o3", "gpt-4.1", "gpt-5", "gpt-4o" (ordered by price) | "ollama": installed models
ttt_language = language # *


# Agent
max_message_history = 10 # Amount of messages the agent can remember at a time, bigger = more expensive
max_query_length = 1000 # Amount of characters a tool can return - example: how many characters can the model retrive from a website
max_steps = 7 # * How many steps and retries can a more complicated plan have

# Ducking
duck_percentage = 0.4 # Volume multiplier for other apps when Jarvis is listening and ducking is on. full mute 0.0-1.0 no ducking
ducking_default = False # If the ducking should be on by default when the program starts

# Muting
vk_mute = 0x75 # Virtual key code for mute toggle