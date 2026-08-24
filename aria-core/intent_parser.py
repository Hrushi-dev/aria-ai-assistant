# -*- coding: utf-8 -*-
# intent_parser.py — Aria LLM routing & JSON parsing engine

import os
import re
import json
import asyncio
import logging
import httpx
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv
import memory_store as memory

_log = logging.getLogger(__name__)

load_dotenv()

API_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2")
]
API_KEYS = [k for k in API_KEYS if k]

MODELS_POOL = [
    "gemini-3.6-flash",
]

LOCAL_MODEL = "qwen2.5:7b"


# ─── System prompt ───────────────────────────────────────────────────────────

def get_system_prompt(user_id: int = None) -> str:
    current_time_str = datetime.now().strftime("%A, %B %d, %Y at %I:%M:%S %p")
    facts   = memory.get_all_facts()
    history = memory.get_recent_history(user_id, limit=6) if user_id else "No prior history."
    facts_str = "\n".join([f"- {k}: {v}" for k, v in facts.items()]) if facts else "None."

    return f"""You are Aria, an autonomous Windows desktop AI agent. Host Time: {current_time_str}.

Known Facts:
{facts_str}

Recent Conversation:
{history}

ABSOLUTE RULES — never violate:
1. NEVER say "Please wait", "One moment", "Let me check" or similar stalling. Act immediately.
2. NEVER create files unless user says "save", "create a file", or "write to disk". For code requests put code inside chat_reply using markdown code blocks. is_chat must be true.
3. NEVER return null for chat_reply when is_chat is true. Always provide a real reply string.
4. For multi-step requests return ALL steps inside tasks[]. Never silently drop steps.
5. action must be exactly one of the allowed actions below — no other values.
6. "delete", "remove", "erase" → delete_file or delete_folder. NEVER create when asked to delete.
7. "open youtube", "play youtube" → action: "play_youtube", command: the search term only.
8. "remember", "remind me" → action: "set_memory_trigger", command: trigger phrase, summary: what to say when triggered.
9. "open [app]", "launch [app]" → action: "open_app", command: app name only (no prefix words).
10. risk_level is "HIGH" only for delete_folder, delete_file, and whatsapp_message. Everything else is "LOW".
11. When user asks if something was done ("did you do it?", "u done?") — check the conversation history above honestly.
12. "volume up/down/mute/set X%" → action: "volume_control", command: "up"|"down"|"mute"|"unmute"|"set", summary: "50" (level as string).
13. "zip/compress/archive" → action: "create_zip", source_paths: comma-separated paths, file_name: archive name.
14. "convert to pdf", "make pdf" → action: "convert_to_pdf", target_path: source file path.
15. If the user asks to send a WhatsApp message but DOES NOT provide the message body, you MUST return is_chat: true and ask what the message should say. If they DO provide the body, return action "whatsapp_message", set "command" to the contact name, and "file_content" to the message body.
16. "click at X Y" or "click on [element]" → action: "gui_click", command: "X Y" (coords as string).
17. "play", "pause", "next", "prev", "stop" alone → action: "media_control", command: the word itself.
68. "minimize", "show desktop", "minimize all" → action: "minimize_all"
69. If user specifies a location (e.g., "desktop", "downloads"), set target_path to that string EXACTLY (e.g. "desktop").
70. MULTI-TURN CONTEXT: When executing a task after asking a clarification question (e.g., user answers "which folder?"), you MUST reconstruct the entire task JSON including ALL original context (e.g., target_path, folder_name, action) from the previous turns in the new task.

ALLOWED ACTIONS:
create_file_folder | delete_folder | delete_file | close_window | open_app | minimize_all |
play_youtube | play_spotify | web_search | take_screenshot | list_files |
list_windows | set_memory_trigger | volume_control | create_zip |
convert_to_pdf | gui_click | gui_type | whatsapp_message | media_control

OUTPUT FORMAT — return ONLY valid JSON, no markdown wrapper, no extra text:

Conversational reply (greetings, questions, explanations, code snippets):
{{"is_chat": true, "chat_reply": "Your reply here. Use ```lang\\ncode\\n``` for code.", "tasks": []}}

Actions (commands, file ops, app launches, searches):
{{"is_chat": false, "chat_reply": null, "tasks": [{{"action": "allowed_action", "target_path": "string or null", "folder_name": "string or null", "file_name": "filename.ext or null", "file_content": "content or null", "command": "search term / app name / trigger phrase or null", "summary": "One-line description", "risk_level": "LOW or HIGH"}}]}}

EXAMPLES:

User: "Hi"
{{"is_chat": true, "chat_reply": "Hey! I'm Aria, your desktop assistant. What can I do for you?", "tasks": []}}

User: "open youtube"
{{"is_chat": false, "chat_reply": null, "tasks": [{{"action": "play_youtube", "target_path": null, "folder_name": null, "file_name": null, "file_content": null, "command": "", "summary": "Open YouTube homepage", "risk_level": "LOW"}}]}}

User: "play despacito on youtube"
{{"is_chat": false, "chat_reply": null, "tasks": [{{"action": "play_youtube", "target_path": null, "folder_name": null, "file_name": null, "file_content": null, "command": "despacito", "summary": "Search YouTube for despacito", "risk_level": "LOW"}}]}}

User: "play love me not by ravyn lenae on spotify"
{{"is_chat": false, "chat_reply": null, "tasks": [{{"action": "play_spotify", "target_path": null, "folder_name": null, "file_name": null, "file_content": null, "command": "love me not ravyn lenae", "summary": "Play love me not by Ravyn Lenae on Spotify", "risk_level": "LOW"}}]}}

User: "volume up"
{{"is_chat": false, "chat_reply": null, "tasks": [{{"action": "volume_control", "target_path": null, "folder_name": null, "file_name": null, "file_content": null, "command": "up", "summary": "10", "risk_level": "LOW"}}]}}

User: "set volume to 60%"
{{"is_chat": false, "chat_reply": null, "tasks": [{{"action": "volume_control", "target_path": null, "folder_name": null, "file_name": null, "file_content": null, "command": "set", "summary": "60", "risk_level": "LOW"}}]}}

User: "zip the downloads folder"
{{"is_chat": false, "chat_reply": null, "tasks": [{{"action": "create_zip", "target_path": "C:/Users/Dell/Downloads", "folder_name": null, "file_name": "downloads_backup.zip", "file_content": null, "command": null, "summary": "Compress Downloads folder into ZIP", "risk_level": "LOW"}}]}}

User: "what are the files that are on my desktop"
{{"is_chat": false, "chat_reply": null, "tasks": [{{"action": "list_files", "target_path": "desktop", "folder_name": null, "file_name": null, "file_content": null, "command": null, "summary": "List files on desktop", "risk_level": "LOW"}}]}}

User: "convert report.docx to pdf"
{{"is_chat": false, "chat_reply": null, "tasks": [{{"action": "convert_to_pdf", "target_path": "report.docx", "folder_name": null, "file_name": null, "file_content": null, "command": null, "summary": "Convert report.docx to PDF", "risk_level": "LOW"}}]}}

User: "send whatsapp to mummy"
{{"is_chat": true, "chat_reply": "Sure! What message would you like to send to Mummy?", "tasks": []}}

User: "Message Mummy on WhatsApp Hi"
{{"is_chat": false, "chat_reply": null, "tasks": [{{"action": "whatsapp_message", "target_path": null, "folder_name": null, "file_name": null, "file_content": "Hi", "command": "Mummy", "summary": "Send WhatsApp to Mummy", "risk_level": "LOW"}}]}}

User: "write me a python hello world"
{{"is_chat": true, "chat_reply": "Here you go!\\n```python\\nprint('Hello, World!')\\n```", "tasks": []}}

User: "remind me to drink water when I say thirsty"
{{"is_chat": false, "chat_reply": null, "tasks": [{{"action": "set_memory_trigger", "target_path": null, "folder_name": null, "file_name": null, "file_content": null, "command": "thirsty", "summary": "Remind user to drink water", "risk_level": "LOW"}}]}}

User: "take a screenshot"
{{"is_chat": false, "chat_reply": null, "tasks": [{{"action": "take_screenshot", "target_path": null, "folder_name": null, "file_name": null, "file_content": null, "command": null, "summary": "Capture desktop screenshot", "risk_level": "LOW"}}]}}
"""


