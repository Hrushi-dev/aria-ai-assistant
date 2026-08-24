import os
import sys
import uuid
import time
import json
import asyncio
import subprocess
import threading
from pathlib import Path

import pyautogui
from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

import memory_store
from router import generate
from tool_executor import take_desktop_screenshot, gui_click, create_zip_archive
from vision_gateway import verify_screen_state

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("MY_TELEGRAM_USER_ID", "0"))
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None

async def _vision_trigger_approval():
    shot_res = take_desktop_screenshot()
    if not shot_res.startswith("SCREENSHOT:"): return
    shot_path = shot_res.replace("SCREENSHOT:", "")
    
    state = await verify_screen_state(shot_path, "Find the button to approve, allow, or say Yes to the permission prompt.")
    if state.get("approved") and state.get("coordinates"):
        coords = state.get("coordinates")
        gui_click(coords[0], coords[1])
    else:
        pyautogui.press('enter')

async def _type_in_chat(text: str):
    pyautogui.hotkey('ctrl', 'l')
    await asyncio.sleep(0.5)
    pyautogui.typewrite(text, interval=0.03)
    await asyncio.sleep(0.5)
    
    shot_res = take_desktop_screenshot()
    if shot_res.startswith("SCREENSHOT:"):
        shot_path = shot_res.replace("SCREENSHOT:", "")
        verify = await verify_screen_state(shot_path, f"The chat input box contains the exact text '{text}'")
        if not verify.get("approved"):
            pass
            
    pyautogui.press('enter')

async def _trigger_e2e_test():
    await _type_in_chat("Run an E2E test pass")
    
    for _ in range(60):
        await asyncio.sleep(10)
        shot_res = take_desktop_screenshot()
        if not shot_res.startswith("SCREENSHOT:"): continue
        shot_path = shot_res.replace("SCREENSHOT:", "")
        comp_check = await verify_screen_state(
            shot_path,
            "The AI assistant has completed the E2E test task and is waiting for the next user input. No spinners or active generation indicators are visible."
        )
        if comp_check.get("approved"):
            break

