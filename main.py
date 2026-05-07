# ─── main.py ──────────────────────────────────────────────
# This is the only file you run.
# It connects all modules together:
#
#   aria_ears.py  →  listens to your voice, returns text
#   assistant.py  →  sends text to Ollama, gets reply
#   commands.py   →  executes PC actions
#   config.py     →  settings and prompt
#
# Flow:
#   you speak → aria_ears hears → assistant thinks → commands act → print reply

from assistant import ask_aria, build_conversation, update_memory
from commands import execute_command
from aria_ears import listen
from aria_voice import speak

# ─── CONVERSATION MEMORY ──────────────────────────────────
# This string grows as you talk.
# It's what gives Aria short-term memory within a session.
conversation = ""

# ─── START ────────────────────────────────────────────────
print("Aria: oh, you're here. great.\n")

# ─── MAIN LOOP ────────────────────────────────────────────
while True:
    try:
        # listen to mic instead of waiting for keyboard input
        user_input = listen()
    except KeyboardInterrupt:
        print("\nAria: fine. leave. see if I care.")
        break

    # nothing heard — try again
    if not user_input:
        print("[system]: didn't catch that. try again.\n")
        continue

    # show what was heard so you can confirm it was correct
    print(f"You: {user_input}")

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

    # print and speak Aria's reply
    print(f"\nAria: {reply}\n")

    # clean reply before speaking — pyttsx3 chokes on special characters
    clean_reply = reply.replace("*", "").replace("…", "").replace("...", "").replace("😉", "").replace("—", ",")
    speak(clean_reply)