# ─── Robust JSON sanitiser ───────────────────────────────────────────

def _sanitise_raw_json(text: str) -> str:
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]

    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace('"""', '\\"')

    result   = []
    in_str   = False
    escaped  = False
    for ch in text:
        if escaped:
            result.append(ch)
            escaped = False
            continue
        if ch == "\\":
            result.append(ch)
            escaped = True
            continue
        if ch == '"' and not escaped:
            in_str = not in_str
            result.append(ch)
            continue
        if in_str:
            if ch == "\n":
                result.append("\\n")
            elif ch == "\r":
                result.append("\\r")
            elif ch == "\t":
                result.append("\\t")
            else:
                result.append(ch)
        else:
            result.append(ch)
    text = "".join(result)

    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def clean_json_response(raw_text: str) -> dict:
    text = raw_text.strip()
    print(f"[Trace] RAW LLM OUTPUT:\n{text}\n")
    try:
        parsed = json.loads(_sanitise_raw_json(text))
        print(f"[Trace] clean_json_response: successfully parsed via json.loads: {parsed}")
        return parsed
    except json.JSONDecodeError as e:
        print(f"[Trace] clean_json_response: json.loads failed: {e}")
        pass

    # Fallback: Regex extract fields to prevent raw JSON dump
    action_m = re.search(r'"action"\s*:\s*"([^"]+)"', text)
    if action_m:
        action = action_m.group(1)
        def get_val(key):
            m = re.search(rf'"{key}"\s*:\s*(?:"((?:\\"|[^"])*)"|null|None)', text, re.DOTALL)
            return m.group(1) if m and m.group(1) else None

        target_path = get_val("target_path")
        folder_name = get_val("folder_name")
        file_name   = get_val("file_name")
        command     = get_val("command")
        
        file_content = None
        fc_m = re.search(r'"file_content"\s*:\s*"(.*?)"\s*,\s*"(?:command|summary|risk_level)"\s*:', text, re.DOTALL)
        if fc_m:
            file_content = fc_m.group(1).replace('\\"', '"').replace('\\n', '\n')
            
        return {
            "is_chat": False,
            "chat_reply": None,
            "tasks": [{
                "action": action,
                "target_path": target_path,
                "folder_name": folder_name,
                "file_name": file_name,
                "file_content": file_content,
                "command": command,
                "summary": "Recovered task via regex",
                "risk_level": "LOW" if action not in ["delete_file", "delete_folder", "whatsapp_message"] else "HIGH"
            }]
        }

    chat_match = re.search(r'"chat_reply"\s*:\s*"(.*?)"(?=\s*[,}])', text, re.DOTALL)
    if chat_match:
        try:
            reply = chat_match.group(1).replace("\\n", "\n")
            return {"is_chat": True, "chat_reply": reply, "tasks": []}
        except Exception:
            pass

    clean = re.sub(r"^\s*(```json?|```)\s*|\s*(```)\s*$", "", text, flags=re.MULTILINE).strip()
    if clean:
        print("[Trace] clean_json_response: returning fallback chat_reply from clean text")
        return {"is_chat": True, "chat_reply": clean, "tasks": []}

    print("[Trace] clean_json_response: returning absolute fallback error")
    return {"is_chat": True, "chat_reply": "⚠️ I had trouble forming a response. Please try again.", "tasks": []}


