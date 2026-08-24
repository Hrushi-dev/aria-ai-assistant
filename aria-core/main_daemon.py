# -*- coding: utf-8 -*-
# main_daemon.py — Aria Telegram bot core

import os
import uuid
import re
import asyncio
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from intent_parser import parse_user_command
from tool_executor import execute_tool
import memory_store as memory

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

try:
    ALLOWED_USER_ID = int(os.getenv("MY_TELEGRAM_USER_ID", "0"))
except (ValueError, TypeError):
    ALLOWED_USER_ID = 0
    logging.warning("MY_TELEGRAM_USER_ID is not set or invalid — bot will reject all users!")

pending_approvals: dict[str, dict] = {}
whatsapp_pending: dict[int, dict] = {}

_MAX_TG_LEN = 4096

def _truncate(text: str, limit: int = _MAX_TG_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 40] + "\n\n⚠️ *(message truncated — too long)*"


async def _send_result(context, chat_id: int, message_id: int, result: str):
    if isinstance(result, str) and result.startswith("SCREENSHOT:"):
        photo_path = result.split("SCREENSHOT:", 1)[1].strip()
        try:
            with open(photo_path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=f, caption="📸 Screenshot captured."
                )
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            await context.bot.edit_message_text(
                f"⚠️ Screenshot taken but could not send image: {e}",
                chat_id=chat_id, message_id=message_id
            )
    elif isinstance(result, str) and result.startswith("SENDFILE:"):
        parts      = result.split("SENDFILE:", 1)[1].split("|", 1)
        file_path  = parts[0].strip()
        caption    = parts[1].strip() if len(parts) > 1 else "📦 File ready."
        try:
            file_size = os.path.getsize(file_path)
            is_local = bool(os.getenv("TELEGRAM_LOCAL_SERVER") or os.getenv("TELEGRAM_LOCAL_API_URL"))
            max_size = 2000 * 1024 * 1024 if is_local else 50 * 1024 * 1024
            if file_size > max_size:
                msg = f"{caption}\n\n⚠️ File created but is too large to send via Telegram ({file_size / (1024*1024):.1f} MB).\nSaved locally at: {file_path}"
                await context.bot.edit_message_text(
                    msg, chat_id=chat_id, message_id=message_id
                )
            else:
                if is_local and "aria-sandbox" in file_path:
                    fname = os.path.basename(file_path)
                    container_uri = f"file:///mnt/aria-sandbox/{fname}"
                    await context.bot.send_document(
                        chat_id=chat_id, document=container_uri, caption=caption,
                        read_timeout=3600, write_timeout=3600
                    )
                else:
                    with open(file_path, "rb") as f:
                        await context.bot.send_document(
                            chat_id=chat_id, document=f, caption=caption,
                            read_timeout=3600, write_timeout=3600
                        )
                await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            await context.bot.edit_message_text(
                f"⚠️ File created but could not send: {e}\nSaved at: {file_path}",
                chat_id=chat_id, message_id=message_id
            )
    elif isinstance(result, str) and result.startswith("YTPICKER:"):
        parts      = result.split("YTPICKER:", 1)[1].split("|", 1)
        photo_path = parts[0].strip()
        query      = parts[1].strip() if len(parts) > 1 else ""
        caption    = f"▶️ <b>YouTube Results</b> for '{query}'\n\nWhich video would you like to play? (1, 2, 3...) or should I scroll down?"
        keyboard   = [
            [
                InlineKeyboardButton("1️⃣ Play 1", callback_data="yt_1"),
                InlineKeyboardButton("2️⃣ Play 2", callback_data="yt_2"),
                InlineKeyboardButton("3️⃣ Play 3", callback_data="yt_3"),
            ],
            [InlineKeyboardButton("⬇️ Scroll Down", callback_data="yt_scroll")]
        ]
        try:
            with open(photo_path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=f, caption=caption,
                    reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML
                )
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            await context.bot.edit_message_text(
                f"⚠️ YouTube search done but couldn't send image: {e}",
                chat_id=chat_id, message_id=message_id
            )
    else:
        text = _truncate(str(result))
        try:
            await context.bot.edit_message_text(
                text, chat_id=chat_id, message_id=message_id
            )
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=text)


