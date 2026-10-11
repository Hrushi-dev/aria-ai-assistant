# -*- coding: utf-8 -*-
# main_daemon.py — Aria Telegram bot core

import os
import uuid
import re
import asyncio
import logging
import traceback
import sys
import subprocess
import html
from datetime import datetime
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
import json
import router
from antigravity_orchestrator import run_orchestration
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
webpage_pending: dict[int, dict] = {}

WEB_BUILDER_PROMPT = """You are Aria's Website Builder Brain.
The user wants to build a website. They will describe what they want.
Extract the following information from their description:
- description: (what the website is about, features, sections, or unknown)
- style: (color theme, tone, aesthetics, gradients, or unknown)

If they mention new details, update the existing details.
Output ONLY JSON in the following format:
{
  "description": "...",
  "style": "..."
}
"""

def determine_next_question(state):
    """Determine what to ask next based on missing info."""
    if state["description"] == "unknown":
        return "Can you explain what the website is? What should it do?"
    
    if state["style"] == "unknown":
        return "What kind of style or color gradients do you want?"
            
    return None


_MAX_TG_LEN = 4096

def _truncate(text: str, limit: int = _MAX_TG_LEN) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 40] + "\n\n⚠️ *(message truncated — too long)*"


async def _send_chat_error(context, chat_id: int, placeholder_msg_id: int | None, error: Exception, stage: str = "Execution"):
    """
    Hermes-style diagnostic alert sent directly to Telegram chat.
    Escapes all HTML entities to avoid parsing failures and provides clear diagnostics.
    """
    tb = traceback.format_exc()
    escaped_tb = html.escape(tb[-2500:] if len(tb) > 2500 else tb)
    escaped_err = html.escape(str(error))
    active_mode = memory.get_fact("active_model_mode") or "CLOUD"
    active_model = memory.get_fact("active_llm_model") or "gemini-2.5-flash"

    hint = "💡 <b>Tip:</b> Check <code>/status</code> for engine health or <code>/logs</code> for details."
    err_lower = str(error).lower()
    if "ollama" in err_lower or "connection refused" in err_lower or "11434" in err_lower:
        hint = "💡 <b>Tip:</b> Ollama is unreachable on localhost:11434. Start Ollama (`ollama serve`) or run <code>/switch cloud</code>."
    elif "quota" in err_lower or "429" in err_lower or "rate limit" in err_lower:
        hint = "💡 <b>Tip:</b> LLM quota or rate-limit hit. Run <code>/switch local</code> for Ollama or <code>/switch openrouter</code>."
    elif "not found" in err_lower or "404" in err_lower:
        hint = "💡 <b>Tip:</b> Model name not recognized. Use <code>/model gemini-2.5-flash</code> or <code>/switch local</code>."
    elif "permission" in err_lower or "access denied" in err_lower:
        hint = "💡 <b>Tip:</b> Permission denied. Run terminal as Administrator if performing privileged disk tasks."

    error_text = (
        f"🚨 <b>Aria Diagnostic Alert — {stage} Error</b>\n"
        f"<code>{'═'*32}</code>\n"
        f"⚙️ <b>Engine:</b> <code>{active_mode}</code> | <b>Model:</b> <code>{active_model}</code>\n"
        f"⚠️ <b>Error:</b> <code>{escaped_err[:300]}</code>\n\n"
        f"<b>Traceback:</b>\n<pre>{escaped_tb}</pre>\n\n"
        f"{hint}"
    )

    sent = False
    if placeholder_msg_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=placeholder_msg_id,
                text=error_text,
                parse_mode=ParseMode.HTML
            )
            sent = True
        except Exception:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=placeholder_msg_id,
                    text=f"🚨 [Error in {stage}]\n{str(error)}\n\nTraceback:\n{tb[-1500:]}\n\n{hint}"
                )
                sent = True
            except Exception:
                pass

    if not sent:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=error_text,
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🚨 [Error in {stage}]\n{str(error)}\n\nTraceback:\n{tb[-1500:]}"
            )


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
        parts      = result.split("SENDFILE:", 1)[1].split("|")
        file_path  = parts[0].strip()
        caption    = parts[1].strip() if len(parts) > 1 else "📦 File ready."
        screenshot_path = None
        for p in parts[2:]:
            if p.strip().startswith("SCREENSHOT:"):
                screenshot_path = p.strip().split("SCREENSHOT:", 1)[1].strip()
                
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
                if screenshot_path and os.path.exists(screenshot_path):
                    try:
                        with open(screenshot_path, "rb") as sf:
                            await context.bot.send_photo(chat_id=chat_id, photo=sf, caption="Here's how the site looks — let me know if this matches what you wanted.")
                    except Exception as e:
                        caption += f"\n\n(⚠️ Failed to send companion screenshot: {e})"
                        
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


