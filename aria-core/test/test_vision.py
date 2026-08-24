import asyncio
import sys
from pathlib import Path

# Add the parent directory to sys.path so we can import modules
parent_dir = Path(__file__).parent.parent
sys.path.append(str(parent_dir))

from vision_gateway import verify_screen_state
from tool_executor import take_desktop_screenshot

async def test_vision():
    print("Capturing screenshot...")
    shot_result = take_desktop_screenshot()
    
    if not shot_result.startswith("SCREENSHOT:"):
        print("Failed to take screenshot:", shot_result)
        return
        
    shot_path = shot_result.split("SCREENSHOT:")[1]
    print(f"Screenshot saved to: {shot_path}")
    
    print("Calling vision_gateway to verify we are looking at a desktop or IDE...")
    import memory_store
    for engine in ["API1", "API2", "GROQ", "OPENROUTER", "LOCAL"]:
        memory_store.update_engine_metric(engine, tokens=0, status=200, latency=0.0, failures=0, cooldown=0.0)

    result = await verify_screen_state(
        screenshot_path=shot_path,
        expected_description="The screen shows a typical Windows desktop, or a code editor/IDE like VS Code with some python code visible.",
        context="Testing the vision gateway using Gemini API."
    )
    
    print("\nVision Gateway Result:")
    import json
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    asyncio.run(test_vision())
