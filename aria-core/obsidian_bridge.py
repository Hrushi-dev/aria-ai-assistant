# -*- coding: utf-8 -*-
"""
Aria Obsidian Bridge
--------------------
Connects Aria's SQLite memory store (aria_memory.db) with an Obsidian Vault.
Provides:
1. Full export of facts, conversations, triggers, audit logs, and agent plans to Obsidian Markdown notes.
2. Real-time sync hooks when new messages, facts, or triggers are added.
3. Vault discovery from %APPDATA%/obsidian/obsidian.json or OBSIDIAN_VAULT_PATH.
4. Vault note search and retrieval for Aria tools.
"""

import os
import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

logger = logging.getLogger("obsidian_bridge")

DEFAULT_VAULT_PATH = Path("D:/HERMES/AriaVault")
DB_PATH = Path(__file__).parent / "aria_memory.db"


def get_obsidian_config_path() -> Optional[Path]:
    """Return path to obsidian.json in AppData/Roaming if it exists."""
    appdata = os.getenv("APPDATA")
    if appdata:
        cfg = Path(appdata) / "obsidian" / "obsidian.json"
        if cfg.exists():
            return cfg
    return None


def get_vault_path() -> Path:
    """
    Resolve the active Obsidian vault directory.
    Priority:
    1. OBSIDIAN_VAULT_PATH environment variable (from .env or OS)
    2. Registered vault in %APPDATA%/obsidian/obsidian.json
    3. Default to D:/HERMES/AriaVault
    """
    env_path = os.getenv("OBSIDIAN_VAULT_PATH")
    if env_path:
        p = Path(env_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    cfg_path = get_obsidian_config_path()
    if cfg_path:
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            vaults = data.get("vaults", {})
            for _, vdata in vaults.items():
                vpath = vdata.get("path")
                if vpath:
                    p = Path(vpath)
                    p.mkdir(parents=True, exist_ok=True)
                    return p
        except Exception as e:
            logger.warning(f"[Obsidian Bridge] Could not parse obsidian.json: {e}")

    DEFAULT_VAULT_PATH.mkdir(parents=True, exist_ok=True)
    return DEFAULT_VAULT_PATH


def register_vault_in_obsidian(vault_path: Path):
    """
    Ensure the vault path is registered in %APPDATA%/obsidian/obsidian.json
    so Obsidian opens it by default without manual browsing.
    """
    cfg_path = get_obsidian_config_path()
    if not cfg_path:
        appdata = os.getenv("APPDATA")
        if appdata:
            cfg_path = Path(appdata) / "obsidian" / "obsidian.json"
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            return

    try:
        data = {"vaults": {}}
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)

        vaults = data.setdefault("vaults", {})
        vault_str = str(vault_path.resolve())

        # Check if already present
        already_registered = any(v.get("path") == vault_str for v in vaults.values())
        if not already_registered:
            import hashlib
            vault_id = hashlib.md5(vault_str.encode("utf-8")).hexdigest()[:16]
            vaults[vault_id] = {
                "path": vault_str,
                "ts": int(datetime.now().timestamp() * 1000),
                "open": True,
            }
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info(f"[Obsidian Bridge] Registered vault '{vault_str}' in obsidian.json")
    except Exception as e:
        logger.warning(f"[Obsidian Bridge] Failed to update obsidian.json: {e}")