def _verify_code_block_integrity(reply: str) -> str:
    opens  = reply.count("```")
    if opens % 2 != 0:
        reply += "\n```\n⚠️ *(Response was truncated — code block closed automatically)*"
    return reply


# ─── Local Ollama query ───────────────────────────────────────────────────────

async def query_local_ollama(
    user_text: str, user_id: int = None, model_name: str = LOCAL_MODEL
) -> dict:
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model_name,
        "prompt": f"{get_system_prompt(user_id)}\n\nUser: {user_text}\nJSON:",
        "format": "json",
        "stream": False,
        "keep_alive": -1,
        "options": {
            "num_predict": 600,
            "num_ctx":     4096,   # system prompt alone is ~1000 tokens — 1536 was cutting it off
            "temperature": 0.0,
            "num_thread":  6
        }
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp   = await client.post(url, json=payload)
            result = resp.json()
            raw    = result.get("response", "{}")
            parsed = clean_json_response(raw)

            if parsed.get("is_chat") and parsed.get("chat_reply"):
                parsed["chat_reply"] = _verify_code_block_integrity(parsed["chat_reply"])

            return parsed
    except Exception as e:
        return {
            "is_chat": True,
            "chat_reply": f"⚠️ Local model error: {e}",
            "tasks": []
        }