async def terminate_orchestrator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
        
    try:
        import antigravity_orchestrator
        antigravity_orchestrator.stop_orchestration()
    except Exception as e:
        logging.error("Error stopping orchestrator: %s", e)

    # Force reset the active state
    memory.set_fact("ag_orchestrator_active", "False")
    memory.set_fact("waiting_for_orchestrator_feedback", None)
    memory.set_fact("ag_orchestrator_instructions", "[]")
    
    await update.message.reply_text("🛑 <b>Emergency Stop:</b> Antigravity agy process and all background tasks terminated.", parse_mode=ParseMode.HTML)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    # Trigger audio + visual sign on laptop in parallel
    diag_stats = {}
    screenshot_path = None
    try:
        import remote_alert
        diag_stats, screenshot_path = remote_alert.trigger_laptop_startup_alert()
    except Exception as e:
        logging.warning(f"[Remote Startup] Laptop alert exception: {e}")

    current_mode = memory.get_fact("active_model_mode") or "CLOUD"
    active_model = memory.get_fact("active_llm_model") or "gemini-2.5-flash"
    user_name    = memory.get_fact("user_name") or "there"

    host = diag_stats.get("hostname", "Laptop")
    battery = diag_stats.get("battery", "100%")
    power = diag_stats.get("power_plugged", "Plugged In ⚡")
    ip = diag_stats.get("ip_address", "Local")
    ram = diag_stats.get("ram_percent", "N/A")
    cpu = diag_stats.get("cpu_percent", "N/A")

    welcome_msg = (
        f"🚀 <b>ARIA FULL SYSTEM ONLINE!</b>\n"
        f"<code>{'═'*32}</code>\n"
        f"• 👤 <b>User:</b> <code>{user_name}</code>\n"
        f"• 💻 <b>Host:</b> <code>{host}</code> (Windows)\n"
        f"• 🔋 <b>Battery:</b> <code>{battery} ({power})</code>\n"
        f"• 📶 <b>IP:</b> <code>{ip}</code> | <b>RAM:</b> <code>{ram}</code> | <b>CPU:</b> <code>{cpu}</code>\n"
        f"• 🧠 <b>Engine:</b> <code>{current_mode}</code> (<code>{active_model}</code>)\n"
        f"• 📁 <b>Obsidian Vault:</b> <i>Connected & Synced</i>\n"
        f"• 🎙️ <b>Telegram Voice:</b> <i>Active (hold mic to talk)</i>\n\n"
        f"🔊 <i>Laptop Alert: Voice spoken on laptop speakers & toast shown on screen.</i>\n\n"
        f"<b>Mobile Remote Controls:</b>\n"
        f"• 🎤 <b>Voice Note</b> — hold mic and speak any task\n"
        f"• <code>/voice</code> — launch laptop desktop voice loop\n"
        f"• <code>/status</code> — live hardware & disk health\n"
        f"• <code>/clean</code> — ARIA System Janitor disk cleaner\n"
        f"• <code>/switch</code> — toggle cloud / local / openrouter\n"
        f"• <code>/ping</code> — test live connection"
    )

    await update.message.reply_text(welcome_msg, parse_mode=ParseMode.HTML)

    # Send live screen confirmation
    if screenshot_path and os.path.exists(screenshot_path):
        try:
            with open(screenshot_path, "rb") as sf:
                await context.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=sf,
                    caption=f"📸 <b>Live Laptop Screen</b> — <code>{host}</code> is awake and ready.",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logging.warning(f"[Remote Startup] Failed to send startup screenshot: {e}")

async def cmd_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    from tool_executor import launch_voice_assistant
    result = await asyncio.get_running_loop().run_in_executor(None, launch_voice_assistant)
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN)

async def cmd_stop_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    from tool_executor import stop_voice_assistant
    result = await asyncio.get_running_loop().run_in_executor(None, stop_voice_assistant)
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN)

