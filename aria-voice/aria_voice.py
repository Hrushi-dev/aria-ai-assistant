# -*- coding: utf-8 -*-
# ─── aria_voice.py ───────────────────────────────────────
# Aria's voice — Text to Speech using Kokoro ONNX (CPU-only).
#
# Design decisions:
#  1. Kokoro is pinned to CPU so the GPU stays 100% free for the LLM.
#  2. speak_streaming() fires TTS sentence-by-sentence in a background
#     thread so the terminal transcript appears IMMEDIATELY while the
#     first sentence is already being synthesised.

import os
import re
import threading
import queue
import numpy as np
import sounddevice as sd

# Force ONNX to CPU before importing kokoro
os.environ["ONNXRUNTIME_EXECUTION_PROVIDER"] = "CPUExecutionProvider"

from kokoro_onnx import Kokoro
from rich.console import Console

console = Console()


# ─── SETTINGS ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
MODEL_PATH  = os.path.join(BASE_DIR, "kokoro-v0_19.fp16.onnx")
VOICES_PATH = os.path.join(BASE_DIR, "voices.bin")
VOICE       = "af_bella"   # calm, natural female voice
SPEED       = 1.05         # slightly faster than default — feels snappier
SAMPLE_RATE = 24000        # Kokoro outputs at 24 kHz

# ─── LOAD MODEL ONCE ──────────────────────────────────────
# Loaded once at import time — not on every speak() call.
console.print("[dim yellow][voice]: loading Kokoro TTS on CPU...[/dim yellow]")
try:
    tts = Kokoro(MODEL_PATH, VOICES_PATH)
    console.print("[dim green][voice]: Kokoro ready (CPU).[/dim green]")
except Exception as _e:
    console.print(f"[bold red][voice]: Kokoro failed to load — {_e}[/bold red]")
    tts = None


# ─── SENTENCE SPLITTER ────────────────────────────────────
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')

def _split_sentences(text: str) -> list[str]:
    """Splits text on sentence boundaries, strips blanks."""
    parts = _SENTENCE_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


# ─── CORE SYNTHESISE + PLAY ───────────────────────────────
def _synth_and_play(sentence: str):
    """Synthesises one sentence and blocks until playback is done."""
    if not tts:
        return
    try:
        samples, sr = tts.create(sentence, voice=VOICE, speed=SPEED, lang="en-us")
        sd.play(samples, samplerate=sr)
        sd.wait()
    except Exception as e:
        console.print(f"[bold yellow][voice]: error — {e}[/bold yellow]")


# ─── PUBLIC: SIMPLE SPEAK ─────────────────────────────────
def speak(text: str):
    """
    Blocking speak — synthesises the full text then plays it.
    Use speak_streaming() for best latency.
    """
    if not text or not text.strip():
        return
    _synth_and_play(text.strip())


# ─── PUBLIC: STREAMING SPEAK ──────────────────────────────
def speak_streaming(text: str):
    """
    Non-blocking sentence-streaming TTS.

    How it works:
      - The caller (main.py) already printed the transcript to the console.
      - This function queues every sentence and plays them sequentially
        in a background daemon thread.
      - Returns IMMEDIATELY so the main loop can start listening again
        while the voice is still playing.

    The background thread is a simple producer-consumer:
      sentences → queue → synth+play loop
    """
    if not text or not text.strip():
        return

    sentences = _split_sentences(text)
    if not sentences:
        return

    # Each call gets its own queue; the background thread drains it.
    q: queue.Queue = queue.Queue()
    for s in sentences:
        q.put(s)
    q.put(None)   # sentinel — signals end

    def _worker():
        while True:
            item = q.get()
            if item is None:
                break
            _synth_and_play(item)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    # We return immediately; the thread plays in the background.
    # If you want to BLOCK until audio finishes, call t.join() here.
    # For voice-assistant UX (listen while speaking) — don't join.


# ─── TEST ─────────────────────────────────────────────────
if __name__ == "__main__":
    import time
    test = "Hello. This is Aria speaking. CPU-only Kokoro is working correctly."
    console.print(f"[bold magenta]Aria:[/bold magenta] {test}")
    speak_streaming(test)
    time.sleep(6)   # keep script alive long enough to hear it