def export_all_memory(vault_path: Optional[Path] = None) -> Dict[str, int]:
    """
    Export all data from aria_memory.db into organized Obsidian Markdown notes.
    Returns stats dict with counts of exported items.
    """
    if not vault_path:
        vault_path = get_vault_path()

    vault_path.mkdir(parents=True, exist_ok=True)
    register_vault_in_obsidian(vault_path)

    stats = {
        "facts": 0,
        "conversations": 0,
        "triggers": 0,
        "audit_logs": 0,
        "plans": 0,
    }

    if not DB_PATH.exists():
        logger.error(f"[Obsidian Bridge] Database not found at {DB_PATH}")
        return stats

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. Facts & Profile
    try:
        cursor.execute("SELECT key, value, updated_at FROM facts ORDER BY key ASC")
        facts = cursor.fetchall()
        stats["facts"] = len(facts)
        _export_facts(vault_path, facts)
    except Exception as e:
        logger.warning(f"[Obsidian Bridge] Error exporting facts: {e}")

    # 2. Conversation History
    try:
        cursor.execute("SELECT id, user_id, role, message, timestamp FROM history ORDER BY id ASC")
        history = cursor.fetchall()
        stats["conversations"] = len(history)
        _export_history(vault_path, history)
    except Exception as e:
        logger.warning(f"[Obsidian Bridge] Error exporting history: {e}")

    # 3. Triggers
    try:
        cursor.execute("SELECT id, trigger_phrase, payload, created_at FROM triggers ORDER BY id ASC")
        triggers = cursor.fetchall()
        stats["triggers"] = len(triggers)
        _export_triggers(vault_path, triggers)
    except Exception as e:
        logger.warning(f"[Obsidian Bridge] Error exporting triggers: {e}")

    # 4. Security Audit Log
    try:
        cursor.execute("SELECT id, user_id, action, risk_level, summary, status, output, timestamp FROM audit_log ORDER BY id ASC")
        audit_rows = cursor.fetchall()
        stats["audit_logs"] = len(audit_rows)
        _export_audit(vault_path, audit_rows)
    except Exception as e:
        logger.warning(f"[Obsidian Bridge] Error exporting audit logs: {e}")

    # 5. Agent Plans
    try:
        cursor.execute("SELECT goal_id, plan_json, step_states, execution_history, updated_at FROM agent_plans ORDER BY updated_at DESC")
        plans = cursor.fetchall()
        stats["plans"] = len(plans)
        _export_plans(vault_path, plans)
    except Exception as e:
        logger.warning(f"[Obsidian Bridge] Error exporting plans: {e}")

    conn.close()

    # 6. Master Index / Home Note
    _generate_home_note(vault_path, stats)

    logger.info(f"[Obsidian Bridge] Memory exported successfully: {stats}")
    return stats


def _export_facts(vault_path: Path, facts: list):
    """Write Facts/Profile.md and Facts/System Facts.md."""
    facts_dir = vault_path / "Facts"
    facts_dir.mkdir(parents=True, exist_ok=True)

    profile_keys = {"user_name", "user_nickname", "preferred_language", "active_model_mode", "user_timezone"}
    profile_facts = []
    system_facts = []

    for f in facts:
        k = f["key"]
        v = f["value"]
        up = f["updated_at"]
        if k in profile_keys or not k.startswith("ag_"):
            profile_facts.append((k, v, up))
        else:
            system_facts.append((k, v, up))

    # Profile Note
    p_content = [
        "---",
        "title: User Profile & Memory Facts",
        "tags: [aria, memory, profile]",
        f"updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "---",
        "",
        "# 👤 User Profile & Core Facts",
        "",
        "> These facts are remembered by Aria across all sessions and voice/Telegram interactions.",
        "",
        "| Key | Value | Last Updated |",
        "| :--- | :--- | :--- |",
    ]
    for k, v, up in profile_facts:
        p_content.append(f"| **`{k}`** | {v} | `{up}` |")
    p_content.append("")
    p_content.append("---")
    p_content.append("*Backlink:* [[00 - Home|🏠 Home]] • [[System Facts|⚙️ System Facts]]")

    with open(facts_dir / "Profile.md", "w", encoding="utf-8") as f:
        f.write("\n".join(p_content))

    # System Facts Note
    s_content = [
        "---",
        "title: System State & Orchestrator Facts",
        "tags: [aria, system, state]",
        f"updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "---",
        "",
        "# ⚙️ System Facts & Session Flags",
        "",
        "| State Variable | Value | Last Updated |",
        "| :--- | :--- | :--- |",
    ]
    for k, v, up in system_facts:
        val_str = str(v).replace("\n", " ")
        if len(val_str) > 60:
            val_str = val_str[:57] + "..."
        s_content.append(f"| **`{k}`** | `{val_str}` | `{up}` |")
    s_content.append("")
    s_content.append("---")
    s_content.append("*Backlink:* [[00 - Home|🏠 Home]] • [[Profile|👤 Profile]]")

    with open(facts_dir / "System Facts.md", "w", encoding="utf-8") as f:
        f.write("\n".join(s_content))