async def set_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    args = context.args
    if not args:
        current = memory.get_fact("active_llm_model") or "gemini-2.5-flash"
        await update.message.reply_text(f"Current model: {current}\nUse /model <model_name> to change it.")
        return
    
    new_model = args[0]
    memory.set_fact("active_llm_model", new_model)
    await update.message.reply_text(f"✅ Model changed to: {new_model}")

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice notes sent from mobile on Telegram."""
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    voice = update.message.voice
    if not voice:
        return

    status_msg = await update.message.reply_text("🎧 <i>Listening to your voice note...</i>", parse_mode=ParseMode.HTML)

    try:
        # Download voice file
        file = await context.bot.get_file(voice.file_id)
        sandbox_dir = Path(__file__).parent.parent / "aria-sandbox"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        voice_path = sandbox_dir / f"tg_voice_{voice.file_unique_id}.ogg"

        await file.download_to_drive(str(voice_path))

        # Transcribe
        import voice_transcriber
        text = voice_transcriber.transcribe_audio_file(str(voice_path))

        # Cleanup voice file
        try:
            voice_path.unlink(missing_ok=True)
        except Exception:
            pass

        if not text:
            await status_msg.edit_text("🔇 Couldn't clearly detect speech in that voice note. Try speaking closer to the phone microphone.")
            return

        # Update status message with what was heard
        await status_msg.edit_text(f"🎤 <i>Heard:</i> <b>\"{html.escape(text)}\"</b>\n⏳ <i>Executing...</i>", parse_mode=ParseMode.HTML)

        # Inject transcribed text as update.message.text and process through existing handle_message
        update.message.text = text
        await handle_message(update, context)

    except Exception as e:
        logging.error(f"[Daemon] Error handling voice message: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Could not process voice note: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID or update.effective_chat.type != "private":
        return

    user_text = update.message.text.strip()
    lower_text = user_text.lower()
    
    # ── Mobile Remote Fireup / Wakeup fast path ───────────────────────────
    if lower_text in ("wake up", "wake", "start aria", "fireup", "fire up", "fire up aria", "fireup aria", "start system", "online"):
        await start(update, context)
        return
    
    # Hard-route coding tasks directly to the IDE orchestrator
    # Only triggers when there's clear coding/building intent, not casual mentions
    trigger_keywords = ["website", "build a", "make a", "code", "app", "pomodoro"]
    # Exclude phrases that look like questions, opinions, or unrelated commands
    routing_exclusions = [
        "what do you think", "what about", "do you know", "have you heard",
        "do you use", "opinion", "thoughts on", "recommend", "review",
        "open ", "close ", "launch ", "start ", "stop ", "delete ", "remove ",
        "zip ", "compress", "list ", "search ", "play ", "volume", "mute",
        "whatsapp", "send ", "screenshot", "minimize", "clean", "janitor",
        "voice", "talk to", "remember", "remind", "switch to", "change to",
        "?",  # Questions are almost never coding tasks
    ]
    has_coding_trigger = any(keyword in lower_text for keyword in trigger_keywords)
    has_exclusion = any(excl in lower_text for excl in routing_exclusions)
    if has_coding_trigger and not has_exclusion and len(user_text) < 100:
        await update.message.reply_text("🚀 Routing to Antigravity agy engine in terminal (Gemini 3.8 Flash)...")
        
        # Force state to active
        memory.set_fact("ag_orchestrator_active", "True")
        memory.set_fact("ag_orchestrator_instructions", "[]")

        
        # Fire orchestrator and exit handler so LLM doesn't do a web search
        intent = {"summary": user_text, "folder_name": "WebProject"}
        import antigravity_orchestrator
        asyncio.create_task(antigravity_orchestrator.run_orchestration(intent))
        return


    # Webpage Builder multi-turn checks
    if user_id in webpage_pending:
        state = webpage_pending[user_id]
        if state["state"] == "awaiting_confirmation":
            if "yes" in lower_text or "y" in lower_text:
                await update.message.reply_text("🚀 Great! Passing to orchestrator. This might take a minute...")
                del webpage_pending[user_id]
                intent = {
                    "summary": f"Create a {state['style']} website with the following description: {state['description']}",
                    "folder_name": "WebProject"
                }
                asyncio.create_task(run_orchestration(intent))
                return
            else:
                state["state"] = "awaiting_answers"
                state["follow_ups"] -= 1
                await update.message.reply_text("Okay, let's adjust. What needs changing?")
                return
        else:
            # Call LLM to parse
            prompt = f"{WEB_BUILDER_PROMPT}\n\nCurrent state:\n{json.dumps({k:v for k,v in state.items() if k not in ['state', 'follow_ups']})}\n\nUser input: {user_text}\n\nJSON:"
            try:
                resp = await router.generate(prompt)
                m = re.search(r'\{.*\}', resp, re.DOTALL)
                if m:
                    updates = json.loads(m.group(0))
                    state.update({k: v for k, v in updates.items() if v != "unknown"})
            except Exception as e:
                logging.error(f"Error parsing with LLM: {e}")
                
            next_q = determine_next_question(state)
            
            if not next_q or state["follow_ups"] >= 2:
                summary = f"Building a {state['style']} website based on: '{state['description']}'. Sound right?"
                state["state"] = "awaiting_confirmation"
                await update.message.reply_text(f"📝 {summary}\n\nReply 'yes' to build or tell me what to change.")
            else:
                state["follow_ups"] += 1
                await update.message.reply_text(f"🤖 {next_q}")
            return

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

    # Orchestrator feedback check
    feedback_state = memory.get_fact("waiting_for_orchestrator_feedback")
    if feedback_state:
        if lower_text in ["cancel", "no cancel", "stop", "abort"]:
            memory.set_fact(f"ag_response_{feedback_state}", "fbcan")
            memory.set_fact("waiting_for_orchestrator_feedback", None)
            await update.message.reply_text("🛑 Cancelled orchestrator feedback loop.")
            return
        else:
            memory.set_fact(f"ag_response_{feedback_state}", f"TEXT:{user_text}")
            memory.set_fact("waiting_for_orchestrator_feedback", None)
            await update.message.reply_text("✅ Feedback sent to orchestrator. It will now continue generating...")
            return

    # Orchestrator ongoing instruction forwarding
    orchestrator_active = memory.get_fact("ag_orchestrator_active")
    if orchestrator_active == "True" and not feedback_state:
        if lower_text in ["stop", "terminate", "cancel"]:
            await terminate_orchestrator(update, context)
            return
            
        queue_str = memory.get_fact("ag_orchestrator_instructions") or "[]"
        try:
            queue = json.loads(queue_str)
        except:
            queue = []
        queue.append(user_text)
        memory.set_fact("ag_orchestrator_instructions", json.dumps(queue))
        await update.message.reply_text("✅ Instruction forwarded to the active Antigravity session.")
        return

    # Memory triggers
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

        # intercept start_web_builder
        if any(t.get("action") == "start_web_builder" for t in intent.get("tasks", [])):
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=placeholder_msg.message_id)
            except Exception: pass
            
            tech_keywords = ["html", "css", "js", "react", "python", "tailwind", "node", "javascript", "typescript", "nextjs"]
            has_tech = any(kw in user_text.lower() for kw in tech_keywords)
            
            if len(user_text) >= 50 or has_tech:
                await update.message.reply_text("🚀 Detailed prompt detected. Passing directly to orchestrator...")
                orchestrator_intent = {
                    "summary": user_text,
                    "folder_name": "WebProject"
                }
                asyncio.create_task(run_orchestration(orchestrator_intent))
                return

            webpage_pending[user_id] = {
                "state": "awaiting_answers",
                "description": "unknown",
                "style": "unknown",
                "follow_ups": 0
            }
            await update.message.reply_text("🤖 Can you explain what the website is? What should it do?")
            return

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
                final_reply = "Didn't catch that, say it again?" if not is_chat else "yeah?"
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
                delay = 1.0
                if action in ["whatsapp_message", "play_spotify"]:
                    delay = 5.0
                elif action in ["open_app", "play_youtube", "web_search"]:
                    delay = 3.0
                await asyncio.sleep(delay)

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
        await _send_chat_error(
            context,
            update.effective_chat.id,
            placeholder_msg.message_id if placeholder_msg else None,
            e,
            stage="Execution Pipeline"
        )


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
                    _t.sleep(0.3)
                    
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

    if data.startswith("ag_"):
        parts = data.split("_", 3)
        if len(parts) == 4:
            action, session_id, req_id = parts[1], parts[2], parts[3]
            memory.set_fact(f"ag_response_{session_id}_{req_id}", action)
            labels = {
                "app": "✅ Approved",
                "appses": "✅ Approved for session",
                "rej": "❌ Rejected",
                "planapp": "✅ Plan Approved",
                "planrej": "❌ Plan Rejected",
                "fbapp": "✅ Final Approved",
                "fbcan": "🛑 Cancelled"
            }
            try:
                await query.edit_message_text(f"Permission {labels.get(action, action)}")
            except Exception:
                pass
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
            parts2     = result.split("SENDFILE:", 1)[1].split("|")
            file_path  = parts2[0].strip()
            caption    = parts2[1].strip() if len(parts2) > 1 else "📦 File ready."
            screenshot_path = None
            for p in parts2[2:]:
                if p.strip().startswith("SCREENSHOT:"):
                    screenshot_path = p.strip().split("SCREENSHOT:", 1)[1].strip()
                    
            try:
                file_size = os.path.getsize(file_path)
                is_local = bool(os.getenv("TELEGRAM_LOCAL_SERVER") or os.getenv("TELEGRAM_LOCAL_API_URL"))
                max_size = 2000 * 1024 * 1024 if is_local else 50 * 1024 * 1024
                if file_size > max_size:
                    await query.message.reply_text(
                        f"{caption}\n\n⚠️ File created but is too large to send via Telegram ({file_size / (1024*1024):.1f} MB).\nSaved locally at: {file_path}"
                    )
                else:
                    if screenshot_path and os.path.exists(screenshot_path):
                        try:
                            with open(screenshot_path, "rb") as sf:
                                await query.message.reply_photo(photo=sf, caption="Here's how the site looks — let me know if this matches what you wanted.")
                        except Exception as e:
                            caption += f"\n\n(⚠️ Failed to send companion screenshot: {e})"
                            
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


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a live health report of all subsystems."""
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    import os
    mode    = memory.get_fact("active_model_mode") or "CLOUD"
    model   = memory.get_fact("active_llm_model") or "gemini-2.5-flash"
    user_nm = memory.get_fact("user_name") or "(not set)"

    # Check Ollama reachability
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=3)
        ollama_status = f"✅ Online ({len(r.json().get('models', []))} model(s) loaded)"
    except Exception as e:
        ollama_status = f"❌ Offline — {type(e).__name__}"

    # Check Gemini key
    gemini_key  = os.getenv("GEMINI_API_KEY_1")
    groq_key    = os.getenv("GROQ_API_KEY")
    openr_key   = os.getenv("OPENROUTER_API_KEY")

    # Disk info
    try:
        import shutil
        c = shutil.disk_usage("C:/")
        d = shutil.disk_usage("D:/")
        disk_info = (
            f"C: {c.free // (1024**3):.0f} GB free / {c.total // (1024**3):.0f} GB\n"
            f"D: {d.free // (1024**3):.0f} GB free / {d.total // (1024**3):.0f} GB"
        )
    except Exception:
        disk_info = "(could not read)"

    orch_active = memory.get_fact("ag_orchestrator_active") or "False"

    await update.message.reply_text(
        f"<b>⚡ Aria System Status</b>\n"
        f"<code>{'─'*30}</code>\n"
        f"🧠 <b>Mode:</b> <code>{mode}</code>\n"
        f"🤖 <b>Model:</b> <code>{model}</code>\n"
        f"👤 <b>User:</b> <code>{user_nm}</code>\n"
        f"<code>{'─'*30}</code>\n"
        f"🔑 <b>Gemini Key 1:</b> {'✅ Set' if gemini_key else '❌ Missing'}\n"
        f"⚡ <b>Groq Key:</b> {'✅ Set' if groq_key else '❌ Missing'}\n"
        f"🌐 <b>OpenRouter Key:</b> {'✅ Set' if openr_key else '❌ Missing'}\n"
        f"💻 <b>Ollama:</b> {ollama_status}\n"
        f"<code>{'─'*30}</code>\n"
        f"💾 <b>Disk:</b>\n<code>{disk_info}</code>\n"
        f"🔧 <b>Orchestrator:</b> {'🟢 Active' if orch_active == 'True' else '⚫ Idle'}\n"
        f"🕐 <b>Time:</b> <code>{datetime.now().strftime('%H:%M:%S')}</code>",
        parse_mode=ParseMode.HTML
    )


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test the intent parser directly and show full trace output."""
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    args = context.args
    test_input = " ".join(args) if args else "hi"

    msg = await update.message.reply_text(
        f"🔍 <b>Debug run for:</b> <code>{test_input}</code>\n⏳ Parsing...",
        parse_mode=ParseMode.HTML
    )
    try:
        intent = await parse_user_command(test_input, user_id=update.effective_user.id)
        import json
        result_str = json.dumps(intent, indent=2, ensure_ascii=False)
        await context.bot.edit_message_text(
            f"🔍 <b>Debug:</b> <code>{test_input}</code>\n\n"
            f"<pre>{result_str[:3500]}</pre>",
            chat_id=update.effective_chat.id,
            message_id=msg.message_id,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        tb = traceback.format_exc()
        await context.bot.edit_message_text(
            f"❌ <b>Parser Error:</b>\n<pre>{tb[:3000]}</pre>",
            chat_id=update.effective_chat.id,
            message_id=msg.message_id,
            parse_mode=ParseMode.HTML
        )


async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the last 30 lines of the daemon's log file."""
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    log_path = os.path.join(os.path.dirname(__file__), "..", "aria-sandbox", "aria_daemon.log")
    log_path = os.path.abspath(log_path)
    if not os.path.exists(log_path):
        await update.message.reply_text(f"⚠️ No log file found at:\n<code>{log_path}</code>", parse_mode=ParseMode.HTML)
        return
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        tail = "".join(lines[-35:])
        await update.message.reply_text(
            f"📋 <b>Last log lines:</b>\n<pre>{tail[:3500]}</pre>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Could not read log: {e}")


