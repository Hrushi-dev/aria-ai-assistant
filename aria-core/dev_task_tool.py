"""
dev_task_tool.py — ARIA Project Dev Task Engine
================================================
Lets ARIA edit any registered project using Gemini-powered code intelligence,
then serves/restarts the dev server and sends a screenshot preview via Telegram.

Flow:
  1. Resolve project from natural language name using project_registry.json
  2. Read relevant source files as context
  3. Ask Gemini to produce a structured diff/edit plan
  4. Apply edits directly via Python file I/O
  5. Ensure the dev server is running (start or restart)
  6. Capture screenshot (for web apps) or take desktop screenshot (for GUI apps)
  7. Return screenshot path + summary for Telegram delivery
"""

import os
import sys
import json
import time
import asyncio
import subprocess
import threading
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# ── Load env (from aria-core or parent) ──────────────────────────────────────
_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env")

# ── Project registry ──────────────────────────────────────────────────────────
_REGISTRY_PATH = _HERE / "project_registry.json"

def _load_registry() -> dict:
    with open(_REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)["projects"]

def resolve_project(name: str) -> dict | None:
    """
    Fuzzy-match a project from the registry by name or alias.
    Returns the project dict or None.
    """
    registry = _load_registry()
    name_lower = name.strip().lower()
    for key, proj in registry.items():
        if name_lower == key:
            return {**proj, "key": key}
        for alias in proj.get("aliases", []):
            if name_lower in alias.lower() or alias.lower() in name_lower:
                return {**proj, "key": key}
    return None

def list_projects() -> str:
    """Return a formatted list of all registered projects."""
    registry = _load_registry()
    lines = ["📁 **Registered Projects:**\n"]
    for key, proj in registry.items():
        lines.append(f"• **{key}** — {proj['description']}\n  Path: `{proj['path']}`")
    return "\n".join(lines)

# ── Source file reader ────────────────────────────────────────────────────────

# Extensions to read for code context
CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".json", ".md"}
# Folders to always skip
SKIP_DIRS = {"node_modules", "venv", ".next", "__pycache__", ".git", "dist", "build", ".vscode"}

def _collect_source_files(project_path: Path, max_files: int = 20, max_size_kb: int = 50) -> list[dict]:
    """
    Collect up to max_files source files from a project (skipping deps).
    Returns list of {path, content} dicts.
    """
    files = []
    for root, dirs, filenames in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in filenames:
            if len(files) >= max_files:
                break
            fpath = Path(root) / fname
            if fpath.suffix.lower() not in CODE_EXTENSIONS:
                continue
            try:
                size_kb = fpath.stat().st_size / 1024
                if size_kb > max_size_kb:
                    continue
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                files.append({
                    "path": str(fpath.relative_to(project_path)),
                    "content": content,
                })
            except Exception:
                continue
        if len(files) >= max_files:
            break
    return files

# ── Gemini code edit planner ──────────────────────────────────────────────────

async def _plan_edits_with_gemini(project: dict, task: str, source_files: list[dict]) -> list[dict]:
    """
    Ask Gemini to produce a list of file edits for the given task.
    Returns list of {file_path, old_content, new_content, description} dicts.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY_1")
    if not api_key:
        raise EnvironmentError("No GEMINI_API_KEY found in aria-core/.env")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImportError("google-genai not installed. Run: pip install google-genai")

    # Build the source context
    source_context = ""
    for f in source_files:
        source_context += f"\n\n### FILE: {f['path']}\n```\n{f['content'][:3000]}\n```"

    prompt = f"""You are a senior software engineer editing the project "{project['description']}".
Project type: {project['type']}
Project path: {project['path']}

Task from user: "{task}"

Here are the current source files:
{source_context}

Produce ONLY a JSON array of file edits needed. Each edit must be an object with:
- "file_path": relative path from project root (e.g. "src/main.py" or "components/Button.jsx")
- "description": one-line description of what this change does
- "full_new_content": the complete new content of the file after the edit (NOT a diff, the full file)

Rules:
- Only include files that actually need to change.
- Keep changes minimal and focused on the task.
- Preserve all existing functionality not mentioned in the task.
- Output ONLY the JSON array, no prose, no markdown fences.
- Maximum 5 file edits per task.

