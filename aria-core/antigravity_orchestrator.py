import os
import sys
import uuid
import time
import json
import asyncio
import subprocess
import shutil
from pathlib import Path
from dotenv import load_dotenv
from telegram import Bot

import memory_store
from tool_executor import create_zip_archive

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("MY_TELEGRAM_USER_ID", "0"))
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None

_current_process: subprocess.Popen | None = None
_current_task: asyncio.Task | None = None
_stop_event = asyncio.Event()

def stop_orchestration():
    """Immediately kill running agy process, cancel background tasks, and reset state."""
    global _current_process, _current_task, _stop_event
    _stop_event.set()
    
    if _current_process:
        try:
            pid = _current_process.pid
            subprocess.run(f"taskkill /F /T /PID {pid}", shell=True, capture_output=True)
        except Exception:
            try:
                _current_process.kill()
            except Exception:
                pass
        _current_process = None

    if _current_task and not _current_task.done():
        _current_task.cancel()

    memory_store.set_fact("ag_orchestrator_active", "False")
    memory_store.set_fact("ag_orchestrator_instructions", "[]")
    memory_store.set_fact("waiting_for_orchestrator_feedback", None)

async def _send_bot_msg(text: str, parse_mode: str = "HTML"):
    if bot and ALLOWED_USER_ID:
        try:
            await bot.send_message(chat_id=ALLOWED_USER_ID, text=text, parse_mode=parse_mode)
        except Exception as e:
            print(f"[Orchestrator] Telegram send error: {e}")

async def run_orchestration(intent: dict) -> str:
    """
    Run coding task directly via `agy` CLI using Gemini 3.8 Flash model.
    Runs headlessly in terminal, creates files, packages project zip, and notifies user.
    """
    global _current_process, _current_task, _stop_event
    _stop_event.clear()
    _current_task = asyncio.current_task()
    
    memory_store.set_fact("ag_orchestrator_active", "True")
    memory_store.set_fact("ag_orchestrator_instructions", "[]")
    
    project_name = intent.get("folder_name") or intent.get("file_name") or intent.get("command", "WebProject")
    raw_prompt = intent.get("summary") or intent.get("file_content") or "Build a modern responsive website"
    
    base_dir = Path("D:/AI-AIS/Projects")
    base_dir.mkdir(parents=True, exist_ok=True)
    project_dir = base_dir / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    
    # Locate agy executable
    agy_exe = shutil.which("agy") or shutil.which("agy.exe")
    if not agy_exe:
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "agy" / "agy.exe",
            Path(os.environ.get("USERPROFILE", "")) / ".gemini" / "bin" / "agy.exe",
            Path(os.environ.get("USERPROFILE", "")) / "go" / "bin" / "agy.exe",
        ]
        for c in candidates:
            if c.exists():
                agy_exe = str(c)
                break
    if not agy_exe:
        agy_exe = "agy"

    model_name = "gemini-3.8-flash-medium"
    
    await _send_bot_msg(
        f"⚡ <b>Launching Antigravity Engine (agy CLI)...</b>\n\n"
        f"• <b>Project:</b> <code>{project_name}</code>\n"
        f"• <b>Model:</b> <code>Gemini 3.8 Flash</code>\n"
        f"• <b>Prompt:</b> {raw_prompt[:250]}\n"
        f"• <b>Directory:</b> <code>{project_dir}</code>\n\n"
        f"<i>Running headless in terminal. Send /stop anytime to cancel.</i>"
    )
    
    cmd = [
        str(agy_exe),
        "-p", raw_prompt,
        "--model", model_name,
        "--dangerously-skip-permissions",
    ]
    
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(project_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        _current_process = proc
        
        loop = asyncio.get_running_loop()
        stdout, stderr = await loop.run_in_executor(None, proc.communicate)
        
        if _stop_event.is_set():
            return "🛑 Orchestration cancelled by user."
            
        created_files = [
            f.relative_to(project_dir)
            for f in project_dir.rglob("*")
            if f.is_file() and not any(p in f.parts for p in [".git", "node_modules", ".venv", "__pycache__"])
        ]
        
        file_summary = "\n".join(f"• <code>{f}</code>" for f in created_files[:15]) if created_files else "• Task finished."
        if len(created_files) > 15:
            file_summary += f"\n• ... and {len(created_files) - 15} more files"
            
        zip_res = create_zip_archive([str(project_dir)], f"{project_name}.zip")
        
        success_msg = (
            f"✅ <b>Antigravity Task Completed!</b>\n\n"
            f"• <b>Project:</b> <code>{project_name}</code>\n"
            f"• <b>Files Created ({len(created_files)}):</b>\n{file_summary}\n\n"
            f"• <b>Path:</b> <code>{project_dir}</code>"
        )
        await _send_bot_msg(success_msg)
        
        if zip_res and zip_res.startswith("SENDFILE:"):
            zip_file_path = zip_res.split("|")[0].replace("SENDFILE:", "")
            if bot and ALLOWED_USER_ID and Path(zip_file_path).exists():
                try:
                    with open(zip_file_path, "rb") as zf:
                        await bot.send_document(
                            chat_id=ALLOWED_USER_ID,
                            document=zf,
                            filename=f"{project_name}.zip",
                            caption=f"📦 Project archive: {project_name}.zip"
                        )
                except Exception as e:
                    print(f"[Orchestrator] Failed to send zip: {e}")
                    
        return f"✅ Project built at {project_dir}:\n{stdout[:500]}"
        
    except asyncio.CancelledError:
        return "🛑 Orchestration cancelled."
    except Exception as e:
        if _stop_event.is_set():
            return "🛑 Orchestration cancelled by user."
        err_msg = f"❌ Orchestration error: {e}"
        await _send_bot_msg(err_msg)
        return err_msg
    finally:
        _current_process = None
        memory_store.set_fact("ag_orchestrator_active", "False")
        memory_store.set_fact("ag_orchestrator_instructions", "[]")
        memory_store.set_fact("waiting_for_orchestrator_feedback", None)