async def cmd_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick engine switcher. Usage: /switch cloud|local|groq|openrouter"""
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    args = context.args
    if not args:
        current = memory.get_fact("active_model_mode") or "CLOUD"
        await update.message.reply_text(
            f"Current engine: <code>{current}</code>\n\n"
            f"Usage: <code>/switch cloud</code> | <code>/switch local</code> | "
            f"<code>/switch groq</code> | <code>/switch openrouter</code>",
            parse_mode=ParseMode.HTML
        )
        return
    mode_map = {
        "cloud": "API1", "api1": "API1", "api2": "API2",
        "local": "LOCAL", "ollama": "LOCAL",
        "groq": "GROQ", "openrouter": "OPENROUTER", "or": "OPENROUTER",
    }
    new_mode = mode_map.get(args[0].lower())
    if not new_mode:
        await update.message.reply_text(f"❌ Unknown mode: <code>{args[0]}</code>", parse_mode=ParseMode.HTML)
        return
    memory.set_fact("active_model_mode", new_mode)
    await update.message.reply_text(f"✅ Switched to: <code>{new_mode}</code>", parse_mode=ParseMode.HTML)


async def cmd_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Run ARIA System Janitor safe disk cleanup. Usage: /clean or /clean <goal>"""
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    args = context.args
    goal = " ".join(args) if args else "Clean safe temp caches, Windows update staging, and NVIDIA caches"

    msg = await update.message.reply_text(
        f"🧹 <b>ARIA Janitor Starting...</b>\n"
        f"🎯 <b>Goal:</b> <code>{html.escape(goal)}</code>\n"
        f"⏳ Analyzing disk space and computing safe cleanup plan...",
        parse_mode=ParseMode.HTML
    )

    try:
        import sys
        from pathlib import Path
        janitor_dir = (Path(__file__).parent.parent / "aria-janitor").resolve()
        if str(janitor_dir) not in sys.path:
            sys.path.insert(0, str(janitor_dir))
        import planner as _jp
        import executor as _je
        import audit_logger as _ja

        # 1. Generate plan
        plan = await _jp.generate_plan(goal)
        actions = plan.get("actions", [])
        total_est = plan.get("total_estimated_reclaim_gb", 0)

        lines = [f"📋 <b>Janitor Action Plan:</b>\n<i>{html.escape(plan.get('goal_description', ''))}</i>\n"]
        for i, a in enumerate(actions, 1):
            r = a.get("risk_level", 0)
            rec = a.get("estimated_reclaim_gb", 0)
            rec_str = f" (~{rec:.2f} GB)" if rec else ""
            lines.append(f"{i}. [Risk {r}] {html.escape(a.get('summary', ''))}{rec_str}")
        lines.append(f"\n<b>Est. Reclaim:</b> ~{total_est:.2f} GB\n⚡ <i>Executing safe actions...</i>")

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=msg.message_id,
            text="\n".join(lines)[:3500],
            parse_mode=ParseMode.HTML
        )

        # 2. Execute plan
        session = _ja.start_session(goal, dry_run=False)
        results = await asyncio.get_running_loop().run_in_executor(
            None, _je.execute_plan, plan, False, 60, True
        )
        for r in results:
            _ja.log_result(r, session_md_path=session["md_path"])
        summary_data = _ja.finish_session(session, results)

        total_reclaimed = summary_data["total_reclaimed_gb"]

        # Current disk free
        import shutil
        c = shutil.disk_usage("C:/")
        d = shutil.disk_usage("D:/")

        res_lines = [
            f"✅ <b>Janitor Maintenance Complete!</b>\n",
            f"💾 <b>Total Reclaimed:</b> <b>+{total_reclaimed:.3f} GB</b>",
            f"📊 <b>Drive Status Now:</b>",
            f"• C: {c.free // (1024**3)} GB free / {c.total // (1024**3)} GB",
            f"• D: {d.free // (1024**3)} GB free / {d.total // (1024**3)} GB\n",
            f"<b>Actions Executed:</b>"
        ]
        for r in results:
            rec = f"+{r.space_reclaimed_gb:.2f}GB" if r.space_reclaimed_gb else "—"
            res_lines.append(f"{r.status_icon} {html.escape(r.action_summary)} | {rec}")

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="\n".join(res_lines)[:3500],
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await _send_chat_error(context, update.effective_chat.id, msg.message_id, e, stage="Janitor Cleanup")


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ping — test that the bot is alive and responding."""
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    await update.message.reply_text("🏓 Pong! Aria is alive and responding.")



async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Send full error tracebacks to the Telegram chat so you can debug in-chat."""
    tb_str = "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))
    logging.error("Exception while handling an update:\n%s", tb_str)

    # Try to send to the user's chat
    try:
        if isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"🚨 <b>Unhandled Error:</b>\n<pre>{tb_str[:3500]}</pre>",
                parse_mode=ParseMode.HTML
            )
        elif ALLOWED_USER_ID:
            await context.bot.send_message(
                chat_id=ALLOWED_USER_ID,
                text=f"🚨 <b>Background Error:</b>\n<pre>{tb_str[:3500]}</pre>",
                parse_mode=ParseMode.HTML
            )
    except Exception as send_err:
        logging.error("Could not send error to Telegram: %s", send_err)


