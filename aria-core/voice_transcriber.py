# -*- coding: utf-8 -*-
"""
Aria Voice Transcriber
----------------------
Handles speech-to-text for Telegram voice notes sent from mobile.
Uses faster-whisper (tiny model on CPU with int8 quantization) for near-instant transcription.
Falls back to Gemini multimodal audio if local transcription is unavailable.
"""

import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("voice_transcriber")

_whisper_model = None


def get_whisper_model():
    """Lazy-load the faster-whisper model once to keep Telegram responsive."""
    global _whisper_model
    if _whisper_model is None:
        try:
            # Suppress Hugging Face warnings
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
            logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

            from faster_whisper import WhisperModel
            logger.info("[Voice Transcriber] Loading whisper model (tiny, int8)...")
            _whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
            logger.info("[Voice Transcriber] Whisper model loaded successfully.")
        except Exception as e:
            logger.error(f"[Voice Transcriber] Failed to load WhisperModel: {e}")
            _whisper_model = False
    return _whisper_model if _whisper_model is not False else None


def transcribe_audio_file(audio_path: str) -> Optional[str]:
    """
    Transcribe an audio file (e.g. .ogg, .wav, .mp3) to text.
    First tries local faster-whisper; falls back to Gemini if needed.
    """
    path = Path(audio_path)
    if not path.exists():
        logger.error(f"[Voice Transcriber] Audio file not found: {audio_path}")
        return None

    # 1. Try local Whisper
    model = get_whisper_model()
    if model:
        try:
            segments, info = model.transcribe(str(path), beam_size=1)
            transcription = " ".join(s.text for s in segments).strip()
            if transcription:
                logger.info(f"[Voice Transcriber] Transcribed via Whisper: '{transcription}'")
                return transcription
        except Exception as e:
            logger.warning(f"[Voice Transcriber] Local Whisper transcription failed: {e}")

    # 2. Fallback to Gemini API if key is available
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gemini_key)
            with open(path, "rb") as f:
                audio_bytes = f.read()

            mime = "audio/ogg" if path.suffix.lower() in (".ogg", ".oga") else "audio/wav"
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[
                    types.Part.from_bytes(data=audio_bytes, mime_type=mime),
                    "Transcribe the spoken audio exactly as said. Return ONLY the transcribed words, nothing else.",
                ]
            )
            text = (response.text or "").strip()
            if text:
                logger.info(f"[Voice Transcriber] Transcribed via Gemini: '{text}'")
                return text
        except Exception as e:
            logger.warning(f"[Voice Transcriber] Gemini audio transcription fallback failed: {e}")

    return None
