# -*- coding: utf-8 -*-
"""
Aria Obsidian-Native Memory Engine
----------------------------------
Completely replaces SQLite (aria_memory.db) with human-readable Obsidian Markdown notes.
The Obsidian Vault at D:/HERMES/AriaVault is the sole source of truth.

Handles:
1. Facts & Profile (Profile.md, System Facts.md)
2. Daily Conversations (Conversations/YYYY-MM/YYYY-MM-DD.md)
3. Todos & Task Management (Todos.md)
4. Reminders & Schedule (Reminders.md)
5. Quick Notes & Knowledge (Notes/)
6. Memory Triggers (Triggers/Memory Triggers.md)
7. Security Audit Log (Audit/Security Audit Log.md)
8. Agent Plans & Metrics (Plans/Agent Goals.md)
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger("obsidian_memory")

DEFAULT_VAULT_PATH = Path("D:/HERMES/AriaVault")


def get_vault_path() -> Path:
    """Resolve the active Obsidian vault directory."""
    env_path = os.getenv("OBSIDIAN_VAULT_PATH")
    if env_path:
        p = Path(env_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    appdata = os.getenv("APPDATA")
    if appdata:
        cfg = Path(appdata) / "obsidian" / "obsidian.json"
        if cfg.exists():
            try:
                with open(cfg, "r", encoding="utf-8") as f:
                    data = json.load(f)
                vaults = data.get("vaults", {})
                for _, vdata in vaults.items():
                    vpath = vdata.get("path")
                    if vpath:
                        p = Path(vpath)
                        p.mkdir(parents=True, exist_ok=True)
                        return p
            except Exception:
                pass

    DEFAULT_VAULT_PATH.mkdir(parents=True, exist_ok=True)
    return DEFAULT_VAULT_PATH


VAULT = get_vault_path()

# Paths to core notes in the vault
PROFILE_NOTE = VAULT / "Facts" / "Profile.md"
SYSTEM_FACTS_NOTE = VAULT / "Facts" / "System Facts.md"
TODOS_NOTE = VAULT / "Todos.md"
REMINDERS_NOTE = VAULT / "Reminders.md"
TRIGGERS_NOTE = VAULT / "Triggers" / "Memory Triggers.md"
AUDIT_NOTE = VAULT / "Audit" / "Security Audit Log.md"
PLANS_NOTE = VAULT / "Plans" / "Agent Goals.md"
CONVERSATIONS_DIR = VAULT / "Conversations"
NOTES_DIR = VAULT / "Notes"
METRICS_FILE = VAULT / "Facts" / "engine_metrics.json"

# In-memory facts cache for sub-millisecond retrieval
_facts_cache: Dict[str, str] = {}
_cache_loaded: bool = False
_facts_mtimes: Dict[Path, float] = {}

PROFILE_KEYS = {
    "user_name", "user_nickname", "preferred_language", "active_model_mode",
    "active_llm_model", "last_inference_engine", "last_opened_app",
    "user_timezone", "obsidian_connected"
}



def _ensure_vault_structure():
    """Ensure all core vault folders and notes exist with headers."""
    VAULT.mkdir(parents=True, exist_ok=True)
    (VAULT / "Facts").mkdir(parents=True, exist_ok=True)
    (VAULT / "Conversations").mkdir(parents=True, exist_ok=True)
    (VAULT / "Triggers").mkdir(parents=True, exist_ok=True)
    (VAULT / "Audit").mkdir(parents=True, exist_ok=True)
    (VAULT / "Plans").mkdir(parents=True, exist_ok=True)
    (VAULT / "Notes").mkdir(parents=True, exist_ok=True)

    if not TODOS_NOTE.exists():
        _init_todos_note()

    if not REMINDERS_NOTE.exists():
        _init_reminders_note()


def _init_todos_note():
    header = [
        "---",
        "title: Personal Todo List",
        "tags: [aria, todos, tasks]",
        f"updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "---",
        "",
        "# 📋 Personal Todo List",
        "",
        "> Managed by Aria AI. Say 'add ... to my todo list', or check tasks off directly in Obsidian.",
        "",
        "## ⏳ Pending Tasks",
        "",
        "## ✅ Completed Tasks",
        "",
        "---",
        "*Backlink:* [[00 - Home|🏠 Home]]",
    ]
    with open(TODOS_NOTE, "w", encoding="utf-8") as f:
        f.write("\n".join(header) + "\n")


def _init_reminders_note():
    header = [
        "---",
        "title: Personal Reminders & Schedule",
        "tags: [aria, reminders, schedule]",
        f"updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "---",
        "",
        "# ⏰ Personal Reminders",
        "",
        "> Reminders set via Aria Telegram or Voice ('remind me to ...').",
        "",
        "## 🔔 Active Reminders",
        "",
        "## 🔕 Dismissed Reminders",
        "",
        "---",
        "*Backlink:* [[00 - Home|🏠 Home]]",
    ]
    with open(REMINDERS_NOTE, "w", encoding="utf-8") as f:
        f.write("\n".join(header) + "\n")


# ── Facts & Profile API ─────────────────────────────────────────────────────

def _load_facts_from_disk():
    """Load facts from Profile.md and System Facts.md tables into cache."""
    global _facts_cache, _cache_loaded, _facts_mtimes
    _facts_cache.clear()

    for note_path in [PROFILE_NOTE, SYSTEM_FACTS_NOTE]:
        if not note_path.exists():
            continue
        try:
            _facts_mtimes[note_path] = note_path.stat().st_mtime
            with open(note_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = [x.strip() for x in line.split("|")]
                    if len(parts) >= 4 and parts[1] and parts[1] not in ("Key", ":---", "State Variable"):
                        k = parts[1].replace("*", "").replace("`", "").strip()
                        v = parts[2].replace("`", "").strip()
                        if k:
                            _facts_cache[k] = v
        except Exception as e:
            logger.warning(f"[Obsidian Memory] Failed reading facts from {note_path}: {e}")

    _cache_loaded = True


def _check_and_reload_facts():
    """Check if any facts file was modified in Obsidian externally, and reload cache if so."""
    global _cache_loaded, _facts_mtimes
    if not _cache_loaded:
        _load_facts_from_disk()
        return

    for note_path in [PROFILE_NOTE, SYSTEM_FACTS_NOTE]:
        if note_path.exists():
            try:
                curr_mtime = note_path.stat().st_mtime
                if curr_mtime > _facts_mtimes.get(note_path, 0):
                    _load_facts_from_disk()
                    return
            except Exception:
                pass


def get_fact(key: str) -> Optional[str]:
    """Retrieve a fact by key from Obsidian memory (fast cached lookup with auto-reload)."""
    _check_and_reload_facts()

    val = _facts_cache.get(key.strip())
    if not val or val == "None":
        return None
    return val


def get_all_facts() -> Dict[str, str]:
    """Return all known facts as a dictionary (auto-reloaded from Obsidian if edited)."""
    _check_and_reload_facts()
    return dict(_facts_cache)


def set_fact(key: str, value: Optional[str]):
    """Set or delete a fact, writing directly to Obsidian Markdown tables."""
    global _facts_cache, _cache_loaded
    if not _cache_loaded:
        _load_facts_from_disk()

    k = key.strip()
    if value is None:
        _facts_cache.pop(k, None)
    else:
        _facts_cache[k] = str(value).strip()

    # Determine target note
    target_note = PROFILE_NOTE if (k in PROFILE_KEYS or not k.startswith("ag_")) else SYSTEM_FACTS_NOTE
    _write_facts_note(target_note)


def _write_facts_note(note_path: Path):
    """Rewrite Profile.md or System Facts.md table with current cached facts."""
    note_path.parent.mkdir(parents=True, exist_ok=True)
    is_profile = (note_path == PROFILE_NOTE)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = "User Profile & Memory Facts" if is_profile else "System State & Orchestrator Facts"
    heading = "# 👤 User Profile & Core Facts" if is_profile else "# ⚙️ System Facts & Session Flags"
    col1 = "Key" if is_profile else "State Variable"

    lines = [
        "---",
        f"title: {title}",
        f"tags: [aria, memory, {'profile' if is_profile else 'system'}]",
        f"updated: {now_str}",
        "---",
        "",
        heading,
        "",
        "> Synced with Aria AI. Managed automatically.",
        "",
        f"| {col1} | Value | Last Updated |",
        "| :--- | :--- | :--- |",
    ]

    for k, v in sorted(_facts_cache.items()):
        belongs_here = (k in PROFILE_KEYS or not k.startswith("ag_")) if is_profile else (k not in PROFILE_KEYS and k.startswith("ag_"))
        if belongs_here:
            clean_v = str(v).replace("\n", " ")
            lines.append(f"| **`{k}`** | `{clean_v}` | `{now_str}` |")

    lines.append("")
    lines.append("---")
    lines.append("*Backlink:* [[00 - Home|🏠 Home]]")

    try:
        with open(note_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        logger.warning(f"[Obsidian Memory] Failed writing {note_path}: {e}")


# ── Conversation History API ────────────────────────────────────────────────

def add_message(user_id: int, role: str, message: str):
    """Directly append a user/assistant message to today's daily log in Obsidian."""
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    month_str = today.strftime("%Y-%m")
    time_str = today.strftime("%H:%M:%S")

    month_dir = CONVERSATIONS_DIR / month_str
    month_dir.mkdir(parents=True, exist_ok=True)
    note_file = month_dir / f"{date_str}.md"

    if not note_file.exists():
        header = [
            "---",
            f"title: Conversation Log — {date_str}",
            "tags: [aria, conversation, daily-log]",
            f"date: {date_str}",
            "---",
            "",
            f"# 💬 Conversation Log — {date_str}",
            "",
            "---",
            "",
        ]
        with open(note_file, "w", encoding="utf-8") as f:
            f.write("\n".join(header))

    entry = []
    if role.lower() == "user":
        entry.append(f"\n### 🧑 **User** `[{time_str}]`\n> {message.replace(chr(10), chr(10) + '> ')}\n")
    else:
        entry.append(f"\n### 🤖 **Aria** `[{time_str}]`\n{message}\n\n---\n")

    try:
        with open(note_file, "a", encoding="utf-8") as f:
            f.write("\n".join(entry))
    except Exception as e:
        logger.warning(f"[Obsidian Memory] Failed to append message to {note_file}: {e}")


