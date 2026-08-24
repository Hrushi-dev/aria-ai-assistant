import asyncio
import sys
import json
from pathlib import Path

# Add the parent directory to sys.path
parent_dir = Path(__file__).parent.parent
sys.path.append(str(parent_dir))

import router
from antigravity_orchestrator import run_orchestration

# Mock run_orchestration for the isolated test so it doesn't build a real website
async def mock_run_orchestration(intent):
    print(f"\n[Mock] run_orchestration successfully invoked with intent:\n{json.dumps(intent, indent=2)}", flush=True)
    return "Mock Success"


SYSTEM_PROMPT = """You are Aria's Website Builder Brain.
The user wants to build a website. They will describe what they want.
Extract the following information from their description:
- type: (e.g. portfolio, blog, store, brand site, unknown)
- name: (name or title of the site, or unknown)
- style: (color theme, tone, aesthetics, or unknown)
- sections: (any specific pages, sections, or content mentioned, or unknown)

If they mention new details, update the existing details.
Output ONLY JSON in the following format:
{
  "type": "...",
  "name": "...",
  "style": "...",
  "sections": "..."
}
"""

def determine_next_question(state):
    """Determine what to ask next based on missing info."""
    if state["type"] == "unknown":
        return "What kind of website are we building? (e.g. portfolio, blog, store, brand site)"
    
    if state["name"] == "unknown":
        if state["type"] == "portfolio":
            return "What's your name or the name for this portfolio?"
        elif state["type"] == "store":
            return "What's the name of your store, and what are you selling?"
        else:
            return "What is the name of this website or brand?"

    if state["style"] == "unknown":
        return "Do you have any preferences for colors, vibe, or style? (e.g. dark mode, minimalist, neon, etc.)"

    if state["sections"] == "unknown":
        if state["type"] == "portfolio":
            return "What kind of work are you showcasing, and roughly how many projects?"
        elif state["type"] == "store":
            return "Are there any specific product categories or sections you want on the homepage?"
        else:
            return "Any specific sections or features you must have on this site?"
            
    return None

async def main():
    state = {
        "type": "unknown",
        "name": "unknown",
        "style": "unknown",
        "sections": "unknown",
        "follow_ups": 0
    }
    
    print("Aria: What do you want to build? Tell me about it in your own words — brand site, portfolio, blog, store, game page, whatever.", flush=True)
    
    mock_inputs = [
        "idk make it look sick, black and gold",
        "i guess a portfolio",
        "my name is alex",
        "mostly graphic design work, about 5 projects",
        "yes"
    ]
    mock_idx = 0
    
    while mock_idx < len(mock_inputs):
        user_input = mock_inputs[mock_idx]
        mock_idx += 1
        print(f"User: {user_input}", flush=True)
        
        # Call LLM to parse
        prompt = f"{SYSTEM_PROMPT}\n\nCurrent state:\n{json.dumps(state)}\n\nUser input: {user_input}\n\nJSON:"
        try:
            resp = await router.generate(prompt)
            print(f"[Debug] LLM Response: {resp}", flush=True)
            import re
            m = re.search(r'\{.*\}', resp, re.DOTALL)
            if m:
                updates = json.loads(m.group(0))
                state.update({k: v for k, v in updates.items() if v != "unknown"})
        except Exception as e:
            print(f"Error parsing with LLM: {e}", flush=True)
            
        next_q = determine_next_question(state)
        
        if not next_q or state["follow_ups"] >= 3:
            summary = f"Building: a {state['style']} {state['type']} called '{state['name']}' with {state['sections']}. Sound right?"
            print(f"Aria: {summary}", flush=True)
            
            # The next input should be 'yes'
            conf = mock_inputs[mock_idx] if mock_idx < len(mock_inputs) else "yes"
            mock_idx += 1
            print(f"User (yes/no): {conf}", flush=True)
            
            if "yes" in conf.lower() or "y" in conf.lower():
                print("Aria: Great! Passing to orchestrator...", flush=True)
                intent = {
                    "summary": f"Create a {state['style']} {state['type']} website for '{state['name']}'. Ensure it includes: {state['sections']}",
                    "folder_name": state['name'].replace(" ", "") if state['name'] != "unknown" else "WebProject"
                }
                
                # Actually invoke the (mocked) orchestration function to prove wiring
                await mock_run_orchestration(intent)
                break
            else:
                print("Aria: Okay, let's adjust. What needs changing?", flush=True)
        else:
            state["follow_ups"] += 1
            print(f"Aria: {next_q}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
