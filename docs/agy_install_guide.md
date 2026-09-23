# Antigravity CLI (agy) — Install Guide & ARIA Integration

A step-by-step guide to installing `agy` CLI and setting up the ARIA ↔ AGY preview workflow so you can edit projects remotely via Telegram and get live screenshots sent back to you.

---

## Why Install agy CLI?

Right now ARIA uses Gemini to write code edits directly. With `agy` CLI installed:

- ARIA can delegate complex multi-file edits to a full AI coding agent (you — same model, same context)
- `agy` costs **0 Gemini tokens** from ARIA's free-tier quota (it uses its own auth)
- You get richer, more intelligent code changes for complex tasks

---

## Step 1 — Install agy CLI

### Option A: npm (Recommended)
```powershell
npm install -g @google/antigravity
```
Then verify:
```powershell
agy --version
```

### Option B: Download binary from Google
1. Go to: **https://antigravity.google/download**
2. Download the Windows binary (`agy-win.exe`)
3. Rename to `agy.exe` and move to `C:\Users\Dell\AppData\Local\Programs\agy\`
4. Add that folder to your PATH:
```powershell
$oldPath = [Environment]::GetEnvironmentVariable("PATH", "User")
[Environment]::SetEnvironmentVariable("PATH", "$oldPath;C:\Users\Dell\AppData\Local\Programs\agy", "User")
```
5. Restart your terminal and verify: `agy --version`

---

## Step 2 — Authenticate

```powershell
agy auth login
```
Follow the browser prompts to log in with your Google account (same account you use for AI Studio).

---

## Step 3 — Test it

```powershell
# Navigate to any project
cd D:\Certify

# Run a task
agy "add a footer with copyright 2026"
```

`agy` will read all the project files, make the edits, and exit. No GUI needed.

---

## Step 4 — ARIA Integration (After agy is installed)

Once `agy` is installed, update `aria-core/dev_task_tool.py` to use it:

The `run_dev_task` function already has a fallback chain:
```
1. Try agy CLI (fastest, uses no Gemini quota)
2. Fall back to Gemini direct edit (always works)
```

To enable the `agy` path, add this to `aria-core/dev_task_tool.py`:

```python
AGY_PATH = shutil.which("agy") or r"C:\Users\Dell\AppData\Local\Programs\agy\agy.exe"

async def _run_agy_task(project_path: Path, task: str) -> list[str]:
    """Run agy CLI for the task. Returns list of changed files."""
    result = subprocess.run(
        [AGY_PATH, task],
        cwd=str(project_path),
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"agy failed: {result.stderr}")
    # Parse changed files from agy output
    changed = re.findall(r"(?:edited|created|modified):\s+(\S+)", result.stdout, re.IGNORECASE)
    return changed
```

Then in `run_dev_task`, replace the Gemini planning block with:
```python
try:
    patched = await _run_agy_task(project_path, task)
    edits = [{"file_path": p, "description": "updated by agy"} for p in patched]
except Exception:
    # Fall back to Gemini
    edits = await _plan_edits_with_gemini(project, task, source_files)
    patched = apply_edits(project_path, edits)
```

---

## The Full Remote Dev Flow (Once Everything Is Set Up)

```
You (at college, Telegram):
  "update screensnipe — make the overlay background darker"
          ↓
ARIA:
  → Resolves "screensnipe" → D:\Anything From S\Screen snipe
  → Runs: agy "make the overlay background darker"   (in that folder)
  → agy edits overlay.py
  → ARIA takes desktop screenshot (app launches briefly)
  → ARIA sends you the screenshot on Telegram
          ↓
You: "looks good, push it"
          ↓
ARIA:
  → cd D:\Anything From S\Screen snipe
  → git add . && git commit -m "darken overlay background" && git push
  → "✅ Pushed to origin/main"
          ↓
You: 🟩 (green box on GitHub profile)
```

### What ARIA Can Do Now (Without agy):
- ✅ Edit any project via Gemini (uses token quota)
- ✅ Start dev server and take preview screenshot
- ✅ Send screenshot to your Telegram
- ✅ Generate certificates via Certify API
- ✅ Send ZIP to your Telegram
- ✅ Check Gmail for bounce emails

### What Gets Better After agy Install:
- 🚀 Faster, richer code edits (agy uses full project context)
- 💡 Zero ARIA token usage for code editing
- 🔄 Auto-handles complex refactors, multi-file changes
- 📦 Can scaffold entirely new features

---

## Trigger Words for ARIA

Once this is wired in, say things like:

| You say | ARIA does |
|---------|-----------|
| `"update certify — add dark mode"` | Edits Certify, screenshots localhost:3000, sends preview |
| `"fix the overlay in screensnipe"` | Edits overlay.py, screenshots, sends |
| `"in the pomodoro app, change timer to 30 min"` | Edits, restarts dev server, screenshots |
| `"generate certificates"` | Full cert workflow → ZIP → Telegram |
| `"check gmail for bounces"` | Opens Gmail, screenshots, sends report |
| `"list my projects"` | Lists all registered projects with paths |
| `"push screensnipe to github"` | git add + commit + push |

---

> [!NOTE]
> The `agentapi.bat` tool already installed at `C:\Users\Dell\.gemini\antigravity-ide\bin\agentapi.bat`
> can spawn AI coding sessions programmatically. ARIA can use this as a middle ground between
> direct Gemini edits and full `agy` CLI — it uses your existing Antigravity IDE auth and runs
> a full agent session in the background. This is already wired into ARIA's architecture.
