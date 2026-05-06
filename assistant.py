# ─── assistant.py ─────────────────────────────────────────
# This file is Aria's brain.
# Its only job: send conversation to Ollama, get back action + reply.
# It doesn't execute commands. It doesn't print anything.
# It just talks to the model and returns structured data.

import requests
import json
import re

from config import OLLAMA_URL, MODEL, SYSTEM_PROMPT, ALLOWED_ACTIONS, MEMORY_LIMIT


def ask_aria(conversation: str) -> tuple[str, dict, str]:
    """
    Sends the full conversation history to Ollama.
    Returns a tuple of (action, params, reply).

    - action : string like "youtube_open" or "none"
    - params : dict with extra info like {"query": "..."}
    - reply  : Aria's natural language response

    This function never crashes the program.
    If something goes wrong, it returns a safe fallback.
    """
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": SYSTEM_PROMPT + conversation,
            "stream": False
        })

        raw = response.json()["response"].strip()

        # model sometimes wraps output in ```json ... ``` — strip that
        clean = re.sub(r"```json|```", "", raw).strip()

        # parse the JSON Aria returned
        data = json.loads(clean)

        action = data.get("action", "none")
        params = data.get("params", {})
        reply  = data.get("reply", "...")

        # safety: reject any action not in whitelist
        if action not in ALLOWED_ACTIONS:
            action = "none"

        return action, params, reply

    except json.JSONDecodeError:
        # model returned text instead of JSON
        # try to salvage whatever reply text is in there
        try:
            reply = response.json()["response"].strip()
            reply = re.sub(r'\{.*?\}', '', reply, flags=re.DOTALL).strip()
            if not reply:
                reply = "something went sideways on my end. try again."
        except Exception:
            reply = "something went sideways on my end. try again."
        return "none", {}, reply

    except Exception as e:
        return "none", {}, f"ran into an issue — {e}"


def build_conversation(history: str, user_input: str) -> str:
    """
    Appends the new user message to conversation history.
    Returns the updated conversation string.
    """
    return history + f"\nUser: {user_input}\nAria:"


def update_memory(history: str, reply: str) -> str:
    """
    Appends Aria's reply to conversation history.
    Trims the history if it exceeds MEMORY_LIMIT characters.
    This is how Aria 'remembers' the conversation.
    """
    history += reply
    history = history[-MEMORY_LIMIT:]
    return history
