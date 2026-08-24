import asyncio
import sys
import uuid
from pathlib import Path

parent_dir = Path(__file__).parent.parent
sys.path.append(str(parent_dir))
sys.stdout.reconfigure(encoding='utf-8')

import memory_store
from antigravity_orchestrator import run_orchestration

async def simulate_telegram_user(delay_sec: int, action: str):
    await asyncio.sleep(delay_sec)
    print(f"[Telegram Sim] Attempting to find pending request to simulate: {action}")
    # Find the most recent req_id in memory_store facts, or just scan
    # Actually, we don't know session_id or req_id easily unless we list facts.
    facts = memory_store.get_all_facts()
    # Looking for a fact that hasn't been set? No, memory_store doesn't store pending.
    # The orchestrator is polling `ag_response_{session_id}_{req_id}`.
    # It hasn't been created yet. But we know it will poll. We can't know the ID unless we intercept it.
    # Wait, `run_orchestration` prints or sends to telegram. Since Telegram is not configured, it prints "Awaiting manual DB inject for test."
    # We can patch memory_store.get_fact to print the key it's polling!
    pass

async def main():
    intent = {
        "folder_name": "TestProjectE2E",
        "summary": "Create a file named hello.txt and write 'hello world' to it. Then create a file named test.txt and write 'test' to it. This will require two file write permissions."
    }
    print("Starting orchestration...")
    
    # Patch memory_store.get_fact to intercept the polled key
    original_get_fact = memory_store.get_fact
    pending_keys = set()
    
    def patched_get_fact(key: str):
        if key.startswith("ag_response_") and key not in pending_keys:
            pending_keys.add(key)
            print(f"[Sim] Detected polling for key: {key}")
            # Determine which action to take based on how many times we've been prompted
            prompt_count = len(pending_keys)
            if prompt_count == 1:
                action = "app"
                print(f"[Sim] Simulating user click: ✅ Approve for first prompt ({key})")
            elif prompt_count == 2:
                action = "appses"
                print(f"[Sim] Simulating user click: ✅ Approve for session for second prompt ({key})")
            else:
                action = "app" # fallback
                
            # Simulate the delay of a user reading it
            async def inject_later():
                await asyncio.sleep(2)
                memory_store.set_fact(key, action)
                print(f"[Sim] Injected {action} into {key}")
            
            asyncio.create_task(inject_later())
            
        return original_get_fact(key)
        
    memory_store.get_fact = patched_get_fact
    
    res = await run_orchestration(intent)
    print("Result:", res)

if __name__ == "__main__":
    asyncio.run(main())
