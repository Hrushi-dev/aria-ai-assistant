import asyncio
import logging
from intent_parser import parse_user_command
import main_daemon

logging.basicConfig(level=logging.DEBUG)

async def main():
    cmds = [
        "Zip the test folder",
        "Create a .txt file on my desktop and name it test00",
        "Convert convert the hi.txt file into .docx"
    ]
    for c in cmds:
        print(f"\n--- COMMAND: {c} ---")
        intent = await parse_user_command(c, user_id=123, autonomy_mode=False)
        print(f"INTENT: {intent}")
        is_chat    = intent.get("is_chat")
        chat_reply = intent.get("chat_reply")
        tasks      = intent.get("tasks") or []
        print(f"is_chat: {is_chat}, chat_reply: {chat_reply}, tasks: {tasks}")
        if is_chat or not tasks:
            final_reply = chat_reply
            if not final_reply:
                final_reply = "I'm listening, but I didn't quite catch what you want me to do." if not is_chat else "Hey! How can I help you today?"
            print(f"FALLBACK TRIGGERED: {final_reply}")
        else:
            print("Routed to tasks execution.")

if __name__ == "__main__":
    asyncio.run(main())
