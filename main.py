# ─── main.py ──────────────────────────────────────────────
# This is the only file you run.
# It doesn't contain logic — it just connects the modules together:
#
#   assistant.py  →  talks to Ollama
#   commands.py   →  executes PC actions
#   config.py     →  settings and prompt
#
# Flow:
#   you type → assistant.py thinks → commands.py acts → print reply

from assistant import ask_aria, build_conversation, update_memory
from commands import execute_command

# ─── CONVERSATION MEMORY ──────────────────────────────────
# This string grows as you talk.
# It's what gives Aria short-term memory within a session.
conversation = ""

# ─── START ────────────────────────────────────────────────
print("Aria: oh, you're here. great.\n")

# ─── MAIN LOOP ────────────────────────────────────────────
while True:
    try:
        user_input = input("You: ").strip()
    except KeyboardInterrupt:
        print("\nAria: fine. leave. see if I care.")
        break

    # empty input
    if not user_input:
        print("\nAria: you typed nothing. impressive.\n")
        continue

    # exit commands
    if user_input.lower() in ["exit", "quit", "bye"]:
        print("\nAria: ...fine. leave. see if I care.\n")
        break

    # append user message to history
    conversation = build_conversation(conversation, user_input)

    # send to Ollama, get back action + reply
    action, params, reply = ask_aria(conversation)

    # execute PC command if there is one
    execute_command(action, params)

    # save Aria's reply into memory
    conversation = update_memory(conversation, reply)

    # print Aria's reply
    print(f"\nAria: {reply}\n")
