"""
audit_logger.py — ARIA System Janitor Session Logger
=====================================================
Logs every operation to JSON Lines and a human-readable Markdown file.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from executor import ExecutionResult

# Logs directory relative to this file's location
LOGS_DIR = Path(__file__).parent / "logs"
JSON_LOG_FILE = LOGS_DIR / "system_janitor_log.json"


def _ensure_logs_dir():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def log_result(result: ExecutionResult, session_md_path: Path = None):
    """
    Append a single ExecutionResult to the JSON log file.
    Optionally also appends to a Markdown session file.
    """
    _ensure_logs_dir()

    timestamp = datetime.now(timezone.utc).isoformat()
    entry = {
        "timestamp": timestamp,
        "summary": result.action_summary,
        "target_path": result.target_path,
        "risk_level": result.risk_level,
        "command": result.command,
        "success": result.success,
        "skipped": result.skipped,
        "dry_run": result.dry_run,
        "blocked_reason": result.blocked_reason,
        "space_before_gb": result.space_before_gb,
        "space_after_gb": result.space_after_gb,
        "space_reclaimed_gb": result.space_reclaimed_gb,
        "duration_seconds": result.duration_seconds,
        "stdout": result.stdout[:500] if result.stdout else "",  # truncate long output
        "stderr": result.stderr[:500] if result.stderr else "",
    }

    # Append to JSON Lines log
    with open(JSON_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    # Append to Markdown session file
    if session_md_path:
        _append_to_markdown(session_md_path, result, timestamp)


def _append_to_markdown(md_path: Path, result: ExecutionResult, timestamp: str):
    """Write one action entry to the Markdown session log."""
    status = result.status_icon
    reclaimed = f"+{result.space_reclaimed_gb:.3f} GB" if result.space_reclaimed_gb else "—"

    lines = [
        f"### {status} {result.action_summary}",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Timestamp | `{timestamp}` |",
        f"| Target | `{result.target_path or '—'}` |",
        f"| Risk Level | {result.risk_level} |",
        f"| Space Reclaimed | {reclaimed} |",
        f"| Duration | {result.duration_seconds}s |",
        f"| Dry Run | {'Yes' if result.dry_run else 'No'} |",
    ]
    if result.blocked_reason:
        lines.append(f"| Blocked Reason | {result.blocked_reason} |")
    if result.command:
        lines += ["", f"```powershell", result.command, "```"]
    if result.stderr:
        lines += ["", f"**Stderr:**", f"```", result.stderr[:300], "```"]
    lines.append("")

    with open(md_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def start_session(goal: str, dry_run: bool = False) -> dict:
    """
    Create a new session log file and return session metadata.

    Returns
    -------
    dict with keys: session_id, md_path, start_time
    """
    _ensure_logs_dir()
    now = datetime.now()
    session_id = now.strftime("%Y%m%d_%H%M%S")
    md_path = LOGS_DIR / f"session_{session_id}.md"

    header = f"""# ARIA System Janitor — Session {session_id}

| Field | Value |
|-------|-------|
| Goal | {goal} |
| Mode | {'🔍 DRY RUN' if dry_run else '⚡ LIVE'} |
| Started | {now.strftime('%Y-%m-%d %H:%M:%S')} |

---

"""
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(header)

    return {
        "session_id": session_id,
        "md_path": md_path,
        "start_time": now,
    }


def finish_session(session: dict, results: list[ExecutionResult]):
    """
    Write the session summary footer to the Markdown log.
    """
    md_path = session["md_path"]
    start_time = session["start_time"]
    end_time = datetime.now()
    duration = round((end_time - start_time).total_seconds(), 1)

    total_reclaimed = sum(r.space_reclaimed_gb for r in results)
    success_count = sum(1 for r in results if r.success)
    skipped_count = sum(1 for r in results if r.skipped)
    blocked_count = sum(1 for r in results if r.blocked_reason and not r.skipped)

    footer = f"""---

## Session Summary

| Metric | Value |
|--------|-------|
| Total Actions | {len(results)} |
| Succeeded | {success_count} |
| Skipped | {skipped_count} |
| Blocked | {blocked_count} |
| **Total Reclaimed** | **{total_reclaimed:.3f} GB** |
| Duration | {duration}s |
| Finished | {end_time.strftime('%Y-%m-%d %H:%M:%S')} |
"""
    with open(md_path, "a", encoding="utf-8") as f:
        f.write(footer)

    return {
        "total_reclaimed_gb": round(total_reclaimed, 3),
        "success_count": success_count,
        "skipped_count": skipped_count,
        "blocked_count": blocked_count,
        "duration_seconds": duration,
        "log_path": str(md_path),
    }


def get_recent_sessions(n: int = 5) -> list[dict]:
    """
    Return metadata for the N most recent sessions from the JSON log.
    Useful for the Telegram hook to show history.
    """
    _ensure_logs_dir()
    if not JSON_LOG_FILE.exists():
        return []

    entries = []
    with open(JSON_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue

    # Group by date prefix of timestamp
    sessions = {}
    for entry in entries:
        ts = entry.get("timestamp", "")[:19]
        date_key = ts[:10]
        if date_key not in sessions:
            sessions[date_key] = {"date": date_key, "actions": 0, "total_reclaimed_gb": 0.0}
        sessions[date_key]["actions"] += 1
        sessions[date_key]["total_reclaimed_gb"] += entry.get("space_reclaimed_gb", 0.0)

    sorted_sessions = sorted(sessions.values(), key=lambda x: x["date"], reverse=True)
    return sorted_sessions[:n]
