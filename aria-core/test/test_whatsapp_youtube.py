import asyncio
import sys
from pathlib import Path

parent_dir = Path(__file__).parent.parent
sys.path.append(str(parent_dir))
sys.stdout.reconfigure(encoding='utf-8')

from tool_executor import execute_tool_structured

async def main():
    print("Testing WhatsApp Retrofit...")
    intent_wa = {
        "action": "whatsapp_message",
        "command": "Test Contact",
        "file_content": "This is a test message."
    }
    # This might launch WhatsApp and test it.
    # Note: Since this is an automated test on the VM, it might fail if WhatsApp isn't logged in,
    # but the vision verification should catch the failure gracefully!
    res_wa = await execute_tool_structured(intent_wa)
    print("WhatsApp Result:")
    print(res_wa)

    print("\nTesting YouTube Retrofit...")
    intent_yt = {
        "action": "play_youtube",
        "command": "Never gonna give you up"
    }
    res_yt = await execute_tool_structured(intent_yt)
    print("YouTube Result:")
    print(res_yt)

if __name__ == "__main__":
    asyncio.run(main())