# ─── Cloud Gemini query ───────────────────────────────────────────────────────

async def query_cloud_gemini(user_text: str, user_id: int = None, mode: str = "CLOUD") -> dict:
    prompt = get_system_prompt(user_id)
    loop   = asyncio.get_running_loop()

    keys_to_try = API_KEYS
    if mode == "API1" and os.getenv("GEMINI_API_KEY_1"):
        keys_to_try = [os.getenv("GEMINI_API_KEY_1")]
    elif mode == "API2" and os.getenv("GEMINI_API_KEY_2"):
        keys_to_try = [os.getenv("GEMINI_API_KEY_2")]

    for model_name in MODELS_POOL:
        for key in keys_to_try:
            try:
                client = genai.Client(api_key=key)
                config = types.GenerateContentConfig(
                    system_instruction=prompt,
                    response_mime_type="application/json",
                    temperature=0.1,
                    max_output_tokens=1400,
                )

                def _call_gemini():
                    return client.models.generate_content(
                        model=model_name,
                        contents=f"User: {user_text}",
                        config=config,
                    )

                response = await asyncio.wait_for(
                    loop.run_in_executor(None, _call_gemini),
                    timeout=20.0
                )

                parsed = clean_json_response(response.text)
                if parsed.get("is_chat") and parsed.get("chat_reply"):
                    parsed["chat_reply"] = _verify_code_block_integrity(parsed["chat_reply"])
                return parsed

            except asyncio.TimeoutError:
                _log.warning("[Gemini] %s / key=...%s timed out after 20s", model_name, str(key)[-6:])
                continue
            except Exception as _e:
                _log.warning("[Gemini] %s / key=...%s failed: %s", model_name, str(key)[-6:], _e)
                continue

    _log.error("[Gemini] All cloud keys/models exhausted. Falling back to local Ollama.")
    memory.set_fact("last_inference_engine", "LOCAL_FALLBACK")
    return await query_local_ollama(user_text, user_id)


async def query_openrouter(user_text: str, user_id: int = None) -> dict:
    url = "https://openrouter.ai/api/v1/chat/completions"
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return {"is_chat": True, "chat_reply": "⚠️ OpenRouter API key not configured in .env", "tasks": []}
    
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "google/gemini-2.5-pro",
        "messages": [
            {"role": "system", "content": get_system_prompt(user_id)},
            {"role": "user", "content": user_text + "\nJSON:"}
        ]
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            result = resp.json()
            raw = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            parsed = clean_json_response(raw)
            if parsed.get("is_chat") and parsed.get("chat_reply"):
                parsed["chat_reply"] = _verify_code_block_integrity(parsed["chat_reply"])
            return parsed
    except Exception as e:
        return {"is_chat": True, "chat_reply": f"⚠️ OpenRouter API error: {e}", "tasks": []}


# ─── Public entry point ───────────────────────────────────────────────────────

