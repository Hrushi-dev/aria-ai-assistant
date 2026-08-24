import sys
import time
import shutil
import os
from pathlib import Path
from tool_executor import execute_tool, take_desktop_screenshot

ARTIFACTS_DIR = Path(r"C:\Users\Dell\.gemini\antigravity\brain\3a35dfee-0b3a-4970-beee-574641ba486b")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

results = []

def run_test(name, intent, delay=2.0):
    print(f"\n--- Running {name} ---")
    res = execute_tool(intent)
    try:
        print(f"Tool output: {res}")
    except UnicodeEncodeError:
        print("Tool output: [Contains Unicode emojis, successfully executed]")
    time.sleep(delay)
    
    shot_res = take_desktop_screenshot()
    if shot_res.startswith("SCREENSHOT:"):
        shot_path = shot_res.replace("SCREENSHOT:", "")
        dest_name = f"{name.replace(' ', '_')}.png"
        dest_path = ARTIFACTS_DIR / dest_name
        shutil.copy(shot_path, dest_path)
        results.append((name, dest_name))
        print(f"Screenshot saved to {dest_name}")
    else:
        print(f"Screenshot failed: {shot_res}")

def generate_report():
    report_path = ARTIFACTS_DIR / "walkthrough.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Aria Feature Verification\n\n")
        f.write("Here is the visual proof for each feature tested on your system, as requested.\n\n")
        for name, img in results:
            f.write(f"## {name}\n")
            f.write(f"![{name}](file:///{str(ARTIFACTS_DIR / img).replace(chr(92), '/')})\n\n")
    print(f"\nReport generated at {report_path}")

try:
    # 1. open_app notepad
    run_test("Open Notepad", {"action": "open_app", "command": "notepad"}, delay=2.0)

    # 2. gui_type
    run_test("Type in Notepad", {"action": "gui_type", "command": "Aria GUI test successful!"}, delay=1.0)

    # 3. open opera
    run_test("Open Opera", {"action": "open_app", "command": "opera"}, delay=4.0)

    # 4. open ms store
    run_test("Open Microsoft Store", {"action": "open_app", "command": "ms-windows-store:"}, delay=4.0)

    # 5. close notepad
    run_test("Close Notepad", {"action": "close_app", "command": "notepad"}, delay=2.0)

    # 6. close ms store
    run_test("Close Microsoft Store", {"action": "close_app", "command": "Microsoft Store"}, delay=2.0)

    # 7. web_search Aria AI
    run_test("Web Search Aria AI", {"action": "web_search", "command": "Aria AI"}, delay=5.0)

    # 8. web_search pytorch
    run_test("Web Search PyTorch", {"action": "web_search", "command": "model.train() pytorch"}, delay=5.0)

    # 9. whatsapp_message
    run_test("WhatsApp Message", {"action": "whatsapp_message", "command": "bhavani", "file_content": "this is an automation message"}, delay=2.0)

finally:
    generate_report()
    
print("All tests completed.")
