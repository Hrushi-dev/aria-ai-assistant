import sys
sys.path.append(r'd:\AI-AIS\aria-core')
import tool_executor
import time
import os

print("Searching youtube...")
res1 = tool_executor.youtube_visual_search("lofi hip hop")
print("Search result:", res1)
time.sleep(3)

print("Clicking 1...")
res2 = tool_executor.execute_tool({"action": "youtube_click", "command": "1"})
print("Click result:", res2)

time.sleep(3)
# Take screenshot of the playing video
shot = tool_executor.take_desktop_screenshot()
print("Final screenshot:", shot)
