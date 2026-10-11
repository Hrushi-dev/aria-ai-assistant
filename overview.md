# Aria Project Overview

This document provides a comprehensive overview of the **Aria — Local AI Desktop Assistant** project context. It is intended to quickly onboard any AI agent resuming work on the repository, detailing the architecture, components, current state, and the latest development plans.

## 1. Project Introduction
Aria is a dual-mode AI assistant that runs fully on a local PC. It features:
1. **Voice Assistant Mode**: A desktop loop where users interact via microphone. Aria listens, thinks, takes actions on the PC, and speaks back.
2. **Telegram Daemon Mode**: A background autonomous agent reachable through Telegram, allowing users to send commands remotely and receive results (including files and screenshots) on their PC.

The project relies on local LLMs (like Qwen via Ollama) and cloud APIs (like Gemini via `google-genai`), allowing dynamic runtime switching between inference engines. 

## 2. Directory Structure & Key Components

The project is structured into distinct, decoupled modules:

### Root Level
- `README.md`: Explains features, tech stack, and setup instructions.
- `requirements.txt`: Python dependencies (includes `python-telegram-bot`, `faster-whisper`, `kokoro-onnx`, `pyautogui`, etc.).
- `start_aria.bat` & `stop_aria.bat`: Scripts to start and gracefully stop the background daemon.

### `aria-core/`
This is the heart of the Telegram daemon and background processing engine.
- **`main_daemon.py`**: The entry point for the Telegram bot daemon.
- **`plan.txt`**: **CRITICAL CONTEXT FILE**. Contains the current development roadmap, focusing on fixing GUI automation reliability using a vision verifier, integrating new LLM providers (Groq/OpenRouter), and building Antigravity IDE orchestration.
- **`antigravity_orchestrator.py`**: Handles automating the Antigravity IDE, launching projects, and managing permission prompts (Feature C in `plan.txt`).
- **`vision_gateway.py`**: The newly built shared vision-verification module to validate GUI state via cloud vision models before acting (Part 2 in `plan.txt`).
- **`obsidian_memory.py` & `memory_store.py`**: Pure-Obsidian Markdown memory engine (`D:/HERMES/AriaVault`). Replaces SQLite entirely with real-time 2-way syncing for todos, reminders, facts, notes, and conversation logs.
- **`tool_executor.py` & `intent_parser.py`**: Core logic for parsing user intents and safely executing tools.
- **`agent_runtime.py`, `router.py`, `llm_clients.py`**: The inference pipeline and routing logic supporting 4-tier model failovers.

### `aria-voice/`
The local desktop voice assistant implementation.
- **`main.py`**: The entry point for the voice-driven desktop loop.
- **`aria_ears.py`**: Handles speech-to-text using `faster-whisper`.
- **`aria_voice.py`**: Handles text-to-speech using `kokoro-onnx`.
- **`commands.py`**: Desktop specific commands and PC automation features.
- **`config.py`**: Configuration for the voice interface.

### `aria-janitor/`
A modular safety, planning, and execution framework.
- **`executor.py`, `guardian.py`, `planner.py`, `audit_logger.py`**: Components enforcing a strict principle: "never act blindly, always verify before proceeding, always give the user real control over risky/uncertain steps rather than guessing."

### `aria-sandbox/`
A designated staging environment for the assistant's runtime artifacts.
- Stores temporary screenshots (`wa_screenshot.png`, `yt_results.png`, etc.) used by `vision_gateway.py`.
- Stores ZIP files of generated projects before delivery over Telegram (e.g., handling local Bot API server's 2GB file limit).
- Contains logs like `tqueue.binlog` and `webhooks_db.binlog`.

## 3. Current Development Context (Where We Left Off)

Based on `aria-core/plan.txt`, the project recently focused on the following key objectives:

1. **GUI Automation Reliability & Vision Verification (`vision_gateway.py`)**: 
   - Historically, GUI tools acted on assumptions (fixed pixels, blind sleeps). 
   - A shared vision-verification module was built to take screenshots and use a cloud vision model (like Gemini) to verify the screen state *before* proceeding with GUI actions.
   - WhatsApp and YouTube flows were refactored to use this new verifier.

2. **Antigravity IDE Orchestration (`antigravity_orchestrator.py`)**:
   - Automating the Antigravity IDE to create projects in `D:\AI-AIS\Projects\<name>`.
   - Handling Antigravity's permission prompts dynamically by detecting them and forwarding them to the user via Telegram with options (Approve, Approve for Session, Reject).
   - Polling for completion, triggering E2E tests, and ultimately zipping the project folder via the sandbox and delivering it via Telegram.

3. **New Model Providers (`llm_clients.py`)**:
   - Integration of Groq as a fast, cheap text-reasoning tier.
   - Default coding model on OpenRouter configured (e.g., `cohere/north-mini-code`).

**Next Steps for the AI**:
If you are picking up work, consult `aria-core/plan.txt` to see which stages of the acceptance tests (Part 1, Part 2, or Part 3) are fully complete or currently failing. You will likely be debugging or finalizing the end-to-end tests for the Antigravity orchestrator or the shared vision verifier.
