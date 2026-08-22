# -*- coding: utf-8 -*-
# ─── main.py ──────────────────────────────────────────────
# This is the only file you run for the VOICE assistant.
# It connects all modules together:
#
#   aria_ears.py  →  listens to your voice, returns text
#   assistant.py  →  routes to Ollama (LOCAL) or Gemini (CLOUD), gets reply
#   commands.py   →  executes PC actions
#   config.py     →  settings, model names, ALYA's prompt
#
# Switching modes — just say it out loud:
#   "switch to cloud" → Gemini API (fast, smart)
#   "switch to local" → Ollama qwen2.5:7b 

import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

from rich.console import Console
from rich.panel import Panel

from assistant import ask_aria, build_conversation, update_memory, set_mode, get_mode
from commands import execute_command
from aria_ears import listen
from aria_voice import speak_streaming

console = Console()

# ─── SWITCH PHRASES ───────────────────────────────────────
_CLOUD_PHRASES = [
    "switch to cloud", "use cloud", "cloud mode",
    "use gemini", "switch to gemini", "enable cloud"
]
_LOCAL_PHRASES = [
    "switch to local", "use local", "local mode",
    "use ollama", "switch to ollama", "enable local", "go offline"
]


def _check_mode_switch(text: str) -> bool:
    """
    Checks if the user said a mode-switch phrase.
    If so, switches the mode and speaks confirmation.
    Returns True if a switch happened (so main loop skips LLM call).
    """
    lower = text.lower()

    if any(p in lower for p in _CLOUD_PHRASES):
        set_mode("CLOUD")
        msg = "Switching to Gemini Cloud. I'll be faster now."
        console.print(Panel(
            f"[bold magenta]Aria:[/bold magenta] {msg}",
            border_style="cyan", expand=False
        ))
        speak_streaming(msg)
        return True

    if any(p in lower for p in _LOCAL_PHRASES):
        set_mode("LOCAL")
        msg = "Switching to local mode. Fully offline now."
        console.print(Panel(
            f"[bold magenta]Aria:[/bold magenta] {msg}",
            border_style="yellow", expand=False
        ))
        speak_streaming(msg)
        return True

    return False


def _mode_badge() -> str:
    mode = get_mode()
    return "[bold cyan]☁ CLOUD[/bold cyan]" if mode == "CLOUD" else "[bold yellow]⚙ LOCAL[/bold yellow]"


# ─── CONVERSATION MEMORY ──────────────────────────────────
conversation = ""

# ─── START ────────────────────────────────────────────────
console.print(f"\n[bold cyan]--- System Initializing | Mode: {_mode_badge()} ---[/bold cyan]")
console.print("[dim]Say 'switch to cloud' or 'switch to local' to change engines.[/dim]\n")

with console.status("[bold magenta]Aria is waking up...[/bold magenta]", spinner="dots"):
    conversation = build_conversation(conversation, "*User just booted you up. Greet them briefly.*")
    _, _, startup_reply = ask_aria(conversation)
    conversation = update_memory(conversation, startup_reply)

# Print transcript first, THEN start TTS — both happen simultaneously
console.print(Panel(
    f"[bold magenta]Aria:[/bold magenta] {startup_reply}",
    border_style="magenta", expand=False
))
speak_streaming(startup_reply)

# ─── MAIN LOOP ────────────────────────────────────────────
while True:
    # Show current mode in the listening prompt
    console.print(f"\n[dim]Mode: {_mode_badge()}[/dim]")

    try:
        user_input = listen()
    except KeyboardInterrupt:
        with console.status("[bold magenta]Aria is thinking...[/bold magenta]", spinner="dots"):
            exit_prompt = build_conversation(conversation, "*User is leaving abruptly. Say a brief goodbye.*")
            _, _, exit_reply = ask_aria(exit_prompt)
        console.print(Panel(
            f"[bold magenta]Aria:[/bold magenta] {exit_reply}",
            border_style="magenta", expand=False
        ))
        speak_streaming(exit_reply)
        import time; time.sleep(4)   # let TTS finish before exit
        break

    # nothing heard — try again
    if not user_input:
        console.print("[dim cyan][system]: didn't catch that. try again.[/dim cyan]")
        continue

    console.print(Panel(
        f"[bold cyan]You:[/bold cyan] {user_input}",
        border_style="cyan", expand=False
    ))

    # exit commands
    if user_input.lower() in ["exit", "quit", "bye", "stop"]:
        with console.status("[bold magenta]Aria is thinking...[/bold magenta]", spinner="dots"):
            exit_prompt = build_conversation(conversation, f"{user_input}\n*User wants to leave. Say a brief goodbye.*")
            _, _, exit_reply = ask_aria(exit_prompt)
        console.print(Panel(
            f"[bold magenta]Aria:[/bold magenta] {exit_reply}",
            border_style="magenta", expand=False
        ))
        speak_streaming(exit_reply)
        import time; time.sleep(4)   # let TTS finish before exit
        break

    # ── Mode switch check (no LLM call needed) ──────────
    if _check_mode_switch(user_input):
        continue

    # append user message to history
    conversation = build_conversation(conversation, user_input)

    # send to active engine (LOCAL or CLOUD), get back action + reply
    engine_label = "Gemini" if get_mode() == "CLOUD" else "Ollama"
    with console.status(
        f"[bold magenta]Aria is thinking... ({engine_label})[/bold magenta]",
        spinner="dots"
    ):
        action, params, reply = ask_aria(conversation)

    # execute PC command if there is one
    if action != "none":
        console.print(f"[dim green][system]: Executing {action}...[/dim green]")
    execute_command(action, params)

    # save Aria's reply into memory
    conversation = update_memory(conversation, reply)

    # Print transcript FIRST — user sees it instantly.
    # speak_streaming() queues TTS in a background thread and returns
    # immediately, so transcript + voice start at the same time.
    console.print(Panel(
        f"[bold magenta]Aria:[/bold magenta] {reply}",
        border_style="magenta", expand=False
    ))
    speak_streaming(reply)