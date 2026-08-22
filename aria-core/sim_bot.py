import asyncio
import logging
import uuid
from telegram import Update, User, Chat, Message, CallbackQuery, InlineKeyboardMarkup
import intent_parser
import main_daemon
import memory_store as memory
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

class MockMessage:
    def __init__(self, text):
        self.text = text
        self.message_id = 999
    async def reply_text(self, text, parse_mode=None, reply_markup=None):
        print(f"[Bot] reply_text: {text}")
        if reply_markup and getattr(reply_markup, "inline_keyboard", None):
            for row in reply_markup.inline_keyboard:
                for btn in row:
                    if btn.text == "✅ Approve":
                        print(f"Auto-approving callback: {btn.callback_data}")
                        await test_callback(btn.callback_data)
        return self
    async def reply_photo(self, photo, caption=None):
        pass
    async def reply_document(self, document, caption=None):
        pass

class MockBot:
    async def send_chat_action(self, chat_id, action):
        pass
    async def edit_message_text(self, text, chat_id, message_id, parse_mode=None):
        print(f"[Bot] edit_message_text: {text}")
    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        pass
    async def delete_message(self, chat_id, message_id):
        pass
    async def send_photo(self, *args, **kwargs):
        pass

class MockContext:
    def __init__(self):
        self.bot = MockBot()

class MockUpdate:
    def __init__(self, user_id, text):
        self.effective_user = User(id=user_id, first_name="Test", is_bot=False)
        self.effective_chat = Chat(id=user_id, type="private")
        self.message = MockMessage(text)

class MockCallbackQuery:
    def __init__(self, data, msg):
        self.data = data
        self.message = msg
        self.from_user = User(id=main_daemon.ALLOWED_USER_ID, first_name="Test", is_bot=False)
    async def answer(self, *args, **kwargs):
        pass
    async def edit_message_text(self, text, parse_mode=None):
        print(f"[Callback] edit_message_text: {text}")

class MockCallbackUpdate:
    def __init__(self, data):
        self.callback_query = MockCallbackQuery(data, MockMessage("foo"))
        self.effective_chat = Chat(id=main_daemon.ALLOWED_USER_ID, type="private")
        self.effective_user = User(id=main_daemon.ALLOWED_USER_ID, first_name="Test", is_bot=False)

async def test_callback(data):
    print(f"\n--- TESTING CALLBACK: {data} ---")
    update = MockCallbackUpdate(data)
    context = MockContext()
    await main_daemon.handle_callback(update, context)

async def test_cmd(cmd):
    print(f"\n--- TESTING COMMAND: {cmd} ---")
    user_id = main_daemon.ALLOWED_USER_ID
    update = MockUpdate(user_id, cmd)
    context = MockContext()
    await main_daemon.handle_message(update, context)

async def main():
    cmds = [
        "Message Doraemon on WhatsApp hi"
    ]
    for c in cmds:
        await test_cmd(c)

if __name__ == "__main__":
    asyncio.run(main())