async def _send_whatsapp_approval(update: Update, context, contact: str, body: str):
    task_id = str(uuid.uuid4())[:8]
    pending_approvals[task_id] = {
        "action":       "whatsapp_message",
        "command":      contact,
        "file_content": body,
        "summary":      f"Send WhatsApp to {contact}: \"{body[:60]}\"",
        "risk_level":   "LOW",
        "_wa_contact":  contact,
        "_wa_body":     body,
    }

    keyboard = [[
        InlineKeyboardButton("✅ Send",         callback_data=f"app_{task_id}"),
        InlineKeyboardButton("❌ Edit/Cancel",  callback_data=f"waedit_{task_id}"),
    ]]
    await update.message.reply_text(
        f"📱 <b>WhatsApp Draft</b>\n\n"
        f"• <b>To:</b> <code>{contact}</code>\n"
        f"• <b>Message:</b>\n{body}\n\n"
        f"Send this message?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


async def _send_media_player(context, chat_id: int, label: str):
    keyboard = [
        [
            InlineKeyboardButton("⏮ Prev",      callback_data="mc_prev"),
            InlineKeyboardButton("⏪ -10s",     callback_data="mc_seekb"),
            InlineKeyboardButton("⏯ Play/Pause",callback_data="mc_toggle"),
            InlineKeyboardButton("⏩ +10s",     callback_data="mc_seekf"),
            InlineKeyboardButton("⏭ Next",      callback_data="mc_next"),
        ],
        [
            InlineKeyboardButton("🔉 Vol -10%", callback_data="mc_voldown"),
            InlineKeyboardButton("🔊 Vol +10%", callback_data="mc_volup"),
            InlineKeyboardButton("🔇 Mute",       callback_data="mc_mute"),
            InlineKeyboardButton("🛑 Close",      callback_data="mc_close"),
        ]
    ]
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"{label}\n\n<i>Remote control ↓</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    current_mode = memory.get_fact("active_model_mode") or "CLOUD"
    user_name    = memory.get_fact("user_name") or "there"
    await update.message.reply_text(
        f"⚡ <b>Aria Core is Online.</b>\n"
        f"• Hello, <b>{user_name}</b>!\n"
        f"• Active Engine: <code>{current_mode}</code>\n"
        f"• Memory &amp; Sandbox: <i>Active</i>",
        parse_mode=ParseMode.HTML
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID or update.effective_chat.type != "private":
        return

    user_text = update.message.text.strip()

    # WhatsApp multi-turn checks
    if user_id in whatsapp_pending:
        wa = whatsapp_pending[user_id]
        if wa["state"] in ["awaiting_body", "awaiting_correction"]:
            if lower_text in ["cancel", "no cancel", "stop", "abort"]:
                del whatsapp_pending[user_id]
                await update.message.reply_text("🛑 WhatsApp draft cancelled.")
                return
            wa["body"] = user_text
            del whatsapp_pending[user_id]
            await _send_whatsapp_approval(update, context, wa["contact"], user_text)
            return

    # Memory triggers
    lower_text = user_text.lower()
    triggers = memory.get_triggers(user_id)
    for trig in triggers:
        if trig["trigger_phrase"] in lower_text:
            await update.message.reply_text(
                f"🔔 <b>Trigger Fired:</b> <code>{trig['trigger_phrase']}</code>\n\n{trig['payload']}",
                parse_mode=ParseMode.HTML
            )
            return

    placeholder_msg = await update.message.reply_text(
        "⏳ <i>Aria is thinking...</i>", parse_mode=ParseMode.HTML
    )
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )

    try:
        name_match = re.search(
            r"(?:my name is|i am|call me)\s+([a-zA-Z0-9_-]+)", user_text, re.IGNORECASE
        )
        if name_match:
            memory.set_fact("user_name", name_match.group(1).strip())

        autonomy_mode = (os.getenv("AUTONOMY_MODE", "0") == "1") or (memory.get_fact("autonomy_mode") == "1")
        intent = await parse_user_command(user_text, user_id=user_id, autonomy_mode=autonomy_mode)
        
        if not intent.get("is_complex") and not intent.get("is_chat") and not intent.get("tasks"):
            print("[Trace] Intent parsed with empty tasks and is_chat=False. Retrying with strict enforcement.")
            strict_prompt = user_text + "\n\nCRITICAL INSTRUCTION: You MUST return a populated 'tasks' array with a valid action. If you cannot, you MUST set 'is_chat': true and explain why."
            intent = await parse_user_command(strict_prompt, user_id=user_id, autonomy_mode=autonomy_mode)
        memory.add_message(user_id, "user", user_text)

        if intent.get("is_complex"):
            import planner
            import permission_gateway
            
            try:
                await context.bot.edit_message_text(
                    "⏳ <i>Aria is planning...</i>", chat_id=update.effective_chat.id, message_id=placeholder_msg.message_id, parse_mode=ParseMode.HTML
                )
            except Exception:
                pass
                
            try:
                plan = await planner.generate_plan(user_text)
                card = permission_gateway.format_scope_card(plan)
                keyboard = permission_gateway.build_approval_keyboard(plan["goal_id"])
                
                pending_approvals[plan["goal_id"]] = plan
                
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=card,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=placeholder_msg.message_id)
            except Exception as e:
                logging.error(f"Planner failed: {e}", exc_info=True)
                await context.bot.edit_message_text(
                    f"⚠️ <b>Planning Failed:</b> <code>{str(e)[:150]}</code>",
                    chat_id=update.effective_chat.id,
                    message_id=placeholder_msg.message_id,
                    parse_mode=ParseMode.HTML
                )
            return

        # 1. Model Switching
        if intent.get("is_model_switch"):
            new_mode = intent.get("target_mode", "CLOUD")
            memory.set_fact("active_model_mode", new_mode)
            desc = "💻 <i>All reasoning running locally via Ollama.</i>" if new_mode == "LOCAL" else "☁️ <i>All reasoning using Cloud API.</i>"
            if new_mode == "OPENROUTER":
                desc = "🌌 <i>All reasoning using OpenRouter API.</i>"
            reply = (
                f"🔄 <b>Model Mode Updated!</b>\n\n"
                f"Aria is now running on: <b>{new_mode}</b>\n"
                f"{desc}"
            )
            memory.add_message(user_id, "assistant", reply)
            await context.bot.edit_message_text(
                reply, chat_id=update.effective_chat.id,
                message_id=placeholder_msg.message_id, parse_mode=ParseMode.HTML
            )
            return

        # 2. Conversational Chat & Empty-Task Fallback
        is_chat    = intent.get("is_chat")
        chat_reply = intent.get("chat_reply")
        tasks      = intent.get("tasks") or []

        if is_chat or not tasks:
            print(f"[Trace] Entered fallback branch. is_chat={is_chat}, len(tasks)={len(tasks)}")
            final_reply = chat_reply
            if not final_reply:
                final_reply = "I'm listening, but I didn't quite catch what you want me to do." if not is_chat else "Hey! How can I help you today?"
            print(f"[Trace] final_reply resolved to: {final_reply}")

            if "whatsapp" in lower_text and ("what" in final_reply.lower() or "message" in final_reply.lower() or "?" in final_reply):
                wa_llm_match = re.search(r"to\s+([a-zA-Z0-9\s_-]+)\?", final_reply, re.IGNORECASE)
                if wa_llm_match:
                    contact = wa_llm_match.group(1).strip()
                else:
                    wa_contact_match = re.search(
                        r"(?:whatsapp|message)\s+(?:message\s+)?(?:to\s+)?([a-zA-Z0-9\s_-]+?)(?:\s+on\s+whatsapp|\s+saying|\s+hi|\s*$)",
                        user_text, re.IGNORECASE
                    )
                    contact = wa_contact_match.group(1).strip() if wa_contact_match else "unknown contact"
                whatsapp_pending[user_id] = {"contact": contact, "body": None, "state": "awaiting_body"}

            memory.add_message(user_id, "assistant", final_reply)
            try:
                await context.bot.edit_message_text(
                    _truncate(final_reply),
                    chat_id=update.effective_chat.id,
                    message_id=placeholder_msg.message_id,
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await context.bot.edit_message_text(
                    _truncate(final_reply),
                    chat_id=update.effective_chat.id,
                    message_id=placeholder_msg.message_id
                )
            return

        # 3. Task Execution
        low_risk_tasks  = [t for t in tasks if t.get("risk_level", "LOW") != "HIGH"]
        high_risk_tasks = [t for t in tasks if t.get("risk_level", "LOW") == "HIGH"]

        results = []
        for i, task in enumerate(low_risk_tasks):
            action  = task.get("action", "unknown")
            summary = task.get("summary", "Executing task")
            await context.bot.send_chat_action(
                chat_id=update.effective_chat.id, action=ChatAction.TYPING
            )
            result = await asyncio.get_running_loop().run_in_executor(
                None, execute_tool, task
            )
            memory.log_audit(user_id, action, "LOW", summary, "AUTO_EXECUTED", str(result))
            memory.add_message(user_id, "assistant", str(result))
            results.append((action, result))
            
            if len(low_risk_tasks) > 1 and i < len(low_risk_tasks) - 1:
                await asyncio.sleep(0.5)

        if results:
            combined_text = "\n\n".join(
                str(r) for _, r in results
                if not (isinstance(r, str) and (r.startswith("SCREENSHOT:") or r.startswith("SENDFILE:") or r.startswith("YTPICKER:")))
            )
            placeholder_consumed = False
            
            for action, result in results:
                if isinstance(result, str) and (result.startswith("SCREENSHOT:") or result.startswith("SENDFILE:") or result.startswith("YTPICKER:")):
                    if not placeholder_consumed:
                        await _send_result(context, update.effective_chat.id, placeholder_msg.message_id, result)
                        placeholder_consumed = True
                    else:
                        await context.bot.send_message(chat_id=update.effective_chat.id, text=str(result))
                elif action in ("play_spotify", "play_youtube"):
                    if not placeholder_consumed:
                        await _send_result(context, update.effective_chat.id, placeholder_msg.message_id, str(result))
                        placeholder_consumed = True
                    await _send_media_player(context, update.effective_chat.id, str(result))
                    return

            if combined_text:
                if not placeholder_consumed:
                    await _send_result(
                        context, update.effective_chat.id, placeholder_msg.message_id, combined_text
                    )
                else:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=_truncate(combined_text))
                    
        elif high_risk_tasks:
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=placeholder_msg.message_id
                )
            except Exception:
                pass

        for task in high_risk_tasks:
            action  = task.get("action", "unknown")
            summary = task.get("summary", "Executing task")
            target  = (
                task.get("target_path") or task.get("folder_name") or
                task.get("file_name") or task.get("command") or "Host PC"
            )
            task_id = str(uuid.uuid4())[:8]
            pending_approvals[task_id] = task

            keyboard = [[
                InlineKeyboardButton("✅ Approve", callback_data=f"app_{task_id}"),
                InlineKeyboardButton("❌ Reject",  callback_data=f"rej_{task_id}")
            ]]
            if action == "whatsapp_message":
                keyboard[0].append(InlineKeyboardButton("✏️ Edit", callback_data=f"waedit_{task_id}"))
                task["_wa_contact"] = target
            
            await update.message.reply_text(
                f"⚠️ <b>Action Pending Approval:</b>\n\n"
                f"• <b>Action:</b> <code>{action}</code>\n"
                f"• <b>Target:</b> <code>{target}</code>\n"
                f"• <b>Summary:</b> {summary}\n\n"
                f"Execute on host PC?",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logging.error("Unhandled error processing user message: %s", e, exc_info=True)
        try:
            await context.bot.edit_message_text(
                f"⚠️ <b>Execution Error:</b> <code>{str(e)[:150]}</code>",
                chat_id=update.effective_chat.id,
                message_id=placeholder_msg.message_id,
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    
    if query.data.startswith("mc_"):
        cmd_map = {
            "mc_toggle":  "toggle",   "mc_next": "next",
            "mc_prev":    "previous", "mc_volup": "up",
            "mc_voldown": "down",     "mc_mute": "mute",
            "mc_seekb":   "seekb",    "mc_seekf": "seekf",
            "mc_close":   "close",
        }
        mc_cmd = cmd_map.get(query.data)
        if mc_cmd in ("up", "down", "mute"):
            from tool_executor import control_volume
            label = await asyncio.get_running_loop().run_in_executor(
                None, control_volume, mc_cmd, None
            )
        else:
            label = await asyncio.get_running_loop().run_in_executor(
                None, execute_tool, {"action": "media_control", "command": mc_cmd}
            )
        await query.answer(str(label)[:200])
        return

    if query.data.startswith("yt_"):
        await query.answer()
        yt_cmd = query.data.split("_", 1)[1]
        
        try:
            await query.message.delete()
        except Exception:
            pass
            
        placeholder_msg = await query.message.reply_text(
            "⏳ <i>Aria is thinking...</i>", parse_mode=ParseMode.HTML
        )
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )
        
        if yt_cmd == "scroll":
            result = await asyncio.get_running_loop().run_in_executor(
                None, execute_tool, {"action": "youtube_scroll"}
            )
        else:
            def yt_click_macro(num: int):
                import pyautogui, time as _t, ctypes
                from tool_executor import youtube_picker_targets
                old_fs = pyautogui.FAILSAFE
                pyautogui.FAILSAFE = False
                try:
                    w, h = pyautogui.size()
                    def foreach_window(hwnd, lParam):
                        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buff = ctypes.create_unicode_buffer(length + 1)
                            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                            if "youtube" in buff.value.lower():
                                ctypes.windll.user32.ShowWindow(hwnd, 3)
                                ctypes.windll.user32.SetForegroundWindow(hwnd)
                                return False
                        return True
                    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
                    ctypes.windll.user32.EnumWindows(EnumWindowsProc(foreach_window), 0)
                    _t.sleep(0.5)
                    pyautogui.hotkey('ctrl', 'home')
                    _t.sleep(0.5)
                    
                    if num in youtube_picker_targets:
                        x, y = youtube_picker_targets[num]
                    else:
                        x = int(w * 0.4)
                        y = int(h * (0.35 + (num - 1) * 0.22))
                        
                    pyautogui.moveTo(x, y, duration=0.4)
                    pyautogui.click()
                    return f"▶️ Playing video #{num}."
                finally:
                    pyautogui.FAILSAFE = old_fs

            num = int(yt_cmd)
            result = await asyncio.get_running_loop().run_in_executor(
                None, yt_click_macro, num
            )
        
        await _send_result(context, update.effective_chat.id, placeholder_msg.message_id, result)
        if yt_cmd != "scroll":
            await _send_media_player(context, update.effective_chat.id, str(result))
        return

    await query.answer()
    if user_id != ALLOWED_USER_ID:
        return

    data = query.data

    if data.startswith("waedit_"):
        actual_task_id = data[len("waedit_"):]
        task = pending_approvals.pop(actual_task_id, None)
        if task:
            contact = task.get("_wa_contact", "")
            whatsapp_pending[user_id] = {
                "contact": contact, "body": None, "state": "awaiting_correction"
            }
            await query.edit_message_text(
                f"✏️ <b>Correction requested.</b>\n\nWhat should the corrected message be for <b>{contact}</b>?",
                parse_mode=ParseMode.HTML
            )
        else:
            await query.edit_message_text("⚠️ Task expired or already processed.")
        return

    if data.startswith("scope_approve:"):
        goal_id = data.split(":", 1)[1]
        plan = pending_approvals.pop(goal_id, None)
        if not plan:
            await query.edit_message_text("⚠️ Plan expired or already processed.")
            return
            
        await query.edit_message_text(f"🚀 **Approved!** Executing plan...", parse_mode=ParseMode.MARKDOWN)
        
        import agent_runtime
        asyncio.create_task(agent_runtime.execute_plan(plan, context, update.effective_chat.id, query.message.message_id))
        return

    if data.startswith("scope_reject:"):
        goal_id = data.split(":", 1)[1]
        plan = pending_approvals.pop(goal_id, None)
        memory.log_audit(user_id, "complex_plan", "HIGH", plan.get("goal_description", "plan") if plan else "unknown", "USER_REJECTED", None)
        await query.edit_message_text("🛑 **Scope Rejected.** Plan cancelled.", parse_mode=ParseMode.MARKDOWN)
        return

    parts = data.split("_", 1)
    if len(parts) != 2:
        await query.edit_message_text("⚠️ Invalid callback data.")
        return
    action_type, task_id = parts[0], parts[1]

    task = pending_approvals.get(task_id)
    if not task:
        await query.edit_message_text("⚠️ Task expired or already processed.")
        return

    action  = task.get("action", "unknown")
    risk    = task.get("risk_level", "HIGH")
    summary = task.get("summary", "Executing task")

    if action_type == "app":
        await query.edit_message_text(
            f"🚀 <b>Approved!</b> Executing <code>{summary}</code>...",
            parse_mode=ParseMode.HTML
        )
        result = await asyncio.get_running_loop().run_in_executor(
            None, execute_tool, task
        )
        memory.log_audit(user_id, action, risk, summary, "APPROVED_EXECUTED", str(result))
        memory.add_message(user_id, "assistant", str(result))

        if isinstance(result, str) and result.startswith("SCREENSHOT:"):
            photo_path = result.split("SCREENSHOT:", 1)[1].strip()
            try:
                with open(photo_path, "rb") as f:
                    await query.message.reply_photo(photo=f, caption="📸 Screenshot captured.")
            except Exception as e:
                await query.message.reply_text(f"⚠️ Could not send screenshot: {e}")
        elif isinstance(result, str) and result.startswith("SENDFILE:"):
            parts2     = result.split("SENDFILE:", 1)[1].split("|", 1)
            file_path  = parts2[0].strip()
            caption    = parts2[1].strip() if len(parts2) > 1 else "📦 File ready."
            try:
                file_size = os.path.getsize(file_path)
                is_local = bool(os.getenv("TELEGRAM_LOCAL_SERVER") or os.getenv("TELEGRAM_LOCAL_API_URL"))
                max_size = 2000 * 1024 * 1024 if is_local else 50 * 1024 * 1024
                if file_size > max_size:
                    await query.message.reply_text(
                        f"{caption}\n\n⚠️ File created but is too large to send via Telegram ({file_size / (1024*1024):.1f} MB).\nSaved locally at: {file_path}"
                    )
                else:
                    if is_local and "aria-sandbox" in file_path:
                        fname = os.path.basename(file_path)
                        container_uri = f"file:///mnt/aria-sandbox/{fname}"
                        await query.message.reply_document(document=container_uri, caption=caption, read_timeout=3600, write_timeout=3600)
                    else:
                        with open(file_path, "rb") as f:
                            await query.message.reply_document(document=f, caption=caption, read_timeout=3600, write_timeout=3600)
            except Exception as e:
                await query.message.reply_text(f"⚠️ Could not send file: {e}")
        else:
            await query.message.reply_text(_truncate(str(result)))

    else:
        memory.log_audit(user_id, action, risk, summary, "USER_REJECTED", None)
        if action == "whatsapp_message":
            contact = task.get("_wa_contact") or task.get("command", "")
            whatsapp_pending[user_id] = {
                "contact": contact, "body": None, "state": "awaiting_correction"
            }
            await query.edit_message_text(
                f"✏️ <b>Message rejected.</b>\n\nWhat should the corrected message be for <b>{contact}</b>?",
                parse_mode=ParseMode.HTML
            )
        else:
            await query.edit_message_text(
                "🛑 <b>Rejected.</b> Task cancelled.", parse_mode=ParseMode.HTML
            )

    pending_approvals.pop(task_id, None)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error(msg="Exception while handling update:", exc_info=context.error)


if __name__ == "__main__":
    builder = ApplicationBuilder().token(BOT_TOKEN)
    local_api = os.getenv("TELEGRAM_LOCAL_SERVER") or os.getenv("TELEGRAM_LOCAL_API_URL")
    if local_api:
        # Strip trailing /bot or / just in case
        clean_url = local_api.replace("/bot", "").rstrip("/")
        builder = builder.base_url(f"{clean_url}/bot").base_file_url(f"{clean_url}/file/bot").local_mode(True)
        
    app = (
        builder
        .read_timeout(60)
        .write_timeout(60)
        .connect_timeout(60)
        .pool_timeout(60)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(error_handler)
    print("Aria Autonomous Agent running...")
    app.run_polling(drop_pending_updates=True)