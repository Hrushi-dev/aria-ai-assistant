"""
planner.py — ARIA System Janitor Planner
=========================================
Connects to Gemini API to convert a plain-English maintenance goal into a
structured JSON action plan that the executor can safely run.
"""

import json
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Load .env from this directory first, then fall back to aria-core
load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent / "aria-core" / ".env", override=False)

try:
    from google import genai
    from google.genai import types
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Action plan JSON schema (matches onemore.md spec)
# ---------------------------------------------------------------------------
ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary":               {"type": "string"},
        "risk_level":            {"type": "integer", "minimum": 0, "maximum": 4},
        "requires_confirmation": {"type": "boolean"},
        "target_path":           {"type": "string"},
        "command":               {"type": "string"},
        "estimated_reclaim_gb":  {"type": "number"},
    },
    "required": ["summary", "risk_level", "requires_confirmation", "target_path", "command"],
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "goal_description": {"type": "string"},
        "actions": {
            "type": "array",
            "items": ACTION_SCHEMA,
            "minItems": 1,
        },
        "total_estimated_reclaim_gb": {"type": "number"},
    },
    "required": ["goal_description", "actions"],
}

# Risk classification context fed to the model
RISK_CONTEXT = """
Risk Level Classification:
  0 - Inspect: Read-only scan (Get-PSDrive, du, listing). Auto-execute.
  1 - Cache Purge: Known temp/installer caches (NVIDIA, Windows Update staging, %TEMP%). Auto-execute within whitelist.
  2 - Migration: Moving directories + creating symlinks (mklink). Requires user prompt.
  3 - Destructive: Permanent deletion of user data, games, or large folders. Requires strict confirmation.
  4 - System Config: Services, power settings, driver uninstalls. Requires strict confirmation.

Requires_confirmation rule:
  - risk_level 0 or 1 → requires_confirmation: false
  - risk_level 2, 3, or 4 → requires_confirmation: true
"""

SYSTEM_CONTEXT = """
You are ARIA System Janitor, a Windows disk maintenance planning agent.
The machine state:
  - OS: Windows 11, drives C: and D:
  - C: Free ≈ 40 GB. D: is the primary data drive.
  - .conda and .gemini are SYMLINKS pointing to D:\\conda and D:\\gemini — DO NOT touch these.
  - WSL Ubuntu and Docker are on D:\\WSL\\ — DO NOT touch these.
  - Ghost of Tsushima save data lives in C:\\Users\\Dell\\AppData\\Roaming\\Sucker Punch — DO NOT touch.
  - Hibernation is already disabled.

Safe maintenance targets (whitelist):
  - C:\\ProgramData\\NVIDIA Corporation\\NVIDIA App\\UpdateFramework\\*
  - C:\\ProgramData\\NVIDIA Corporation\\Downloader\\*
  - C:\\ProgramData\\Dell\\SARemediation\\SystemRepair\\Snapshots\\*
  - C:\\Windows\\SoftwareDistribution\\Download\\*
  - C:\\Users\\Dell\\AppData\\Local\\Temp\\*
  - C:\\Users\\Dell\\AppData\\Local\\NVIDIA\\*

Output ONLY valid JSON matching the schema. No prose, no markdown fences.
"""


def _extract_json(text: str) -> str:
    """Strip markdown fences and extract first JSON object from text."""
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[start:end + 1]
    return text


def _validate_plan(plan: dict):
    """Raise ValueError if plan doesn't match expected structure."""
    if not isinstance(plan, dict):
        raise ValueError("Plan must be a JSON object.")
    if "actions" not in plan or not isinstance(plan["actions"], list):
        raise ValueError("Plan must contain an 'actions' array.")
    if len(plan["actions"]) == 0:
        raise ValueError("Plan must contain at least one action.")

    for i, action in enumerate(plan["actions"]):
        for required_key in ["summary", "risk_level", "requires_confirmation", "target_path", "command"]:
            if required_key not in action:
                raise ValueError(f"Action {i} missing required field '{required_key}'.")
        risk = int(action["risk_level"])
        if not (0 <= risk <= 4):
            raise ValueError(f"Action {i} has invalid risk_level {risk}. Must be 0–4.")
        # Enforce requires_confirmation rule
        expected_confirm = risk >= 2
        if action["requires_confirmation"] != expected_confirm:
            action["requires_confirmation"] = expected_confirm  # auto-correct


