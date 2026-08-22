import asyncio
import logging
from telegram import Update, User, Chat, Message, CallbackQuery
from main_daemon import handle_callback, _send_result
import main_daemon
from unittest.mock import AsyncMock, MagicMock
import os

async def main():
    print("Testing scroll callback...")
    update = MagicMock()
    update.effective_chat.id = main_daemon.ALLOWED_USER_ID
    
    query = MagicMock()
    query.from_user.id = main_daemon.ALLOWED_USER_ID
    query.data = "yt_scroll"
    query.answer = AsyncMock()
    
    msg = MagicMock()
    msg.message_id = 999
    msg.reply_text = AsyncMock(return_value=msg)
    msg.delete = AsyncMock()
    query.message = msg
    
    update.callback_query = query
    
    context = MagicMock()
    context.bot.send_chat_action = AsyncMock()
    context.bot.send_photo = AsyncMock()
    context.bot.delete_message = AsyncMock()
    
    await handle_callback(update, context)
    
    print(f"send_photo called: {context.bot.send_photo.called}")
    if context.bot.send_photo.call_args:
        args, kwargs = context.bot.send_photo.call_args
        print(f"caption: {kwargs.get('caption')}")
    print("Done")

if __name__ == "__main__":
    asyncio.run(main())
