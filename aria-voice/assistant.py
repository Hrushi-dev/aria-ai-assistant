# -*- coding: utf-8 -*-
# ─── assistant.py ─────────────────────────────────────────
# Aria's brain for the Voice Assistant path.
#
# Supports TWO modes:
#   LOCAL  → sends conversation to Ollama (qwen2.5:7b) — fully offline
#   CLOUD  → sends conversation to Gemini API — faster, smarter
#
# Switch modes at runtime by saying:
#   "switch to cloud" / "use cloud" → CLOUD mode
#   "switch to local" / "use local" → LOCAL mode
#
# Both modes use ALYA's personality prompt and return the same
# (action, params, reply) tuple so the rest of the pipeline is unchanged.

import requests
import json
import re

from config import (
    OLLAMA_URL, MODEL, SYSTEM_PROMPT, ALLOWED_ACTIONS, MEMORY_LIMIT,
    GEMINI_API_KEY, GEMINI_MODEL
)

# ─── MODE STATE ───────────────────────────────────────────
# Starts in CLOUD mode (Gemini) for fast, low-latency responses.
# Say "switch to local" to go fully offline via Ollama.
_current_mode = "CLOUD"


def get_mode() -> str:
    """Returns the current inference mode: 'LOCAL' or 'CLOUD'."""
    return _current_mode


def set_mode(mode: str):
    """
    Sets the inference mode for ask_aria().
    mode must be 'LOCAL' or 'CLOUD'.
    """
    global _current_mode
    mode = mode.upper().strip()
    if mode in ("LOCAL", "CLOUD"):
        _current_mode = mode


# ─── JSON PARSER ──────────────────────────────────────────
def _parse_response(raw: str) -> tuple[str, dict, str]:
    """
    Parses the JSON returned by either Ollama or Gemini.
    Strips markdown code fences if present.
    Returns (action, params, reply).
    Falls back to ("none", {}, raw_text) on failure.
    """
    try:
        clean = re.sub(r"```json|```", "", raw).strip()
        # extract the first {...} block
        start = clean.find("{")
        end   = clean.rfind("}")
        if start != -1 and end != -1:
            clean = clean[start:end + 1]

        data   = json.loads(clean)
        action = data.get("action", "none")
        params = data.get("params", {})
        reply  = data.get("reply", "...")

        if action not in ALLOWED_ACTIONS:
            action = "none"

        return action, params, reply

    except json.JSONDecodeError:
        # salvage any text outside the JSON block
        text = re.sub(r'\{.*?\}', '', raw, flags=re.DOTALL).strip()
        return "none", {}, text or "something went sideways on my end. try again."


# ─── LOCAL: OLLAMA ────────────────────────────────────────
def _ask_local(conversation: str) -> tuple[str, dict, str]:
    """Sends conversation to local Ollama (qwen2.5:7b)."""
    try:
        response = requests.post(OLLAMA_URL, json={
            "model":  MODEL,
            "prompt": SYSTEM_PROMPT + conversation,
            "stream": False
        }, timeout=30)

        raw = response.json()["response"].strip()
        return _parse_response(raw)

    except Exception as e:
        return "none", {}, f"local model issue — {e}"


# ─── CLOUD: GEMINI ────────────────────────────────────────
def _ask_cloud(conversation: str) -> tuple[str, dict, str]:
    """Sends conversation to Gemini cloud API."""
    if not GEMINI_API_KEY:
        return "none", {}, "No GEMINI_API_KEY set. Add it to your .env file!"

    try:
        from google import genai
        from google.genai import types 

        client   = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model   = GEMINI_MODEL,
            contents= f"Conversation so far:{conversation}",
            config  = types.GenerateContentConfig(
                system_instruction   = SYSTEM_PROMPT,
                response_mime_type   = "application/json",
                temperature          = 0.3,
                max_output_tokens    = 600
            )
        )
        return _parse_response(response.text)

    except Exception as e:
        # Gemini failed — fall back to local silently
        action, params, reply = _ask_local(conversation)
        return action, params, f"[cloud failed, using local] {reply}"


# ─── PUBLIC API ───────────────────────────────────────────
def ask_aria(conversation: str) -> tuple[str, dict, str]:
    """
    Main entry point called by main.py.
    Routes to LOCAL (Ollama) or CLOUD (Gemini) based on current mode.
    Always returns (action, params, reply) — never crashes.
    """
    if _current_mode == "CLOUD":
        return _ask_cloud(conversation)
    return _ask_local(conversation)


def build_conversation(history: str, user_input: str) -> str:
    """Appends the new user message to conversation history."""
    return history + f"\nUser: {user_input}\nAria:"


def update_memory(history: str, reply: str) -> str:
    """
    Appends Aria's reply to conversation history.
    Trims to MEMORY_LIMIT characters so memory doesn't grow forever.
    """
    history += reply
    if len(history) > MEMORY_LIMIT:
        history = history[-MEMORY_LIMIT:]
        first_newline = history.find('\n')
        if first_newline != -1:
            history = history[first_newline + 1:]
    return history
