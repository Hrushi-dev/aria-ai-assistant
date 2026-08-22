# -*- coding: utf-8 -*-
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
import logging

# Suppress Hugging Face warnings before importing faster_whisper
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

from faster_whisper import WhisperModel
from rich.console import Console

console = Console()

# ─── SETTINGS ─────────────────────────────────────────────
SAMPLE_RATE    = 16000   # 16kHz — whisper's preferred sample rate
CHANNELS       = 1       # mono audio — one mic, one channel
RECORD_SECONDS = 5       # how long to record each time you speak
MODEL_SIZE     = "small"  # tiny / base / small / medium
                         # base = good balance of speed + accuracy for laptop mic
                         # tiny = fastest but misses words more often
                         # small = more accurate but slower

# ─── LOAD MODEL ONCE ──────────────────────────────────────
# This runs when aria_ears.py is first imported.
console.print("[dim yellow][ears]: loading whisper model...[/dim yellow]")
# Switched to CPU since CUDA 12 dlls are missing in this environment
model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
console.print("[dim green][ears]: whisper ready.[/dim green]")


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
    console.print(f"[bold red][ears]: listening for {RECORD_SECONDS} seconds...[/bold red]")

    # record audio — returns numpy array of shape (samples, channels)
    audio_data = sd.rec(
        int(RECORD_SECONDS * SAMPLE_RATE),  # total number of samples to record
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32"                      # 32-bit float — soundfile expects this
    )

    sd.wait()  # block here until recording finishes
    console.print("[dim red][ears]: done recording.[/dim red]")

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
    audio_path = None
    try:
        audio_path = record_audio()
        text = transcribe(audio_path)  # transcribe() deletes the file on success
        audio_path = None              # mark as cleaned up

        if text:
            console.print(f"[dim blue][ears]: heard → '{text}'[/dim blue]")
        else:
            console.print("[dim blue][ears]: heard nothing.[/dim blue]")

        return text

    except Exception as e:
        console.print(f"[bold yellow][ears]: error — {e}[/bold yellow]")
        return ""

    finally:
        # BUG-07 FIX: always clean up temp file if transcribe() failed before deletion
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass

# ─── TEST ─────────────────────────────────────────────────
if __name__ == "__main__":
    print(listen())