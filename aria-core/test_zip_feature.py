import os
import shutil
import time
import requests
from pathlib import Path
from tool_executor import execute_tool, take_desktop_screenshot, DESKTOP_DIR
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
USER_ID = os.getenv("MY_TELEGRAM_USER_ID")

ARTIFACTS_DIR = Path(r"C:\Users\Dell\.gemini\antigravity\brain\3a35dfee-0b3a-4970-beee-574641ba486b")

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

print("Starting ZIP test...")
# 1. Create 'pics' folder on Desktop using tool_executor
print("Creating 'pics' folder and file...")
execute_tool({"action": "create_file_folder", "target_path": str(DESKTOP_DIR), "folder_name": "pics", "file_name": "test_image.txt", "file_content": "This is a placeholder for a picture."})

# 2. Wait to ensure file system sync
time.sleep(1)

# 3. Create ZIP using tool_executor
print("Zipping the folder...")
zip_intent = {"action": "create_zip", "source_paths": [str(DESKTOP_DIR / "pics")], "file_name": "pics_archive.zip", "target_path": str(DESKTOP_DIR)}
zip_result = str(execute_tool(zip_intent))
try:
    print("ZIP Result:", zip_result)
except UnicodeEncodeError:
    print("ZIP Result: [Contains Emojis]")

# Take screenshot as proof
print("Capturing screenshot...")
shot_res = take_desktop_screenshot()
if shot_res.startswith("SCREENSHOT:"):
    shot_path = shot_res.replace("SCREENSHOT:", "")
    dest_path = ARTIFACTS_DIR / "pics_zip_proof.png"
    shutil.copy(shot_path, dest_path)
    send_tg_photo(dest_path, "📸 Here is the visual proof that the 'pics' folder was created and zipped on the desktop.")
    print("Proof saved and sent.")

# Extract the ZIP file path and send it to Telegram
if zip_result.startswith("SENDFILE:"):
    file_path = zip_result.split("SENDFILE:", 1)[1].split("|", 1)[0].strip()
    print(f"Sending ZIP file to Telegram: {file_path}")
    send_tg_document(file_path, "📦 Here is the 'pics_archive.zip' file you requested!")
else:
    print("ZIP creation did not return a SENDFILE string.")

print("Test complete.")