def get_recent_history(user_id: int, limit: int = 6) -> str:
    """Retrieve the recent conversation turns directly from today's Obsidian daily log."""
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    month_str = today.strftime("%Y-%m")
    note_file = CONVERSATIONS_DIR / month_str / f"{date_str}.md"

    if not note_file.exists():
        return "No prior conversation history today."

    try:
        with open(note_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        blocks = content.split("### ")
        history_items = []
        for b in blocks:
            b_clean = b.strip()
            if b_clean.startswith("🧑 **User**"):
                lines = b_clean.splitlines()
                text = " ".join(l.lstrip("> ").strip() for l in lines[1:] if l.strip())
                if text:
                    history_items.append(f"User: {text}")
            elif b_clean.startswith("🤖 **Aria**"):
                lines = b_clean.splitlines()
                text = " ".join(l.strip() for l in lines[1:] if l.strip() and l.strip() != "---")
                if text:
                    history_items.append(f"Aria: {text}")

        if not history_items:
            return "No prior conversation history."

        return "\n".join(history_items[-limit:])
    except Exception as e:
        logger.warning(f"[Obsidian Memory] Failed reading history: {e}")
        return "No prior conversation history."


# ── Personal Assistant: Todos API ───────────────────────────────────────────

def add_todo(task_text: str) -> str:
    """Add a new task to Todos.md in Obsidian."""
    _ensure_vault_structure()
    clean_task = task_text.strip().lstrip("- [ ]").strip()
    if not clean_task:
        return "⚠️ Task description cannot be empty."

    try:
        with open(TODOS_NOTE, "r", encoding="utf-8") as f:
            content = f.read()

        line_to_add = f"- [ ] {clean_task}\n"
        if "## ⏳ Pending Tasks" in content:
            new_content = content.replace("## ⏳ Pending Tasks", f"## ⏳ Pending Tasks\n{line_to_add}", 1)
        else:
            new_content = content + f"\n## ⏳ Pending Tasks\n{line_to_add}\n"

        with open(TODOS_NOTE, "w", encoding="utf-8") as f:
            f.write(new_content)

        return f"✅ **Added to your Obsidian Todo list:**\n• `- [ ]` {clean_task}"
    except Exception as e:
        return f"❌ Failed to add todo: {e}"


def get_todos(status_filter: str = "pending") -> List[Dict[str, str]]:
    """
    Get todos from Todos.md.
    status_filter: 'all', 'pending', or 'completed'
    """
    _ensure_vault_structure()
    todos = []
    if not TODOS_NOTE.exists():
        return todos

    try:
        with open(TODOS_NOTE, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str.startswith("- [ ]"):
                    t_text = line_str[5:].strip()
                    if status_filter in ("all", "pending"):
                        todos.append({"task": t_text, "completed": False, "raw": line_str})
                elif line_str.startswith("- [x]") or line_str.startswith("- [X]"):
                    t_text = line_str[5:].strip()
                    if status_filter in ("all", "completed"):
                        todos.append({"task": t_text, "completed": True, "raw": line_str})
    except Exception as e:
        logger.warning(f"[Obsidian Memory] Failed reading todos: {e}")

    return todos


def complete_todo(task_query: str) -> str:
    """Mark a matching pending task as completed in Todos.md."""
    _ensure_vault_structure()
    q = task_query.lower().strip()
    if not TODOS_NOTE.exists():
        return "📂 No todo list found."

    try:
        with open(TODOS_NOTE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        matched_line_idx = None
        matched_task_text = None

        for idx, line in enumerate(lines):
            l_strip = line.strip()
            if l_strip.startswith("- [ ]") and q in l_strip.lower():
                matched_line_idx = idx
                matched_task_text = l_strip[5:].strip()
                break

        if matched_line_idx is None:
            return f"🔍 No pending task found matching **'{task_query}'**."

        # Remove pending line
        lines.pop(matched_line_idx)
        done_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        completed_line = f"- [x] {matched_task_text} *(completed {done_timestamp})*\n"

        # Insert under Completed Tasks
        completed_header_idx = None
        for idx, line in enumerate(lines):
            if "## ✅ Completed Tasks" in line:
                completed_header_idx = idx
                break

        if completed_header_idx is not None:
            lines.insert(completed_header_idx + 1, completed_line)
        else:
            lines.append(f"\n## ✅ Completed Tasks\n{completed_line}")

        with open(TODOS_NOTE, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return f"🎉 **Task Completed!**\n• `- [x]` {matched_task_text}"
    except Exception as e:
        return f"❌ Failed to complete todo: {e}"


def remove_todo(task_query: str) -> str:
    """Remove a task entirely from Todos.md."""
    _ensure_vault_structure()
    q = task_query.lower().strip()
    try:
        with open(TODOS_NOTE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        removed = None
        for line in lines:
            if ("- [ ]" in line or "- [x]" in line) and q in line.lower() and not removed:
                removed = line.strip()
            else:
                new_lines.append(line)

        if not removed:
            return f"🔍 No task found matching **'{task_query}'** to delete."

        with open(TODOS_NOTE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        return f"🗑️ **Deleted from Obsidian Todo list:**\n• {removed}"
    except Exception as e:
        return f"❌ Failed to delete todo: {e}"


# ── Personal Assistant: Reminders API ───────────────────────────────────────

def add_reminder(reminder_text: str, due_time: Optional[str] = None) -> str:
    """Add a structured reminder to Reminders.md in Obsidian."""
    _ensure_vault_structure()
    clean_text = reminder_text.strip()
    time_prefix = f"`[{due_time}]` " if due_time else f"`[{datetime.now().strftime('%Y-%m-%d %H:%M')}]` "
    reminder_line = f"- [ ] {time_prefix}{clean_text}\n"

    try:
        with open(REMINDERS_NOTE, "r", encoding="utf-8") as f:
            content = f.read()

        if "## 🔔 Active Reminders" in content:
            new_content = content.replace("## 🔔 Active Reminders", f"## 🔔 Active Reminders\n{reminder_line}", 1)
        else:
            new_content = content + f"\n## 🔔 Active Reminders\n{reminder_line}\n"

        with open(REMINDERS_NOTE, "w", encoding="utf-8") as f:
            f.write(new_content)

        return f"⏰ **Reminder Saved to Obsidian!**\n• {reminder_line.strip()}"
    except Exception as e:
        return f"❌ Failed to save reminder: {e}"


def get_reminders(active_only: bool = True) -> List[Dict[str, str]]:
    """Retrieve reminders from Reminders.md."""
    _ensure_vault_structure()
    reminders = []
    if not REMINDERS_NOTE.exists():
        return reminders

    try:
        with open(REMINDERS_NOTE, "r", encoding="utf-8") as f:
            for line in f:
                l = line.strip()
                if l.startswith("- [ ]"):
                    reminders.append({"text": l[5:].strip(), "active": True})
                elif not active_only and (l.startswith("- [x]") or l.startswith("- [X]")):
                    reminders.append({"text": l[5:].strip(), "active": False})
    except Exception as e:
        logger.warning(f"[Obsidian Memory] Failed reading reminders: {e}")

    return reminders


def dismiss_reminder(query: str) -> str:
    """Dismiss a reminder in Reminders.md."""
    _ensure_vault_structure()
    q = query.lower().strip()
    try:
        with open(REMINDERS_NOTE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        matched = None
        for idx, line in enumerate(lines):
            if line.strip().startswith("- [ ]") and q in line.lower():
                matched = line.strip()[5:].strip()
                lines.pop(idx)
                break

        if not matched:
            return f"🔍 No active reminder found matching **'{query}'**."

        dismissed_line = f"- [x] {matched} *(dismissed {datetime.now().strftime('%Y-%m-%d %H:%M')})*\n"
        d_idx = None
        for idx, line in enumerate(lines):
            if "## 🔕 Dismissed Reminders" in line:
                d_idx = idx
                break
        if d_idx is not None:
            lines.insert(d_idx + 1, dismissed_line)
        else:
            lines.append(f"\n## 🔕 Dismissed Reminders\n{dismissed_line}")

        with open(REMINDERS_NOTE, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return f"🔕 **Dismissed Reminder:**\n• {matched}"
    except Exception as e:
        return f"❌ Failed to dismiss reminder: {e}"


# ── Quick Notes & Knowledge API ─────────────────────────────────────────────

def save_note(title: str, content: str) -> str:
    """Save or append a note directly into Notes/{title}.md in Obsidian."""
    _ensure_vault_structure()
    clean_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip() or "Quick Note"
    note_path = NOTES_DIR / f"{clean_title}.md"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not note_path.exists():
        doc = [
            "---",
            f"title: {clean_title}",
            "tags: [aria, personal, note]",
            f"created: {now_str}",
            "---",
            "",
            f"# 📝 {clean_title}",
            "",
            content.strip(),
            "",
            "---",
            "*Backlink:* [[00 - Home|🏠 Home]]",
        ]
        with open(note_path, "w", encoding="utf-8") as f:
            f.write("\n".join(doc) + "\n")
        return f"📝 **Created note in Obsidian:** `Notes/{clean_title}.md`"
    else:
        with open(note_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n### Updated `[{now_str}]`\n{content.strip()}\n")
        return f"📝 **Updated note in Obsidian:** `Notes/{clean_title}.md`"


def read_note(note_name: str) -> Optional[str]:
    """Read a note from anywhere in the Obsidian vault."""
    clean = note_name.strip().lower()
    if clean.endswith(".md"):
        clean = clean[:-3]

    for md_file in VAULT.rglob("*.md"):
        if md_file.stem.lower() == clean or clean in md_file.stem.lower():
            try:
                with open(md_file, "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            except Exception as e:
                return f"❌ Error reading note: {e}"
    return None


def search_vault(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Search all Markdown files in the Obsidian vault."""
    q_lower = query.lower()
    results = []
    for md_file in VAULT.rglob("*.md"):
        try:
            with open(md_file, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            if q_lower in text.lower():
                lines = [l.strip() for l in text.splitlines() if q_lower in l.lower() and not l.startswith("---")]
                snippet = " ... ".join(lines[:3]) if lines else text[:200]
                results.append({
                    "note": md_file.name,
                    "rel_path": str(md_file.relative_to(VAULT)),
                    "snippet": snippet[:250],
                    "path": str(md_file.resolve()),
                })
                if len(results) >= max_results:
                    break
        except Exception:
            continue
    return results


# ── Triggers API ────────────────────────────────────────────────────────────

def set_trigger(user_id: int, trigger_phrase: str, payload: str):
    """Save proactive trigger to Triggers/Memory Triggers.md."""
    _ensure_vault_structure()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    phrase = trigger_phrase.strip().lower()
    pay = payload.strip()

    try:
        if not TRIGGERS_NOTE.exists():
            lines = [
                "---", "title: Proactive Memory Triggers", "tags: [aria, triggers]", "---",
                "", "# ⚡ Proactive Memory Triggers", "",
                "| Trigger Phrase | Configured Response / Action | Created At |",
                "| :--- | :--- | :--- |",
            ]
        else:
            with open(TRIGGERS_NOTE, "r", encoding="utf-8") as f:
                lines = [l.rstrip("\n") for l in f]

        lines.append(f"| **`{phrase}`** | {pay} | `{now_str}` |")
        with open(TRIGGERS_NOTE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        logger.warning(f"[Obsidian Memory] Failed writing trigger: {e}")


def get_triggers(user_id: int) -> List[Dict[str, str]]:
    """Get all proactive triggers from Triggers/Memory Triggers.md."""
    triggers = []
    if not TRIGGERS_NOTE.exists():
        return triggers

    try:
        with open(TRIGGERS_NOTE, "r", encoding="utf-8") as f:
            for line in f:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 4 and parts[1] and parts[1] not in ("Trigger Phrase", ":---", "ID"):
                    p = parts[1].replace("*", "").replace("`", "").strip()
                    pay = parts[2].strip()
                    if p and pay:
                        triggers.append({"trigger_phrase": p, "payload": pay})
    except Exception as e:
        logger.warning(f"[Obsidian Memory] Failed reading triggers: {e}")

    return triggers


# ── Audit Log API ───────────────────────────────────────────────────────────

def log_audit(user_id: int, action: str, risk: str, summary: str, status: str, output: Optional[str] = None):
    """Append security and tool executions directly to Audit/Security Audit Log.md."""
    _ensure_vault_structure()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    clean_summary = (summary or "").replace("|", "\\|").replace("\n", " ")

    risk_badge = f"`{risk}`"
    if "HIGH" in risk:
        risk_badge = f"🔴 **{risk}**"
    elif "MEDIUM" in risk:
        risk_badge = f"🟡 **{risk}**"
    elif "LOW" in risk or "SAFE" in risk:
        risk_badge = f"🟢 **{risk}**"

    status_icon = "✅" if status in ("SUCCESS", "approved", "done") else "❌"
    row = f"| `{now_str}` | **`{action}`** | {risk_badge} | {status_icon} `{status}` | {clean_summary} |\n"

    try:
        if not AUDIT_NOTE.exists():
            header = [
                "---", "title: Security Audit Log", "tags: [aria, audit]", "---",
                "", "# 🛡️ Security & Tool Audit Log", "",
                "| Timestamp | Action | Risk Level | Status | Summary |",
                "| :--- | :--- | :--- | :--- | :--- |",
                row,
            ]
            with open(AUDIT_NOTE, "w", encoding="utf-8") as f:
                f.write("\n".join(header))
        else:
            with open(AUDIT_NOTE, "a", encoding="utf-8") as f:
                f.write(row)
    except Exception as e:
        logger.warning(f"[Obsidian Memory] Failed logging audit: {e}")


# ── Engine Metrics & Plans API ──────────────────────────────────────────────

def get_engine_metric(provider: str) -> Optional[dict]:
    if not METRICS_FILE.exists():
        return None
    try:
        with open(METRICS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(provider)
    except Exception:
        return None


def update_engine_metric(provider: str, tokens: int, status: int, latency: float, failures: int, cooldown: float):
    data = {}
    if METRICS_FILE.exists():
        try:
            with open(METRICS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    curr = data.get(provider, {"tokens_consumed": 0})
    curr["tokens_consumed"] = curr.get("tokens_consumed", 0) + tokens
    curr["status_code"] = status
    curr["latency"] = latency
    curr["consecutive_failures"] = failures
    curr["cooldown_timestamp"] = cooldown
    data[provider] = curr

    try:
        METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(METRICS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"[Obsidian Memory] Failed saving engine metric: {e}")


def set_agent_plan(goal_id: str, plan_json: str, step_states: str, execution_history: str):
    _ensure_vault_structure()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = [
        f"\n## 🎯 Goal: `{goal_id}` `[{now_str}]`",
        f"- **Plan:**\n```json\n{plan_json}\n```",
        f"- **States:** `{step_states}`",
        f"- **History:** `{execution_history}`",
        "\n---",
    ]
    try:
        with open(PLANS_NOTE, "a", encoding="utf-8") as f:
            f.write("\n".join(entry) + "\n")
    except Exception as e:
        logger.warning(f"[Obsidian Memory] Failed saving agent plan: {e}")


def get_agent_plan(goal_id: str) -> Optional[dict]:
    # Returns basic dictionary placeholder for goal state
    return {"goal_id": goal_id, "status": "stored_in_obsidian"}


# Initialize vault structure and cache on import
_ensure_vault_structure()
_load_facts_from_disk()