def _export_history(vault_path: Path, history: list):
    """Group conversation history by date and write into Conversations/YYYY-MM/YYYY-MM-DD.md."""
    conv_dir = vault_path / "Conversations"
    conv_dir.mkdir(parents=True, exist_ok=True)

    grouped: Dict[str, list] = {}
    for row in history:
        ts = row["timestamp"] or "2026-08-14 00:00:00"
        try:
            date_part = ts.split(" ")[0]
        except Exception:
            date_part = "2026-08-14"
        grouped.setdefault(date_part, []).append(row)

    for date_str, msgs in grouped.items():
        try:
            year_month = date_str[:7]
        except Exception:
            year_month = "2026-08"

        month_dir = conv_dir / year_month
        month_dir.mkdir(parents=True, exist_ok=True)

        lines = [
            "---",
            f"title: Conversation Log — {date_str}",
            "tags: [aria, conversation, daily-log]",
            f"date: {date_str}",
            f"message_count: {len(msgs)}",
            "---",
            "",
            f"# 💬 Conversation Log — {date_str}",
            "",
            f"> Recorded {len(msgs)} messages between User and Aria.",
            "",
            "---",
            "",
        ]

        for m in msgs:
            role = m["role"]
            text = m["message"]
            m_time = m["timestamp"].split(" ")[-1] if " " in (m["timestamp"] or "") else ""

            if role == "user":
                lines.append(f"### 🧑 **User** `[{m_time}]`")
                lines.append(f"> {text.replace(chr(10), chr(10) + '> ')}")
                lines.append("")
            else:
                lines.append(f"### 🤖 **Aria** `[{m_time}]`")
                lines.append(f"{text}")
                lines.append("")
                lines.append("---")
                lines.append("")

        lines.append("*Backlinks:* [[00 - Home|🏠 Home]] • [[Profile|👤 Profile]]")

        note_file = month_dir / f"{date_str}.md"
        with open(note_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))