async def _validate_and_screenshot_website(project_dir: Path) -> str | None:
    import socket, re, shutil
    server_proc = None
    url = None
    try:
        pkg_json = project_dir / "package.json"
        index_html = project_dir / "index.html"
        
        if pkg_json.exists():
            print("Website Validation: Found package.json, running npm install...")
            npm_exe = shutil.which("npm") or "npm.cmd"
            try:
                subprocess.run([npm_exe, "install"], cwd=str(project_dir), timeout=90, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                print("Website Validation: npm install timed out.")
                return None
            print("Website Validation: Running npm run dev...")
            server_proc = subprocess.Popen([npm_exe, "run", "dev"], cwd=str(project_dir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            start_time = time.time()
            while time.time() - start_time < 15:
                line = server_proc.stdout.readline()
                if not line and server_proc.poll() is not None: break
                match = re.search(r"http://localhost:(\d+)", line) or re.search(r"http://127\.0\.0\.1:(\d+)", line)
                if match:
                    url = f"http://localhost:{match.group(1)}"
                    break
            if not url: url = "http://localhost:3000"
        elif index_html.exists():
            print("Website Validation: Found index.html, starting python server...")
            sock = socket.socket()
            sock.bind(('', 0))
            port = sock.getsockname()[1]
            sock.close()
            server_proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port)], cwd=str(project_dir), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            url = f"http://localhost:{port}"
            
        if url:
            print(f"Website Validation: Opening {url}")
            import pyautogui
            pyautogui.hotkey('win', 'd')
            import time
            time.sleep(1.0)
            os.startfile(url)
            for _ in range(12):
                await asyncio.sleep(5)
                shot_res = take_desktop_screenshot()
                if not shot_res.startswith("SCREENSHOT:"): continue
                shot_path = shot_res.replace("SCREENSHOT:", "")
                state = await verify_screen_state(shot_path, "The browser is showing a successfully rendered webpage. It is NOT showing a 'This site can't be reached' error, a 'Connection refused' error, or a completely blank white page.")
                if state.get("approved"):
                    return shot_path
            return None
    except Exception as e:
        print(f"Website Validation Error: {e}")
        return None
    finally:
        if server_proc:
            try: server_proc.terminate()
            except: pass

async def send_permission_prompt(shot_path: str, session_id: str, prompt_text: str = "Permission required by Antigravity.") -> str:
    req_id = str(uuid.uuid4())[:8]
    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"ag_app_{session_id}_{req_id}")],
        [InlineKeyboardButton("✅ Approve for session", callback_data=f"ag_appses_{session_id}_{req_id}")],
        [InlineKeyboardButton("❌ Reject", callback_data=f"ag_rej_{session_id}_{req_id}")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    if bot and ALLOWED_USER_ID:
        try:
            with open(shot_path, "rb") as f:
                await bot.send_photo(chat_id=ALLOWED_USER_ID, photo=f, caption=f"⚠️ {prompt_text}", reply_markup=markup)
        except Exception as e: return "reject"
    for _ in range(300):
        resp = memory_store.get_fact(f"ag_response_{session_id}_{req_id}")
        if resp: return resp
        await asyncio.sleep(1)
    return "reject"

async def _monitor_files(project_dir: Path, stop_event: threading.Event):
    seen = set()
    while not stop_event.is_set():
        if project_dir.exists():
            current = {f.name for f in project_dir.rglob('*') if f.is_file() and not '.git' in f.parts and not 'node_modules' in f.parts}
            new_files = current - seen
            if new_files:
                seen.update(new_files)
                if bot and ALLOWED_USER_ID:
                    try:
                        file_list = ", ".join(list(new_files)[:10])
                        if len(new_files) > 10: file_list += "..."
                        await bot.send_message(chat_id=ALLOWED_USER_ID, text=f"📄 Antigravity created: {file_list}")
                    except: pass
        await asyncio.sleep(10)

async def _generate_final_report(project_dir: Path) -> str:
    all_files_text = []
    for f in project_dir.rglob('*'):
        if f.is_file() and not '.git' in f.parts and not 'node_modules' in f.parts:
            try:
                content = f.read_text(encoding='utf-8')
                all_files_text.append(f"--- {f.name} ---\n{content[:1000]}")
            except: pass
    
    prompt = "Generate a comprehensive markdown report for the project and its features based on these files:\n\n" + "\n".join(all_files_text)
    try:
        res = generate([{"role": "user", "content": prompt}])
        report_text = res.get("text", "Report generation failed.")
    except Exception as e:
        report_text = f"Report generation failed: {e}"
        
    report_path = project_dir / "final_report.md"
    report_path.write_text(report_text, encoding='utf-8')
    return report_text

async def run_orchestration(intent: dict) -> str:
    project_name = intent.get("folder_name") or intent.get("file_name") or intent.get("command", "AgProject")
    raw_prompt = intent.get("summary") or intent.get("file_content") or "Build a simple hello world app"
    
    # Nike Imagery + Plan Pause instructions
    nike_prompt = (
        raw_prompt + "\n\n"
        "IMPORTANT INSTRUCTIONS:\n"
        "1. Generate an implementation_plan.md file detailing the plan.\n"
        "2. Once the plan is generated, STOP and wait for my explicit approval before writing any other code.\n"
        "3. You must search the internet for real luxury Nike product photography and use them in the website instead of generic placeholders."
    )
    
    base_dir = Path("D:/AI-AIS/Projects")
    base_dir.mkdir(parents=True, exist_ok=True)
    project_dir = base_dir / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    
    session_id = str(uuid.uuid4())[:8]
    session_approved = False
    
    import shutil
    ag_exe = shutil.which("antigravity") or "antigravity.cmd"
    if not ag_exe: return "⚠️ Antigravity CLI not found."
    
    # 1. Visual GUI Launch
    print("Launching Antigravity GUI...")
    pyautogui.hotkey('win', 'd') # Minimize all to keep focus isolated
    time.sleep(1)
    proc = subprocess.Popen(f'"{ag_exe}" .', cwd=str(project_dir), shell=True)
    
    # Start File Monitor
    stop_event = threading.Event()
    file_monitor = asyncio.create_task(_monitor_files(project_dir, stop_event))
    
    await asyncio.sleep(5) # Wait for IDE
    
    # 2. Type Prompt Visually
    pyautogui.hotkey('ctrl', 'l')
    await asyncio.sleep(1)
    pyautogui.typewrite(nike_prompt, interval=0.03)
    pyautogui.press('enter')
    
    # 3. Wait for Plan (Timeout 4 mins)
    plan_text = None
    start_wait = time.time()
    while time.time() - start_wait < 240:
        plan_path = project_dir / "implementation_plan.md"
        if plan_path.exists():
            await asyncio.sleep(2) # let it finish writing
            try:
                plan_text = plan_path.read_text(encoding='utf-8')
                break
            except: pass
        await asyncio.sleep(5)
        
    # Plan Approval Gate
    if plan_text:
        shot_res = take_desktop_screenshot()
        shot_path = shot_res.replace("SCREENSHOT:", "") if shot_res.startswith("SCREENSHOT:") else None
        
        req_id = str(uuid.uuid4())[:8]
        memory_store.set_fact(f"ag_response_{session_id}_{req_id}", "None")
        kb = [
            [InlineKeyboardButton("✅ Approve Plan & Continue", callback_data=f"ag_planapp_{session_id}_{req_id}")],
            [InlineKeyboardButton("❌ Reject Plan", callback_data=f"ag_planrej_{session_id}_{req_id}")]
        ]
        if bot and ALLOWED_USER_ID:
            msg_text = f"📝 **Plan Generated**\n\n{plan_text[:3500]}"
            if shot_path:
                with open(shot_path, "rb") as f:
                    await bot.send_photo(chat_id=ALLOWED_USER_ID, photo=f, caption=msg_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
            else:
                await bot.send_message(chat_id=ALLOWED_USER_ID, text=msg_text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
                
        # Wait for approval
        approved = False
        for _ in range(600): # 10 min
            resp = memory_store.get_fact(f"ag_response_{session_id}_{req_id}")
            if resp == "planapp":
                approved = True
                break
            elif resp == "planrej":
                stop_event.set()
                return "🛑 Orchestration cancelled by user during plan review."
            await asyncio.sleep(1)
            
        if approved:
            await _type_in_chat("Approve")
    else:
        if bot and ALLOWED_USER_ID:
            await bot.send_message(chat_id=ALLOWED_USER_ID, text="⚠️ No separate plan file was found within 4 minutes. Coding is continuing based on the submitted prompt.")
            
    # 4. Wait for coding to finish
    completed = False
    for i in range(240): # 20 minutes max (240 * 5s)
        await asyncio.sleep(5)
        shot_res = take_desktop_screenshot()
        if not shot_res.startswith("SCREENSHOT:"): continue
        shot_path = shot_res.replace("SCREENSHOT:", "")
        
        # Send progress screenshot every 1 minute (12 * 5s = 60s)
        if i > 0 and i % 12 == 0 and bot and ALLOWED_USER_ID:
            try:
                with open(shot_path, "rb") as f:
                    await bot.send_photo(chat_id=ALLOWED_USER_ID, photo=f, caption="⏳ **Coding Progress Update:** Aria is still working on your project.")
            except: pass
            
        comp_check = await verify_screen_state(shot_path, "The AI assistant has completed the task and is waiting for the next user input. No spinners or active generation indicators are visible.")
        if comp_check.get("approved"):
            completed = True
            break
        perm_check = await verify_screen_state(shot_path, "A permission prompt or approval request is visible on screen from the AI assistant.")
        if perm_check.get("approved"):
            if session_approved:
                if bot and ALLOWED_USER_ID:
                    try: await bot.send_message(chat_id=ALLOWED_USER_ID, text="✅ Auto-approved prompt for session.")
                    except: pass
                await _vision_trigger_approval()
            else:
                resp = await send_permission_prompt(shot_path, session_id, "Antigravity is asking for permission.")
                if resp == "appses":
                    session_approved = True
                    await _vision_trigger_approval()
                elif resp == "app":
                    await _vision_trigger_approval()
                else:
                    stop_event.set()
                    return "🛑 Orchestration halted by user rejection."
                    
    if not completed:
        stop_event.set()
        return "⚠️ Antigravity orchestration timed out."
        
    # 5. Interactive Feedback Loop
    while True:
        await _trigger_e2e_test()
        site_shot = await _validate_and_screenshot_website(project_dir)
        
        req_id = str(uuid.uuid4())[:8]
        memory_store.set_fact("waiting_for_orchestrator_feedback", f"{session_id}_{req_id}")
        
        if bot and ALLOWED_USER_ID:
            kb = [[InlineKeyboardButton("✅ Approve", callback_data=f"ag_fbapp_{session_id}_{req_id}")],
                  [InlineKeyboardButton("🛑 Cancel", callback_data=f"ag_fbcan_{session_id}_{req_id}")]]
            if site_shot:
                with open(site_shot, "rb") as f:
                    await bot.send_photo(chat_id=ALLOWED_USER_ID, photo=f, caption="Review the website. If it's good, click Approve. Otherwise, type what's missing or what to add.", reply_markup=InlineKeyboardMarkup(kb))
            else:
                await bot.send_message(chat_id=ALLOWED_USER_ID, text="Website failed to run. Type what to fix, or click Cancel.", reply_markup=InlineKeyboardMarkup(kb))
        
        # Wait for feedback or button
        feedback = None
        for _ in range(600):
            val = memory_store.get_fact(f"ag_response_{session_id}_{req_id}")
            if val == "fbapp":
                feedback = "approve"
                break
            elif val == "fbcan":
                feedback = "cancel"
                break
            elif val and val.startswith("TEXT:"):
                feedback = val.replace("TEXT:", "")
                break
            await asyncio.sleep(1)
            
        memory_store.set_fact("waiting_for_orchestrator_feedback", None)
        
        if feedback == "approve":
            break
        elif feedback == "cancel":
            stop_event.set()
            return "🛑 Orchestration cancelled during feedback loop."
        elif feedback:
            await _type_in_chat(feedback)
            
            # Wait for coding again
            for i in range(60):
                await asyncio.sleep(10)
                s_res = take_desktop_screenshot()
                if not s_res.startswith("SCREENSHOT:"): continue
                s_path = s_res.replace("SCREENSHOT:", "")
                if (await verify_screen_state(s_path, "The AI assistant has completed the task and is waiting for the next user input. No spinners visible.")).get("approved"):
                    break
    
    stop_event.set()
    
    # 6. Final Report & Zip
    await _generate_final_report(project_dir)
    res = create_zip_archive([str(project_dir)], f"{project_name}.zip")
    if site_shot and res.startswith("SENDFILE:"):
        res = f"{res}|SCREENSHOT:{site_shot}"
    elif site_shot:
        res = f"SENDFILE:{res}|📦 Archive: {project_name}.zip|SCREENSHOT:{site_shot}"
    else:
        if res.startswith("SENDFILE:"):
            res = f"{res} (Note: couldn't get a visual confirmation the site is running, but the project files are included)"
        else:
            res = f"SENDFILE:{res}|📦 Archive: {project_name}.zip (Note: couldn't get a visual confirmation the site is running, but the project files are included)"
    return res
