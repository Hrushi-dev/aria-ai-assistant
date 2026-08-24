import sys
import time
import shutil
import os
import requests
from pathlib import Path
from tool_executor import execute_tool, take_desktop_screenshot
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
USER_ID = os.getenv("MY_TELEGRAM_USER_ID")

ARTIFACTS_DIR = Path(r"C:\Users\Dell\.gemini\antigravity\brain\3a35dfee-0b3a-4970-beee-574641ba486b")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

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
        with open(doc_path, "rb") as f:
            requests.post(url, data={"chat_id": USER_ID, "caption": caption}, files={"document": f})
    except Exception as e:
        print("TG Error:", e)

results = []

def run_test(name, intent, delay=2.0):
    print(f"\n--- Running {name} ---")
    send_tg_message(f"🧪 Running Test: {name}")
    
    try:
        res = execute_tool(intent)
        res_str = str(res)
    except Exception as e:
        res_str = f"Error: {e}"
        
    time.sleep(delay)
    
    # Take screenshot of the screen state
    shot_res = take_desktop_screenshot()
    dest_name = f"{name.replace(' ', '_')}.png"
    dest_path = ARTIFACTS_DIR / dest_name
    
    if shot_res.startswith("SCREENSHOT:"):
        shot_path = shot_res.replace("SCREENSHOT:", "")
        try:
            shutil.copy(shot_path, dest_path)
            results.append((name, dest_name))
            send_tg_photo(dest_path, f"Proof: {name}\nOutput: {res_str[:200]}")
        except Exception as e:
            send_tg_message(f"Failed to copy screenshot for {name}: {e}")
    else:
        send_tg_message(f"Proof for {name} failed: No screenshot. Output: {res_str[:200]}")

    # Handle outputs (SENDFILE, etc.)
    if res_str.startswith("SENDFILE:"):
        parts = res_str.split("SENDFILE:", 1)[1].split("|", 1)
        file_path = parts[0].strip()
        send_tg_document(file_path, f"File output for {name}")

tests = [
    ("Create Folder and File", {"action": "create_file_folder", "folder_name": "AriaTestFolder", "file_name": "test_doc.txt", "file_content": "Aria automation test file."}, 2.0),
    ("List Files", {"action": "list_files", "target_path": "AriaTestFolder"}, 1.0),
    ("Convert to PDF", {"action": "convert_to_pdf", "target_path": "AriaTestFolder/test_doc.txt"}, 3.0),
    ("Create ZIP", {"action": "create_zip", "source_paths": ["AriaTestFolder"], "file_name": "AriaTestArchive.zip"}, 2.0),
    ("Delete File", {"action": "delete_file", "target_path": "AriaTestFolder/test_doc.pdf"}, 1.0),
    ("Delete Folder", {"action": "delete_folder", "target_path": "AriaTestFolder"}, 1.0),
    ("Set Memory Trigger", {"action": "set_memory_trigger", "command": "test aria", "summary": "Aria is running perfectly."}, 1.0),
    ("List Windows", {"action": "list_windows"}, 1.0),
    ("Minimize All", {"action": "minimize_all"}, 1.0),
    ("Volume Mute", {"action": "volume_control", "command": "mute"}, 1.0),
    ("Volume Unmute", {"action": "volume_control", "command": "unmute"}, 1.0),
    ("Open Notepad", {"action": "open_app", "command": "notepad"}, 2.0),
    ("Type in Notepad", {"action": "gui_type", "command": "Aria GUI test successful!"}, 1.0),
    ("Open Opera", {"action": "open_app", "command": "opera"}, 4.0),
    ("Open Microsoft Store", {"action": "open_app", "command": "ms-windows-store:"}, 4.0),
    ("Close Notepad", {"action": "close_app", "command": "notepad"}, 1.0),
    ("Close Microsoft Store", {"action": "close_app", "command": "Microsoft Store"}, 1.0),
    ("Close Opera", {"action": "close_app", "command": "opera"}, 1.0),
    ("Web Search Aria AI", {"action": "web_search", "command": "Aria AI"}, 5.0),
    ("Web Search PyTorch", {"action": "web_search", "command": "model.train() pytorch"}, 5.0),
    ("WhatsApp Message", {"action": "whatsapp_message", "command": "bhavani", "file_content": "this is an automation message"}, 8.0),
    ("Play YouTube", {"action": "play_youtube", "command": "Aria AI demo"}, 6.0),
    ("YouTube Scroll", {"action": "youtube_scroll"}, 3.0),
    ("YouTube Click", {"action": "youtube_click", "command": "1"}, 4.0),
    ("Play Spotify", {"action": "play_spotify", "command": "lofi hip hop"}, 5.0)
]

try:
    for name, intent, delay in tests:
        run_test(name, intent, delay)
finally:
    with open(ARTIFACTS_DIR / "test_results.json", "w") as f:
        import json
        json.dump(results, f)
    print("All tests completed.")
