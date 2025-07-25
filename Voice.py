#voice_announcement

from gtts import gTTS
import os
import threading
from playsound import playsound

VOICE_DIR = "voice_clips"
VOICE_FILE = os.path.join(VOICE_DIR, "ai_voice.mp3")

# Ensure the voice_clips folder exists
os.makedirs(VOICE_DIR, exist_ok=True)

def generate_voice_file(token_number: int, mode: str = "serve"):
    # Different announcements based on mode
    if mode=="next":
        text = f"Token number {token_number}, please come to the counter."
    elif mode == "serve":
        text = f"Now serving token number {token_number}."
    elif mode == "skip":
        text = f"Token number {token_number} has been skipped."
    elif mode == "recall":
        text = f"Token number {token_number}, please come again to the counter."
    else:
        text = f"Token number {token_number}."

    print(f"🛠 Generating AI voice: {text}")
    tts = gTTS(text)
    tts.save(VOICE_FILE)
    return VOICE_FILE

def _play_voice(file_path):
    try:
        playsound(file_path)
    except Exception as e:
        print("❌ Voice playback failed:", e)

def play_voice(token_number: int, mode: str = "serve"):
    file_path = generate_voice_file(token_number, mode)
    print(f"[Playsound] Playing generated: {file_path}")
    threading.Thread(target=_play_voice, args=(file_path,), daemon=True).start()