def _export_triggers(vault_path: Path, triggers: list):
    """Write Triggers/Memory Triggers.md."""
    trig_dir = vault_path / "Triggers"
    trig_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "---",
        "title: Proactive Memory Triggers",
        "tags: [aria, memory, triggers]",
        f"updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "---",
        "",
        "# ⚡ Proactive Memory Triggers",
        "",
        "> Whenever you say any of the trigger phrases, Aria automatically recalls and executes the associated payload.",
        "",
        "| ID | Trigger Phrase | Configured Response / Payload | Created At |",
        "| :--- | :--- | :--- | :--- |",
    ]

    for t in triggers:
        tid = t["id"]
        phrase = t["trigger_phrase"]
        payload = t["payload"]
        created = t["created_at"]
        lines.append(f"| {tid} | **`{phrase}`** | {payload} | `{created}` |")

    lines.append("")
    lines.append("---")
    lines.append("*Backlink:* [[00 - Home|🏠 Home]]")

    with open(trig_dir / "Memory Triggers.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _export_audit(vault_path: Path, audit_rows: list):
    """Write Audit/Security Audit Log.md."""
    audit_dir = vault_path / "Audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "---",
        "title: Security & Tool Audit Log",
        "tags: [aria, security, audit]",
        f"updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"total_records: {len(audit_rows)}",
        "---",
        "",
        "# 🛡️ Security & Tool Audit Log",
        "",
        "> Chronological record of tools, commands, and security validations performed by Aria.",
        "",
        "| Timestamp | Action | Risk Level | Status | Summary |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for row in reversed(audit_rows):
        ts = row["timestamp"]
        act = row["action"]
        risk = row["risk_level"]
        status = row["status"]
        summary = (row["summary"] or "").replace("|", "\\|").replace("\n", " ")
        if len(summary) > 80:
            summary = summary[:77] + "..."

        risk_badge = f"`{risk}`"
        if risk in ("HIGH", "HIGH_RISK"):
            risk_badge = f"🔴 **{risk}**"
        elif risk in ("MEDIUM", "MEDIUM_RISK"):
            risk_badge = f"🟡 **{risk}**"
        elif risk in ("LOW", "SAFE"):
            risk_badge = f"🟢 **{risk}**"

        status_icon = "✅" if status in ("SUCCESS", "approved", "done") else "❌"

        lines.append(f"| `{ts}` | **`{act}`** | {risk_badge} | {status_icon} `{status}` | {summary} |")

    lines.append("")
    lines.append("---")
    lines.append("*Backlink:* [[00 - Home|🏠 Home]]")

    with open(audit_dir / "Security Audit Log.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _export_plans(vault_path: Path, plans: list):
    """Write Plans/Agent Goals.md."""
    plans_dir = vault_path / "Plans"
    plans_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "---",
        "title: Autonomous Agent Plans & Goals",
        "tags: [aria, agent, plans]",
        f"updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "---",
        "",
        "# 🎯 Autonomous Agent Goals & Plans",
        "",
        "> High-level tasks, structured plans, and execution states generated by Aria Planner.",
        "",
    ]

    for p in plans:
        gid = p["goal_id"]
        up = p["updated_at"]
        raw_plan = p["plan_json"]
        try:
            plan_obj = json.loads(raw_plan)
            goal_desc = plan_obj.get("goal_description", gid)
            steps = plan_obj.get("steps", [])
        except Exception:
            goal_desc = gid
            steps = []

        lines.append(f"## 📋 Goal: {goal_desc}")
        lines.append(f"- **Goal ID:** `{gid}`")
        lines.append(f"- **Last Updated:** `{up}`")
        if steps:
            lines.append("### Execution Steps:")
            for idx, st in enumerate(steps, 1):
                tool = st.get("tool", "unknown")
                desc = st.get("description", "")
                risk = st.get("risk", "LOW")
                lines.append(f"{idx}. `[{risk}]` **{tool}**: {desc}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("*Backlink:* [[00 - Home|🏠 Home]]")

    with open(plans_dir / "Agent Goals.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _generate_home_note(vault_path: Path, stats: dict):
    """Generate 00 - Home.md as the entry dashboard in Obsidian."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content = [
        "---",
        "title: Aria AI Assistant — Memory Vault",
        "tags: [aria, dashboard, home]",
        f"created: {now_str}",
        "---",
        "",
        "# 🌌 Aria AI — Second Brain Vault",
        "",
        f"> **Welcome to your Aria Obsidian Memory Vault!**  ",
        f"> This vault is synced with Aria's local SQLite database (`aria_memory.db`). Every conversation, preference, proactive memory trigger, and security audit log is mirrored here into human-readable Markdown.",
        "",
        "## 📊 Memory Overview",
        "",
        f"- **👤 Profile & Core Facts:** `{stats['facts']}` items configured ([[Profile|Open Profile]] • [[System Facts|System State]])",
        f"- **💬 Conversation History:** `{stats['conversations']}` messages recorded across sessions",
        f"- **⚡ Proactive Triggers:** `{stats['triggers']}` memory triggers active ([[Memory Triggers|Open Triggers]])",
        f"- **🛡️ Security Audit Entries:** `{stats['audit_logs']}` tool runs logged ([[Security Audit Log|Open Audit Log]])",
        f"- **🎯 Agent Plans:** `{stats['plans']}` structured execution goals ([[Agent Goals|Open Plans]])",
        "",
        "---",
        "",
        "## 🗂️ Quick Navigation",
        "",
        "| Section | Description | Link |",
        "| :--- | :--- | :--- |",
        "| **👤 Profile & Facts** | Persistent user memory, name, and preferences | [[Profile]] |",
        "| **⚙️ System State** | Model providers, runtime flags, and app states | [[System Facts]] |",
        "| **💬 Conversations** | Chronological transcripts grouped by date | [[Conversations]] |",
        "| **⚡ Memory Triggers** | Learned conditional prompts and responses | [[Memory Triggers]] |",
        "| **🛡️ Security Audit** | Record of actions, shell runs, and risk levels | [[Security Audit Log]] |",
        "| **🎯 Agent Goals** | Autonomous plans generated by Aria | [[Agent Goals]] |",
        "",
        "---",
        "",
        "## 🔄 Real-Time Sync",
        "",
        "This vault is connected live to Aria's memory engine:",
        "1. When Aria talks with you on Telegram or Voice, messages automatically append to today's log under `Conversations/`.",
        "2. When Aria learns a new fact (e.g. your name or preferences), it updates [[Profile]].",
        "3. You can edit notes directly in Obsidian, and Aria will read from this vault whenever you ask questions about past notes.",
        "",
        f"*Vault Location:* `{vault_path}`  ",
        f"*Last Sync:* `{now_str}`",
    ]

    with open(vault_path / "00 - Home.md", "w", encoding="utf-8") as f:
        f.write("\n".join(content))


# ── Live Sync Hooks ─────────────────────────────────────────────────────────

def sync_message_to_obsidian(user_id: int, role: str, message: str):
    """Append a new message to today's daily conversation log in Obsidian."""
    try:
        vault = get_vault_path()
        today = datetime.now()
        date_str = today.strftime("%Y-%m-%d")
        month_str = today.strftime("%Y-%m")
        time_str = today.strftime("%H:%M:%S")

        conv_dir = vault / "Conversations" / month_str
        conv_dir.mkdir(parents=True, exist_ok=True)
        note_file = conv_dir / f"{date_str}.md"

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

        with open(note_file, "a", encoding="utf-8") as f:
            f.write("\n".join(entry))
    except Exception as e:
        logger.warning(f"[Obsidian Bridge] Real-time message sync failed: {e}")


def sync_fact_to_obsidian(key: str, value: Optional[str]):
    """Update profile/fact notes in Obsidian when a fact changes."""
    try:
        vault = get_vault_path()
        profile_path = vault / "Facts" / "Profile.md"
        if profile_path.exists():
            # Refresh facts export
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT key, value, updated_at FROM facts ORDER BY key ASC")
            facts = cursor.fetchall()
            conn.close()
            _export_facts(vault, facts)
    except Exception as e:
        logger.warning(f"[Obsidian Bridge] Real-time fact sync failed: {e}")


def sync_trigger_to_obsidian(phrase: str, payload: str):
    """Refresh triggers note in Obsidian."""
    try:
        vault = get_vault_path()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, trigger_phrase, payload, created_at FROM triggers ORDER BY id ASC")
        triggers = cursor.fetchall()
        conn.close()
        _export_triggers(vault, triggers)
    except Exception as e:
        logger.warning(f"[Obsidian Bridge] Real-time trigger sync failed: {e}")


# ── Vault Search & Query ────────────────────────────────────────────────────

def search_vault(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """
    Search markdown files in the Obsidian vault for text matching query.
    Returns list of dicts: [{"note": "Profile.md", "snippet": "...", "path": "..."}]
    """
    vault = get_vault_path()
    query_lower = query.lower()
    results = []

    for md_file in vault.rglob("*.md"):
        try:
            with open(md_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if query_lower in content.lower():
                lines = content.splitlines()
                matching_lines = [l.strip() for l in lines if query_lower in l.lower() and not l.startswith("---")]
                snippet = " ... ".join(matching_lines[:3]) if matching_lines else content[:200]
                results.append({
                    "note": md_file.name,
                    "rel_path": str(md_file.relative_to(vault)),
                    "snippet": snippet[:300],
                    "path": str(md_file.resolve()),
                })
                if len(results) >= max_results:
                    break
        except Exception:
            continue

    return results


def read_note(note_rel_path: str) -> Optional[str]:
    """Read the full content of a note from the Obsidian vault, searching subfolders if needed."""
    vault = get_vault_path()
    target = vault / note_rel_path
    if not target.exists() and not note_rel_path.endswith(".md"):
        target = vault / f"{note_rel_path}.md"

    if not target.exists() or not target.is_file():
        # Search for filename across all subdirectories
        clean_name = Path(note_rel_path).name.lower()
        if clean_name.endswith(".md"):
            clean_name = clean_name[:-3]
        for md_file in vault.rglob("*.md"):
            if md_file.stem.lower() == clean_name or clean_name in md_file.stem.lower():
                target = md_file
                break

    if target.exists() and target.is_file():
        try:
            with open(target, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"❌ Error reading note: {e}"
    return None