async def parse_user_command(user_text: str, user_id: int = None, autonomy_mode: bool = False) -> dict:
    clean = user_text.strip()
    lower = clean.lower()

    # ── Mode Switching ────────────────────────────────────────────────────
    if any(p in lower for p in ["change to local", "use local model", "switch to local", "local llm"]):
        return {"is_model_switch": True, "target_mode": "LOCAL"}
    if any(p in lower for p in ["change to cloud", "use cloud model", "switch to cloud", "cloud llm"]):
        return {"is_model_switch": True, "target_mode": "CLOUD"}
    if any(p in lower for p in ["change to api1", "switch to api1", "use api1"]):
        return {"is_model_switch": True, "target_mode": "API1"}
    if any(p in lower for p in ["change to api2", "switch to api2", "use api2"]):
        return {"is_model_switch": True, "target_mode": "API2"}
    if any(p in lower for p in ["change to openrouter", "switch to openrouter", "use openrouter", "change to open router", "switch to open router", "use open router"]):
        return {"is_model_switch": True, "target_mode": "OPENROUTER"}

    # ── Fast-Path: Common Greetings ───────────────────────────────────────
    if lower in ["hi", "hello", "hey", "yo", "sup", "wake up", "are you there", "are u there", "hi aria", "hey aria"]:
        return {"is_chat": True, "chat_reply": "Hello! I'm online and ready. What can I do for you today?", "tasks": []}

    # ── Fast-Path: Open App ───────────────────────────────────────────────
    m = re.match(r"(?:open|launch|start|run)\s+(.+)", lower)
    if m and not any(k in lower for k in ["youtube", "spotify", "folder", "file", "and", "then", "make", "create", "write", "text", "to text", "message", "send", "router", "openrouter", "api1", "api2", "local", "ollama"]) and len(m.group(1).split()) <= 3:
        return {"is_chat": False, "chat_reply": None, "tasks": [{"action": "open_app", "command": m.group(1).strip(), "target_path": None, "folder_name": None, "file_name": None, "file_content": None, "summary": f"Open {m.group(1).strip()}", "risk_level": "LOW"}]}

    # ── Fast-Path: Close App ──────────────────────────────────────────────
    m = re.match(r"(?:close|quit|exit|kill)\s+(.+)", lower)
    if m:
        return {"is_chat": False, "chat_reply": None, "tasks": [{"action": "close_window", "command": m.group(1).strip(), "target_path": None, "folder_name": None, "file_name": None, "file_content": None, "summary": f"Close {m.group(1).strip()}", "risk_level": "LOW"}]}

    # ── Fast-Path: Web Builder ────────────────────────────────────────────
    if any(k in lower for k in ["make me a webpage", "create a website", "build a webpage", "build a website", "make a website", "create a webpage", "make a web page", "create a web page"]):
        return {"is_chat": False, "chat_reply": None, "tasks": [{"action": "start_web_builder", "risk_level": "LOW", "summary": "Start adaptive web builder flow"}]}

    # ── Fast-Path: Web Search ─────────────────────────────────────────────
    m = re.match(r"(?:search(?:\s+for)?|google|look up)\s+(.+)", lower)
    if m:
        return {"is_chat": False, "chat_reply": None, "tasks": [{"action": "web_search", "command": m.group(1).strip(), "target_path": None, "folder_name": None, "file_name": None, "file_content": None, "summary": f"Search: {m.group(1).strip()}", "risk_level": "LOW"}]}

    # ── Fast-Path: YouTube ────────────────────────────────────────────────
    m = re.match(r"(?:play\s+(?:.+?)\s+on\s+youtube|open\s+youtube\s+(?:and\s+)?(?:play|search)\s+(.+)|play\s+youtube\s+(.+))", lower)
    if not m:
        m2 = re.match(r"(?:search|play)\s+(.+?)\s+on\s+youtube", lower)
        if m2:
            yt_q = m2.group(1).strip()
            return {"is_chat": False, "chat_reply": None, "tasks": [{"action": "play_youtube", "command": yt_q, "target_path": None, "folder_name": None, "file_name": None, "file_content": None, "summary": f"YouTube: {yt_q}", "risk_level": "LOW"}]}
    elif "youtube" in lower and any(k in lower for k in ["play", "search", "open", "watch"]):
        yt_q = re.sub(r"(?:play|search|open|watch|on\s+youtube|in\s+youtube|youtube)", "", lower, flags=re.IGNORECASE).strip()
        if yt_q:
            return {"is_chat": False, "chat_reply": None, "tasks": [{"action": "play_youtube", "command": yt_q, "target_path": None, "folder_name": None, "file_name": None, "file_content": None, "summary": f"YouTube: {yt_q}", "risk_level": "LOW"}]}

    # ── Fast-Path: Spotify ────────────────────────────────────────────────
    if "spotify" in lower:
        sp_q = re.sub(r"(?:play|search|open|on\s+spotify|spotify|something|music)", "", lower, flags=re.IGNORECASE).strip()
        return {"is_chat": False, "chat_reply": None, "tasks": [{"action": "play_spotify", "command": sp_q or "", "target_path": None, "folder_name": None, "file_name": None, "file_content": None, "summary": f"Spotify: {sp_q or 'open'}", "risk_level": "LOW"}]}

    # ── Fast-Path: Create Folder ──────────────────────────────────────────
    m = re.match(r"create\s+(?:a\s+)?folder\s+(?:called|named|)?\s*['\"]?([a-zA-Z0-9_\-\s]+?)['\"]?\s*(?:on\s+(?:the\s+)?(.+))?$", lower)
    if m:
        fname = m.group(1).strip()
        where = (m.group(2) or "desktop").strip()
        return {"is_chat": False, "chat_reply": None, "tasks": [{"action": "create_file_folder", "folder_name": fname, "target_path": where, "file_name": None, "file_content": None, "command": None, "summary": f"Create folder {fname}", "risk_level": "LOW"}]}

    # ── Fast-Path: Delete Folder ──────────────────────────────────────────
    m = re.match(r"delete\s+(?:the\s+)?folder\s+['\"]?([a-zA-Z0-9_\-\s]+?)['\"]?\s*(?:from\s+(?:the\s+)?(.+))?$", lower)
    if m:
        fname = m.group(1).strip()
        where = (m.group(2) or "desktop").strip()
        return {"is_chat": False, "chat_reply": None, "tasks": [{"action": "delete_folder", "folder_name": fname, "target_path": where, "file_name": None, "file_content": None, "command": None, "summary": f"Delete folder {fname}", "risk_level": "HIGH"}]}

    # ── Fast-Path: Memory Trigger ─────────────────────────────────────────
    m = re.match(r"remind\s+me\s+(?:to\s+)?(.+?)\s+when\s+(?:i\s+say\s+)?['\"]?(.+?)['\"]?$", lower)
    if m:
        payload = m.group(1).strip()
        trigger = m.group(2).strip()
        return {"is_chat": False, "chat_reply": None, "tasks": [{"action": "set_memory_trigger", "command": trigger, "summary": f"Remind: {payload}", "target_path": None, "folder_name": None, "file_name": None, "file_content": None, "risk_level": "LOW"}]}

    # ── Fast-Path: Screenshot ─────────────────────────────────────────────
    if any(k in lower for k in ["screenshot", "screen shot", "capture screen", "snapshot"]):
        return {
            "is_chat": False, "chat_reply": None,
            "tasks": [{
                "action": "take_screenshot",
                "target_path": None, "folder_name": None, "file_name": None,
                "file_content": None, "command": None,
                "summary": "Capture primary desktop screenshot",
                "risk_level": "LOW"
            }]
        }

    # ── Fast-Path: List Windows ───────────────────────────────────────────
    if any(k in lower for k in ["list windows", "what's open", "show open apps", "active windows"]):
        return {
            "is_chat": False, "chat_reply": None,
            "tasks": [{
                "action": "list_windows",
                "target_path": None, "folder_name": None, "file_name": None,
                "file_content": None, "command": None,
                "summary": "List all active windows",
                "risk_level": "LOW"
            }]
        }

    # ── Fast-Path: Media commands ─────────────────────────────────────────
    _MEDIA_WORDS = {
        "play":     "play",   "pause":    "pause",
        "next":     "next",   "previous": "previous",
        "prev":     "prev",   "stop":     "stop",
        "next song": "next",  "prev song": "previous",
        "skip":     "next",
    }
    if lower in _MEDIA_WORDS or lower.rstrip(".") in _MEDIA_WORDS:
        cmd = _MEDIA_WORDS.get(lower, _MEDIA_WORDS.get(lower.rstrip("."), "toggle"))
        return {
            "is_chat": False, "chat_reply": None,
            "tasks": [{
                "action": "media_control",
                "target_path": None, "folder_name": None, "file_name": None,
                "file_content": None, "command": cmd,
                "summary": f"Media control: {cmd}",
                "risk_level": "LOW"
            }]
        }

    # ── Fast-Path: YouTube text selection ─────────────────────────────────
    if lower == "scroll down":
        return {
            "is_chat": False, "chat_reply": None,
            "tasks": [{"action": "youtube_scroll", "summary": "Scroll browser down", "risk_level": "LOW"}]
        }
    
    yt_play_match = re.fullmatch(r"play\s+(\d+)", lower)
    if yt_play_match:
        return {
            "is_chat": False, "chat_reply": None,
            "tasks": [{"action": "youtube_click", "command": yt_play_match.group(1), "summary": f"Click video {yt_play_match.group(1)}", "risk_level": "LOW"}]
        }

    # ── Fast-Path: List files on desktop ─────────────────────────────────────
    if re.fullmatch(r"(what are the files(?: that are)? on my desktop|list my desktop|show folder contents)", lower):
        return {
            "is_chat": False, "chat_reply": None,
            "tasks": [{"action": "list_files", "target_path": "desktop", "summary": "List files on desktop", "risk_level": "LOW"}]
        }

    # ── Fast-Path: Volume shortcuts ───────────────────────────────────────
    vol_map = {
        "volume up":   ("up",     None),
        "vol up":      ("up",     None),
        "volume down": ("down",   None),
        "vol down":    ("down",   None),
        "mute":        ("mute",   None),
        "unmute":      ("unmute", None),
    }
    for phrase, (vol_cmd, vol_level) in vol_map.items():
        if phrase in lower:
            return {
                "is_chat": False, "chat_reply": None,
                "tasks": [{
                    "action": "volume_control",
                    "target_path": None, "folder_name": None, "file_name": None,
                    "file_content": None, "command": vol_cmd,
                    "summary": str(vol_level or ""),
                    "risk_level": "LOW"
                }]
            }

    vol_set = re.search(r"(?:set\s+)?volume\s+(?:to\s+)?(\d+)\s*%?", lower)
    if vol_set:
        return {
            "is_chat": False, "chat_reply": None,
            "tasks": [{
                "action": "volume_control",
                "target_path": None, "folder_name": None, "file_name": None,
                "file_content": None, "command": "set",
                "summary": vol_set.group(1),
                "risk_level": "LOW"
            }]
        }

    # ── Fast-Path: Model Diagnostics ──────────────────────────────────────
    if any(k in lower for k in [
        "which model", "what model", "current model", "active model", 
        "what llm", "which llm", "are you on local", "are you local or cloud"
    ]):
        active = (memory.get_fact("active_model_mode") or "CLOUD").upper()
        engine_desc = f"💻 Local Ollama ({LOCAL_MODEL})" if active == "LOCAL" else "☁️ Gemini Cloud API"
        return {
            "is_chat": True,
            "chat_reply": (
                f"⚡ <b>Aria Engine Status:</b>\n\n"
                f"• <b>Active Mode:</b> <code>{active}</code>\n"
                f"• <b>Engine:</b> {engine_desc}\n"
                f"• <b>Status:</b> Online &amp; Ready"
            ),
            "tasks": []
        }

    # ── LLM Routing ───────────────────────────────────────────────────────
    if autonomy_mode:
        return {"is_complex": True}
        
    active_mode = memory.get_fact("active_model_mode") or "CLOUD"
    if active_mode == "LOCAL":
        res = await query_local_ollama(clean, user_id)
    elif active_mode == "OPENROUTER":
        res = await query_openrouter(clean, user_id)
    else:
        res = await query_cloud_gemini(clean, user_id, active_mode)

    if "action" in res and "tasks" not in res:
        action_val = res.get("action")
        res["tasks"] = [{
            "action":      action_val,
            "target_path": res.get("target_path"),
            "folder_name": res.get("folder_name"),
            "file_name":   res.get("file_name"),
            "file_content":res.get("file_content"),
            "command":     res.get("command"),
            "summary":     res.get("summary", "Execute task"),
            "risk_level":  res.get("risk_level", "LOW")
        }] if action_val and action_val not in [None, "null", "none"] else []

    print(f"[Trace] parse_user_command returning: {res}")
    return res