import asyncio
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

parent_dir = Path(__file__).parent.parent
sys.path.append(str(parent_dir))

from antigravity_orchestrator import run_orchestration

async def main():
    intent = {
        "folder_name": "TestProject",
        "summary": "Create a python script that prints hello world. Do not ask for clarification, just execute."
    }
    print("Starting orchestration...")
    res = await run_orchestration(intent)
    print("Result:", res)

if __name__ == "__main__":
    asyncio.run(main())
