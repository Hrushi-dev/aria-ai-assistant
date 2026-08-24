import asyncio
from pathlib import Path
import sys

parent_dir = Path(__file__).parent.parent
sys.path.append(str(parent_dir))
sys.stdout.reconfigure(encoding='utf-8')

from antigravity_orchestrator import run_orchestration

async def main():
    intent = {
        "folder_name": "NikeLuxuryWeb",
        "summary": "Create a luxury website for the Nike brand. Make it fully functional, dynamic, and extremely premium. You must gather pictures from the internet for real Nike products and add them in the picture placeholders. The website should have a sleek dark mode, modern typography, smooth gradients, and interactive hover effects."
    }
    
    print("Starting LIVE Orchestration for NikeLuxuryWeb...")
    res = await run_orchestration(intent)
    print("LIVE Orchestration Result:")
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
