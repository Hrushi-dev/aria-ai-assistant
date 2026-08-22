# Aria — Local AI Desktop Assistant

Aria is a dual-mode AI assistant that runs fully on your PC. It supports both a **voice-driven desktop loop** and a **Telegram autonomous agent**, powered by local LLMs or Gemini cloud APIs.

---

## Modes

### 🎙️ Voice Assistant (`main.py`)
Talk to Aria through your microphone. She listens, thinks, acts on your PC, and talks back.

```
python main.py
```

Say **"switch to cloud"** or **"switch to local"** at any time to change the inference engine mid-conversation.

### 🤖 Telegram Daemon (`aria-core/main_daemon.py`)
Run Aria as a background agent accessible through Telegram. Send commands from your phone, get results on your PC.

```
launch_aria.bat       # start silently in background
stop_aria.bat         # stop the daemon
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Speech-to-Text | faster-whisper (Whisper small, CPU) |
| Text-to-Speech | Kokoro ONNX (af_bella voice, CPU) |
| Local LLM | qwen2.5:7b via Ollama (~4.5GB VRAM) |
| Cloud LLM | Gemini 2.5 Flash (google-genai) |
| Telegram Bot | python-telegram-bot v22 |
| Memory | SQLite via memory_store.py |
| PC Control | subprocess, webbrowser, ctypes, nircmd |

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Pull the local model
```bash
ollama pull qwen2.5:7b
```

### 3. Create `.env` files

**`D:\AI-AIS\.env`** (for voice assistant):
```
GEMINI_API_KEY=your_key_here
```

**`D:\AI-AIS\aria-core\.env`** (for Telegram daemon):
```
TELEGRAM_BOT_TOKEN=your_bot_token
MY_TELEGRAM_USER_ID=your_telegram_id
GEMINI_API_KEY_1=your_key_here
GEMINI_API_KEY_2=optional_second_key
```

---

## Features

- 🎙️ Voice input via Whisper STT
- 🔊 Neural TTS via Kokoro (sentence streaming)
- 🔀 Runtime switch between local and cloud LLM
- 📱 Telegram remote control with approval prompts for risky actions
- 🧠 Persistent memory via SQLite
- 🖥️ PC automation: apps, browser, volume, files, screenshots
- 🔔 Memory triggers (reminders fired on keyword match)