Example output format:
[
  {{
    "file_path": "src/main.py",
    "description": "Add dark mode toggle to main window",
    "full_new_content": "...complete file content..."
  }}
]"""

    client = genai.Client(api_key=api_key)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=8192),
    )

    raw = response.text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()

    edits = json.loads(raw)
    if not isinstance(edits, list):
        raise ValueError("Gemini returned non-list response for edits")
    return edits

# ── File patcher ──────────────────────────────────────────────────────────────

def apply_edits(project_path: Path, edits: list[dict]) -> list[str]:
    """
    Apply a list of file edits to the project.
    Returns list of successfully patched file paths.
    """
    patched = []
    for edit in edits:
        rel_path = edit.get("file_path", "")
        new_content = edit.get("full_new_content", "")
        if not rel_path or not new_content:
            continue
        target = project_path / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        # Backup original
        if target.exists():
            backup_path = target.with_suffix(target.suffix + ".bak")
            backup_path.write_text(target.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        target.write_text(new_content, encoding="utf-8")
        patched.append(rel_path)
    return patched

def revert_edits(project_path: Path, edits: list[dict]):
    """Restore .bak files if something went wrong."""
    for edit in edits:
        rel_path = edit.get("file_path", "")
        target = project_path / rel_path
        backup = target.with_suffix(target.suffix + ".bak")
        if backup.exists():
            backup.replace(target)

# ── Dev server manager ────────────────────────────────────────────────────────

_running_servers: dict[str, subprocess.Popen] = {}

def _is_port_open(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0

def _extract_port(dev_url: str | None) -> int | None:
    if not dev_url:
        return None
    m = re.search(r":(\d+)", dev_url)
    return int(m.group(1)) if m else None

def ensure_dev_server(project: dict, timeout: int = 45) -> bool:
    """
    Ensure the project's dev server is running.
    Returns True if server is up, False on timeout.
    """
    key = project["key"]
    path = Path(project["path"])
    start_cmd = project.get("start_cmd")
    dev_url = project.get("dev_url")
    port = _extract_port(dev_url)
    proj_type = project.get("type", "")

    # If no dev_url (desktop apps), nothing to check
    if not dev_url or not port:
        return True

    # Already up?
    if _is_port_open(port):
        return True

    # Kill any stale process for this project
    if key in _running_servers:
        try:
            _running_servers[key].terminate()
        except Exception:
            pass

    # Start the server
    if not start_cmd:
        return False

    # Determine how to launch
    if proj_type in ("nextjs", "vite"):
        if start_cmd.endswith(".bat"):
            proc = subprocess.Popen(
                ["cmd", "/c", start_cmd],
                cwd=str(path),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            proc = subprocess.Popen(
                start_cmd.split(),
                cwd=str(path),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
    else:
        proc = subprocess.Popen(
            ["cmd", "/c", start_cmd],
            cwd=str(path),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    _running_servers[key] = proc

    # Wait for port to open
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_port_open(port):
            time.sleep(2)  # Give the app a moment to fully initialize
            return True
        time.sleep(1)
    return False

def stop_dev_server(project_key: str):
    """Stop a running dev server."""
    proc = _running_servers.get(project_key)
    if proc:
        try:
            proc.terminate()
        except Exception:
            pass
        del _running_servers[project_key]

# ── Screenshot capture ────────────────────────────────────────────────────────

def capture_web_screenshot(url: str, output_path: Path, wait_seconds: float = 2.0) -> bool:
    """
    Capture a screenshot of a web URL using the system browser + pyautogui.
    Falls back to PIL desktop screenshot if browser approach fails.
    """
    try:
        import webbrowser
        import pyautogui
        from PIL import ImageGrab

        webbrowser.open(url)
        time.sleep(wait_seconds + 1.5)

        # Try to bring the browser window to foreground
        import ctypes
        hwnd_found = [None]
        def _enum(hwnd, _):
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.lower()
                if any(k in title for k in ["chrome", "edge", "firefox", "brave", "localhost"]):
                    hwnd_found[0] = hwnd
                    return False
            return True
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(_enum), 0)
        if hwnd_found[0]:
            ctypes.windll.user32.ShowWindow(hwnd_found[0], 9)
            ctypes.windll.user32.SetForegroundWindow(hwnd_found[0])
            time.sleep(0.5)

        img = ImageGrab.grab()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path))
        return True
    except Exception:
        return False

def capture_desktop_screenshot(output_path: Path) -> bool:
    """Capture full desktop screenshot."""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(output_path))
        return True
    except Exception:
        return False

# ── Main orchestrator ─────────────────────────────────────────────────────────

async def run_dev_task(project_name: str, task: str, want_preview: bool = True) -> dict:
    """
    Full pipeline: resolve project → read files → Gemini edit → apply → serve → screenshot.

    Returns
    -------
    dict with keys:
        success: bool
        summary: str        — human-readable summary of what was done
        patched_files: list — list of edited file paths
        screenshot_path: str | None
        error: str | None
    """
    # 1. Resolve project
    project = resolve_project(project_name)
    if not project:
        return {
            "success": False,
            "summary": f"Project '{project_name}' not found in registry. Use 'list projects' to see available projects.",
            "patched_files": [],
            "screenshot_path": None,
            "error": "project_not_found",
        }

    project_path = Path(project["path"])
    if not project_path.exists():
        return {
            "success": False,
            "summary": f"Project folder not found at `{project_path}`.",
            "patched_files": [],
            "screenshot_path": None,
            "error": "folder_not_found",
        }

    # 2. Read source files
    source_files = _collect_source_files(project_path)

    # 3. Ask Gemini to plan edits
    try:
        edits = await _plan_edits_with_gemini(project, task, source_files)
    except Exception as e:
        return {
            "success": False,
            "summary": f"Gemini planning failed: {e}",
            "patched_files": [],
            "screenshot_path": None,
            "error": str(e),
        }

    if not edits:
        return {
            "success": False,
            "summary": "Gemini returned no edits for this task.",
            "patched_files": [],
            "screenshot_path": None,
            "error": "no_edits",
        }

    # 4. Apply edits
    try:
        patched = apply_edits(project_path, edits)
    except Exception as e:
        return {
            "success": False,
            "summary": f"Failed to apply edits: {e}",
            "patched_files": [],
            "screenshot_path": None,
            "error": str(e),
        }

    # 5. Ensure dev server running (for web apps)
    screenshot_path = None
    dev_url = project.get("dev_url")
    proj_type = project.get("type", "")

    if want_preview:
        if dev_url:
            server_up = ensure_dev_server(project, timeout=50)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shot_path = Path(project["path"]) / f".aria_preview_{ts}.png"

            if server_up:
                ok = capture_web_screenshot(dev_url, shot_path, wait_seconds=3)
            else:
                ok = capture_desktop_screenshot(shot_path)

            if ok:
                screenshot_path = str(shot_path)
        elif proj_type == "python-desktop":
            # Launch the app briefly for screenshot
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shot_path = Path(project["path"]) / f".aria_preview_{ts}.png"
            ok = capture_desktop_screenshot(shot_path)
            if ok:
                screenshot_path = str(shot_path)

    # 6. Build summary
    change_lines = [f"  • `{e['file_path']}` — {e.get('description', 'updated')}" for e in edits]
    summary = (
        f"✅ **{project['description']}** updated for: _{task}_\n\n"
        f"**Files changed ({len(patched)}):**\n" + "\n".join(change_lines)
    )

    return {
        "success": True,
        "summary": summary,
        "patched_files": patched,
        "screenshot_path": screenshot_path,
        "error": None,
    }

def run_dev_task_sync(project_name: str, task: str, want_preview: bool = True) -> dict:
    """Synchronous wrapper for CLI/tool_executor use."""
    return asyncio.run(run_dev_task(project_name, task, want_preview))

# ── Telegram-hook interface ───────────────────────────────────────────────────

async def run_dev_task_for_telegram(project_name: str, task: str) -> dict:
    """
    Run a dev task and return a dict shaped for Telegram delivery.
    screenshot_path will be sent as a photo by main_daemon.py.
    """
    result = await run_dev_task(project_name, task, want_preview=True)
    return {
        "text": result["summary"] if result["success"] else f"❌ Dev task failed:\n{result['summary']}",
        "screenshot_path": result.get("screenshot_path"),
        "success": result["success"],
        "patched_files": result.get("patched_files", []),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python dev_task_tool.py <project_name> <task>")
        print("       python dev_task_tool.py list")
        sys.exit(1)
    if sys.argv[1] == "list":
        print(list_projects())
    else:
        result = run_dev_task_sync(sys.argv[1], " ".join(sys.argv[2:]))
        print(result["summary"])
        if result.get("screenshot_path"):
            print(f"Screenshot: {result['screenshot_path']}")
