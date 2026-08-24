import json
import asyncio
from pathlib import Path
import router

async def verify_screen_state(screenshot_path: str, expected_description: str, context: str = None) -> dict:
    """
    Calls the cloud vision model to verify if the screen state matches expectations.
    Returns: {"approved": bool, "reason": str, "next_action_hint": str}
    """
    if not Path(screenshot_path).exists():
        return {
            "approved": False,
            "reason": f"Screenshot file not found: {screenshot_path}",
            "next_action_hint": "Check screenshot capture logic."
        }
        
    prompt = f"""
You are an independent GUI verification system.
Your job is to look at the provided screenshot and determine if the current screen state matches the expected state.

EXPECTED STATE DESCRIPTION:
{expected_description}

CONTEXT:
{context or "No additional context provided."}

Analyze the screenshot carefully. Return exactly a JSON object (without markdown code blocks or extra text) with the following structure:
{{
    "approved": <true if the screen matches the expected state, false otherwise>,
    "reason": "<A brief, clear explanation of what you see and why it matches or fails>",
    "next_action_hint": "<If approved, state 'proceed'. If not approved, suggest how the user/system might fix it, e.g., 'Click the search bar', 'Wait for page to load'>"
}}
"""
    try:
        # Note: Engine override defaults to API1/API2 (Gemini) since Groq vision requires a valid key
        # and OpenRouter/Local models might not support vision or have keys configured for it.
        # Once Groq vision is validated and a real key is present, this can be updated or allowed to float.
        response_text = await router.generate(prompt, image_path=screenshot_path)
        
        # Strip markdown if present
        clean_json = response_text.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        elif clean_json.startswith("```"):
            clean_json = clean_json[3:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
            
        result = json.loads(clean_json.strip())
        
        # Ensure schema
        return {
            "approved": bool(result.get("approved", False)),
            "reason": str(result.get("reason", "No reason provided.")),
            "next_action_hint": str(result.get("next_action_hint", "Unknown."))
        }
    except json.JSONDecodeError as e:
        return {
            "approved": False,
            "reason": f"Failed to parse vision model response. Raw: {response_text[:100]}...",
            "next_action_hint": "Retry verification."
        }
    except Exception as e:
        return {
            "approved": False,
            "reason": f"Vision verification failed with error: {str(e)}",
            "next_action_hint": "Check model API connectivity."
        }