async def _call_gemini(prompt: str) -> str:
    """Call Gemini API and return raw text response."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY_1")
    if not api_key:
        raise EnvironmentError(
            "No GEMINI_API_KEY found. Set it in aria-janitor/.env or aria-core/.env"
        )
    if not _GENAI_AVAILABLE:
        raise ImportError("google-genai not installed. Run: pip install google-genai")

    client = genai.Client(api_key=api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_CONTEXT,
            temperature=0.1,
            max_output_tokens=2048,
        ),
    )
    return response.text


async def generate_plan(goal: str) -> dict:
    """
    Convert a plain-English maintenance goal into a structured action plan.

    Parameters
    ----------
    goal : str
        E.g. "Clean up NVIDIA caches and clear Windows Update downloads"

    Returns
    -------
    dict
        Validated plan with 'goal_description', 'actions', and
        'total_estimated_reclaim_gb' keys.
    """
    prompt = f"""Generate a Windows disk maintenance plan for this goal: "{goal}"

{RISK_CONTEXT}

Output ONLY valid JSON in this exact format:
{{
  "goal_description": "short description of what will be done",
  "actions": [
    {{
      "summary": "human-readable description of this step",
      "risk_level": 1,
      "requires_confirmation": false,
      "target_path": "C:\\\\ProgramData\\\\NVIDIA Corporation\\\\NVIDIA App\\\\UpdateFramework",
      "command": "Remove-Item -Path 'C:\\\\ProgramData\\\\NVIDIA Corporation\\\\NVIDIA App\\\\UpdateFramework\\\\*' -Recurse -Force -ErrorAction SilentlyContinue",
      "estimated_reclaim_gb": 7.3
    }}
  ],
  "total_estimated_reclaim_gb": 7.3
}}

Rules:
- Use PowerShell syntax for all commands.
- Never target protected paths (Windows system dirs, Documents, Desktop, game saves, WSL, conda/gemini symlinks).
- Use -ErrorAction SilentlyContinue so locked files don't abort the run.
- For inspection steps (risk_level 0), use read-only commands like Get-ChildItem, Get-PSDrive, du.
- Output ONLY the JSON, no other text."""

    # First attempt
    raw = await _call_gemini(prompt)
    json_text = _extract_json(raw)

    try:
        plan = json.loads(json_text)
        _validate_plan(plan)
        return plan
    except Exception as e:
        # Retry once with error feedback
        retry_prompt = prompt + (
            f"\n\nYour previous response failed validation: {e}\n"
            "Return ONLY the corrected JSON."
        )
        raw = await _call_gemini(retry_prompt)
        json_text = _extract_json(raw)
        plan = json.loads(json_text)
        _validate_plan(plan)
        return plan


def generate_plan_sync(goal: str) -> dict:
    """Synchronous wrapper for generate_plan (for CLI use)."""
    return asyncio.run(generate_plan(goal))


# ---------------------------------------------------------------------------
# Telegram-hook interface (for future aria-core integration)
# ---------------------------------------------------------------------------
async def generate_plan_for_telegram(goal: str) -> dict:
    """
    Same as generate_plan but returns a dict shaped for Telegram delivery.
    Designed to be called from aria-core/main_daemon.py in the future.
    """
    plan = await generate_plan(goal)
    return {
        "janitor_plan": plan,
        "action_count": len(plan.get("actions", [])),
        "total_estimated_reclaim_gb": plan.get("total_estimated_reclaim_gb", 0),
        "has_risky_actions": any(
            a.get("risk_level", 0) >= 2 for a in plan.get("actions", [])
        ),
    }


if __name__ == "__main__":
    import sys
    goal = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Check free space on C: and D: drives"
    print(f"Planning: {goal}\n")
    plan = generate_plan_sync(goal)
    print(json.dumps(plan, indent=2))
