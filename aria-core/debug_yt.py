import sys
sys.path.append(r'd:\AI-AIS\aria-core')
import tool_executor
import time

print("Searching youtube...")
res1 = tool_executor.youtube_visual_search("lofi hip hop")
print("Search result:", res1)
time.sleep(2)

print("Clicking 1...")
res2 = tool_executor.execute_tool({"action": "youtube_click", "command": "1"})
print("Click result:", res2)
