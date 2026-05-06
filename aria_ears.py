# ─── aria_ears.py ─────────────────────────────────────────
# Aria's hearing — Speech to Text.
#
# How it works:
#   1. sounddevice records audio from your mic into a numpy array
#   2. soundfile saves that array as a temp .wav file
#   3. faster-whisper transcribes the .wav into text
#   4. the text gets returned to main.py
#
# The WhisperModel is loaded ONCE when this module is imported.
# Loading it every time you speak would be slow.

import sounddevice as sd
import soundfile as sf
import numpy as np
import tempfile
import os
from faster_whisper import WhisperModel

# ─── SETTINGS ─────────────────────────────────────────────
SAMPLE_RATE    = 16000   # 16kHz — whisper's preferred sample rate
CHANNELS       = 1       # mono audio — one mic, one channel
RECORD_SECONDS = 5       # how long to record each time you speak
MODEL_SIZE     = "base"  # tiny / base / small / medium
                         # base = good balance of speed + accuracy for laptop mic
                         # tiny = fastest but misses words more often
                         # small = more accurate but slower

# ─── LOAD MODEL ONCE ──────────────────────────────────────
# This runs when aria_ears.py is first imported.
# "cuda" means use your RTX 3050 GPU — much faster than CPU.
# compute_type="int8" means use 8-bit integers instead of 32-bit floats.
# This cuts VRAM usage roughly in half with almost no quality loss.
print("[ears]: loading whisper model...")
model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")   
print("[ears]: whisper ready.")


# ─── RECORD FROM MIC ──────────────────────────────────────
def record_audio() -> str:
    """
    Records audio from the default microphone for RECORD_SECONDS.
    Saves it to a temporary .wav file.
    Returns the path to that temp file.

    sounddevice.rec() starts recording immediately.
    sounddevice.wait() blocks until recording is done.
    The result is a 2D numpy array: shape = (samples, channels)
    """
    print(f"[ears]: listening for {RECORD_SECONDS} seconds...")

    # record audio — returns numpy array of shape (samples, channels)
    audio_data = sd.rec(
        int(RECORD_SECONDS * SAMPLE_RATE),  # total number of samples to record
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32"                      # 32-bit float — soundfile expects this
    )

    sd.wait()  # block here until recording finishes
    print("[ears]: done recording.")

    # save to a temp file so faster-whisper can read it
    # delete=False means the file stays after we close it
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, audio_data, SAMPLE_RATE)

    return tmp.name  # return path like C:\Users\...\tmpXXXX.wav


# ─── TRANSCRIBE AUDIO ─────────────────────────────────────
def transcribe(audio_path: str) -> str:
    """
    Takes a path to a .wav file.
    Runs faster-whisper on it.
    Returns the transcribed text as a string.

    model.transcribe() returns:
      - segments: an iterable of speech segments with .text
      - info: metadata like language detected, duration

    We join all segments together to get the full transcript.
    """
    segments, info = model.transcribe(audio_path, language="en")

    # segments is a generator — we iterate through it to get text chunks
    transcript = " ".join(segment.text for segment in segments).strip()

    # clean up the temp file after transcription
    os.remove(audio_path)

    return transcript


# ─── MAIN LISTEN FUNCTION ─────────────────────────────────
def listen() -> str:
    """
    The only function main.py needs to call.
    Records audio, transcribes it, returns the text.

    Returns empty string if nothing was heard or transcription failed.
    """
    try:
        audio_path = record_audio()
        text = transcribe(audio_path)

        if text:
            print(f"[ears]: heard → '{text}'")
        else:
            print("[ears]: heard nothing.")

        return text

    except Exception as e:
        print(f"[ears]: error — {e}")
        return ""

# ─── TEST ─────────────────────────────────────────────────
if __name__ == "__main__":
    print(listen())