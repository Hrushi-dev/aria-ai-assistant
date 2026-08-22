import json
import uuid
from router import generate

VALID_TOOLS = [
    "create_file_folder", "delete_folder", "delete_file", "close_window", "minimize_all", 
    "open_app", "play_youtube", "youtube_visual_search", "youtube_scroll", "youtube_click", 
    "play_spotify", "web_search", "take_screenshot", "list_files", "list_windows", 
    "set_memory_trigger", "create_zip", "volume_control", "convert_to_pdf", "gui_click", 
    "gui_type", "whatsapp_message", "media_control", "python_code_interpreter"
]

def _extract_json(text: str) -> str:
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end+1]
    return text

async def generate_plan(goal: str) -> dict:
    prompt = f"""You are a strict JSON planning agent. Your task is to generate an execution plan for this goal: '{goal}'
You MUST output ONLY valid JSON matching this exact schema:
{{
  "goal_id": "plan_<random>",
  "goal_description": "short description",
  "steps": [
    {{"step_id": 1, "tool": "tool_name", "description": "what this step does", "params": {{"key": "value"}} }}
  ],
  "scope_boundary": {{
    "allowed_read_paths": ["/path/to/read", "desktop", "downloads"],
    "allowed_write_paths": ["/path/to/write", "desktop", "downloads"],
    "external_actions": ["send_telegram_file", "web_search"]
  }}
}}

CRITICAL RULES:
1. For ANY data, file manipulation, or spreadsheet tasks, you MUST use `python_code_interpreter` (e.g. with pandas or standard python libraries). DO NOT use GUI automation (`open_app`, `gui_click`, `gui_type`) for data manipulation. GUI automation is fragile and lacks clean error output for self-healing. Only use GUI tools for inherently GUI-only tasks (like WhatsApp desktop or YouTube UI).
2. If the user asks to "send it to me" or "send me the file", DO NOT invent a delivery tool step like `email` or `send_telegram_file`. File delivery is handled automatically by the runtime at the end of the execution. However, you MUST include `send_telegram_file` in the `external_actions` array to authorize the delivery.
3. Your `external_actions` in the scope boundary must ONLY reflect real external actions like `send_telegram_file` or `web_search`.
4. When a dedicated tool already exists in VALID_TOOLS for a task (e.g. `convert_to_pdf` for PDF conversion, `create_zip` for archiving), use that dedicated tool directly — do not reimplement its functionality via `python_code_interpreter`. Reserve `python_code_interpreter` for data manipulation/analysis steps that have no dedicated tool (cleaning, transforming, computing from a spreadsheet/CSV/etc).
5. For `convert_to_pdf`, the expected parameter for the source file is `target_path`. For `python_code_interpreter`, use `code`.
6. DATA FLOW & PATH CHAINING: Each step's file input MUST reference the actual output path of the prior step, not a newly-invented path. Any new intermediate or cleaned files MUST be written strictly into `allowed_write_paths` (do not save them back into `allowed_read_paths`). Note that `convert_to_pdf` automatically derives its output filename by replacing the extension with `.pdf` in the same directory, so the step *following* it must reference that derived `.pdf` path as its input.

Valid tool names are: {', '.join(VALID_TOOLS)}.
Do not include any other text outside the JSON.
"""
    
    # First attempt
    resp_text = await generate(prompt)
    json_text = _extract_json(resp_text)
    
    try:
        plan = json.loads(json_text)
        _validate_plan(plan)
        return plan
    except Exception as e:
        # Retry once
        retry_prompt = prompt + f"\n\nYour previous response failed validation with this error: {e}\nPlease correct the JSON and return ONLY the valid JSON."
        resp_text = await generate(retry_prompt)
        json_text = _extract_json(resp_text)
        try:
            plan = json.loads(json_text)
            _validate_plan(plan)
            return plan
        except Exception as retry_e:
            raise ValueError(f"Failed to generate valid plan after 2 attempts. Last error: {retry_e}")

def _validate_plan(plan: dict):
    if not isinstance(plan, dict): raise ValueError("Plan must be a JSON object.")
    if "steps" not in plan or not isinstance(plan["steps"], list): raise ValueError("Missing or invalid 'steps' array.")
    if len(plan["steps"]) == 0: raise ValueError("Plan must contain at least one step.")
    
    if "goal_id" not in plan or not str(plan["goal_id"]).startswith("plan_"):
        plan["goal_id"] = f"plan_{uuid.uuid4().hex[:8]}"
        
    for step in plan["steps"]:
        tool = step.get("tool")
        if tool not in VALID_TOOLS:
            raise ValueError(f"Invalid tool '{tool}' used in step {step.get('step_id')}. Must be one of {VALID_TOOLS}")
