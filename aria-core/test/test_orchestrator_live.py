import asyncio
import os
import sys
import time
import json
import threading
from pathlib import Path
from dotenv import load_dotenv

parent_dir = Path(__file__).parent.parent
sys.path.append(str(parent_dir))

import memory_store
from antigravity_orchestrator import run_orchestration
from tool_executor import take_desktop_screenshot

async def auto_approver():
    """Simulate a user clicking 'Approve' on Telegram when prompted"""
    while True:
        await asyncio.sleep(2)
        
        # Check if orchestrator is waiting for plan approval
        # We need to find any 'ag_response_{session}_{req}' key that is pending
        facts = memory_store.get_all_facts()
        for key in facts:
            if key.startswith('ag_response_'):
                val = facts[key]
                if not val or val == 'None':
                    print(f"[Auto-Approver] Auto-approving plan for key {key}...")
                    memory_store.set_fact(key, "planapp")
                
        # Check if orchestrator is waiting for final feedback
        fb_key = memory_store.get_fact("waiting_for_orchestrator_feedback")
        if fb_key:
            full_key = f"ag_response_{fb_key}"
            val = memory_store.get_fact(full_key)
            if not val:
                print(f"[Auto-Approver] Auto-approving final website for {full_key}...")
                memory_store.set_fact(full_key, "fbapp")
                
async def main():
    intent = {
        "folder_name": "TestWebsite",
        "summary": "Create a sleek, minimalist dark mode portfolio website for a developer named Alex. Include a hero section with a greeting, and a skills section."
    }
    
    print("Starting Live Orchestrator Test...")
    print("WARNING: Do not touch the mouse or keyboard during this test!")
    
    # Run auto-approver in background
    asyncio.create_task(auto_approver())
    
    result = await run_orchestration(intent)
    
    print("\n\n--- ORCHESTRATION COMPLETE ---")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