if __name__ == "__main__":
    # ── Configure file logging so errors survive between restarts ──────────────
    log_dir = os.path.join(os.path.dirname(__file__), "..", "aria-sandbox")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "aria_daemon.log")
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(file_handler)
    logging.getLogger().setLevel(logging.INFO)

    if not BOT_TOKEN:
        logging.critical("TELEGRAM_BOT_TOKEN is not set in .env — cannot start!")
        sys.exit(1)
    if not ALLOWED_USER_ID:
        logging.critical("MY_TELEGRAM_USER_ID is not set — bot will reject ALL messages!")

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
    app.add_handler(CommandHandler(["start", "wake", "fireup", "remote", "online"], start))
    app.add_handler(CommandHandler("model",     set_model))
    app.add_handler(CommandHandler(["voice", "talk"], cmd_voice))
    app.add_handler(CommandHandler(["stopvoice"], cmd_stop_voice))
    app.add_handler(CommandHandler(["stop", "terminate"], terminate_orchestrator))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("debug",     cmd_debug))
    app.add_handler(CommandHandler("logs",      cmd_logs))
    app.add_handler(CommandHandler("switch",    cmd_switch))
    app.add_handler(CommandHandler("ping",      cmd_ping))
    app.add_handler(CommandHandler(["clean", "janitor"], cmd_clean))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(error_handler)

    
    # Force-clear any hanging orchestration states on startup
    memory.set_fact("ag_orchestrator_active", "False")
    memory.set_fact("ag_orchestrator_instructions", "[]")
    memory.set_fact("waiting_for_orchestrator_feedback", None)

    # Start UDP port 9 Wake-on-LAN listener for phone WolOn signals
    try:
        import remote_alert
        remote_alert.start_wol_listener()
    except Exception as e:
        logging.warning("Could not start WoL listener: %s", e)
    
    logging.info("Aria Autonomous Agent starting... Bot token: ...%s", BOT_TOKEN[-10:])
    print("Aria Autonomous Agent running...")
    app.run_polling(drop_pending_updates=True)