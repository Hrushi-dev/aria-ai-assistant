import sys
import time
import shutil
import os
import requests
import uuid
import random
import string
from pathlib import Path
from tool_executor import execute_tool, take_desktop_screenshot, DESKTOP_DIR
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
USER_ID = os.getenv("MY_TELEGRAM_USER_ID")

ARTIFACTS_DIR = Path(r"C:\Users\Dell\.gemini\antigravity\brain\3a35dfee-0b3a-4970-beee-574641ba486b")

def send_tg_message(text):
    if not BOT_TOKEN or not USER_ID: return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": USER_ID, "text": text})
    except Exception as e:
        print("TG Error:", e)

def send_tg_photo(photo_path, caption):
    if not BOT_TOKEN or not USER_ID: return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as f:
            requests.post(url, data={"chat_id": USER_ID, "caption": caption}, files={"photo": f})
    except Exception as e:
        print("TG Error:", e)

def send_tg_document(doc_path, caption):
    if not BOT_TOKEN or not USER_ID: return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        # We need to catch ConnectionResetError and report it properly
        with open(doc_path, "rb") as f:
            res = requests.post(url, data={"chat_id": USER_ID, "caption": caption}, files={"document": f})
            if res.status_code != 200:
                print(f"TG Upload Error: {res.text}")
    except Exception as e:
        print("TG Error:", e)

def random_string(length=8):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def run_orchestrated_test(name, intent, minimize_query=None, delay=2.0):
    print(f"\n--- Running {name} ---")
    send_tg_message(f"🧪 Test: {name}")
    
    # 1. Minimize everything before starting to ensure clean state
    execute_tool({"action": "minimize_all"})
    time.sleep(1.0)
    
    # 2. Execute target action (brings it to front)
    try:
        res = execute_tool(intent)
        res_str = str(res)
    except Exception as e:
        res_str = f"Error: {e}"
        
    time.sleep(delay)
    
    # 3. Take screenshot
    shot_res = take_desktop_screenshot()
    dest_name = f"Orchestrated_{name.replace(' ', '_')}.png"
    dest_path = ARTIFACTS_DIR / dest_name
    
    if shot_res.startswith("SCREENSHOT:"):
        shot_path = shot_res.replace("SCREENSHOT:", "")
        try:
            shutil.copy(shot_path, dest_path)
            send_tg_photo(dest_path, f"Proof: {name}\nOutput: {res_str[:200]}")
        except Exception as e:
            pass
            
    # Handle outputs (SENDFILE)
    if res_str.startswith("SENDFILE:"):
        parts = res_str.split("SENDFILE:", 1)[1].split("|", 1)
        file_path = parts[0].strip()
        send_tg_document(file_path, f"File output for {name}")

    # 4. Minimize the specific tab/app instead of closing it
    if minimize_query:
        min_res = execute_tool({"action": "minimize_app", "command": minimize_query})
        try:
            print(f"Minimize result for {minimize_query}: {min_res}")
        except UnicodeEncodeError:
            print(f"Minimize result for {minimize_query}: [Contains Emojis]")
        time.sleep(1.0)


# Pre-test: Token Quota & Random ZIP
# 1. Token quota
token_res = execute_tool({"action": "check_tokens"})
send_tg_message(token_res)

# 2. Random Zip
random_name = f"archive_{random_string()}.zip"
print(f"Creating random ZIP: {random_name}")
execute_tool({"action": "create_file_folder", "target_path": str(DESKTOP_DIR), "folder_name": "pics", "file_name": "random.txt", "file_content": "Random content"})
time.sleep(1.0)
zip_res = execute_tool({"action": "create_zip", "source_paths": [str(DESKTOP_DIR / "pics")], "file_name": random_name, "target_path": str(DESKTOP_DIR)})
if str(zip_res).startswith("SENDFILE:"):
    file_path = str(zip_res).split("SENDFILE:", 1)[1].split("|", 1)[0].strip()
    send_tg_document(file_path, f"📦 Here is your randomly named ZIP: {random_name}")

tests = [
    ("Open Notepad", {"action": "open_app", "command": "notepad"}, "notepad", 2.0),
    ("Open Microsoft Store", {"action": "open_app", "command": "ms-windows-store:"}, "store", 4.0),
    ("Web Search Aria AI", {"action": "web_search", "command": "Aria AI"}, "browser", 5.0),
    ("WhatsApp Message", {"action": "whatsapp_message", "command": "bhavani", "file_content": "blind typing test with minimize"}, "whatsapp", 8.0)
]

try:
    for name, intent, min_query, delay in tests:
        run_orchestrated_test(name, intent, min_query, delay)
finally:
    print("Orchestrated tests complete.")
