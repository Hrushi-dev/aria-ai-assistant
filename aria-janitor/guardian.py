"""
guardian.py — ARIA System Janitor Policy Engine
================================================
The deterministic safety gate between the LLM's action plan and the OS.
No PowerShell command runs unless it passes every check here first.
"""

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# BLACKLIST — Hard block. No LLM instruction can override these.
# ---------------------------------------------------------------------------
BLACKLIST_PATTERNS = [
    r"^C:\\Windows\\(?!SoftwareDistribution\\Download)",   # Windows system (except update staging)
    r"^C:\\Users\\Dell\\Documents",
    r"^C:\\Users\\Dell\\Desktop",
    r"^C:\\Users\\Dell\\Pictures",
    r"^C:\\Users\\Dell\\Videos",
    r"^C:\\Users\\Dell\\Music",
    r"^C:\\Users\\Dell\\AppData\\Roaming\\Sucker Punch",   # Ghost of Tsushima saves
    r"^C:\\Users\\Dell\\AppData\\Local\\Steam",
    r"^C:\\Program Files\\",
    r"^C:\\Program Files \(x86\)\\",
    r"^D:\\WSL\\",                                          # WSL virtual disks
    r"^D:\\conda$",                                         # conda symlink target
    r"^D:\\gemini$",                                        # gemini symlink target
    r"^[A-Za-z]:\\$",                                       # Drive roots (C:\, D:\)
    r"^[A-Za-z]:\\Users\\Dell$",                            # User profile root
]

# ---------------------------------------------------------------------------
# WHITELIST — Only these paths may be modified/deleted without a blacklist hit.
# ---------------------------------------------------------------------------
WHITELIST_PATTERNS = [
    r"^C:\\ProgramData\\NVIDIA Corporation\\NVIDIA App\\UpdateFramework",
    r"^C:\\ProgramData\\NVIDIA Corporation\\Downloader",
    r"^C:\\ProgramData\\Dell\\SARemediation\\SystemRepair\\Snapshots",
    r"^C:\\Windows\\SoftwareDistribution\\Download",
    r"^C:\\Users\\Dell\\AppData\\Local\\Temp",
    r"^C:\\Users\\Dell\\AppData\\Local\\NVIDIA",
    r"^C:\\Users\\Dell\\AppData\\LocalLow\\NVIDIA",
    r"^D:\\AI-AIS\\aria-sandbox",
    r"^D:\\d_vol\\AI-AIS\\aria-sandbox",
    # Read-only / inspect actions are always allowed regardless of path
]

# ---------------------------------------------------------------------------
# FORBIDDEN command patterns (regardless of path)
# ---------------------------------------------------------------------------
FORBIDDEN_COMMAND_PATTERNS = [
    r"Remove-Item\s+[\"']?[A-Za-z]:\\[\"']?\s",            # Remove-Item on drive root
    r"Format-Volume",
    r"Remove-Partition",
    r"Clear-Disk",
    r"diskpart",
    r"rd\s+/s\s+/q\s+[A-Za-z]:\\$",                        # rd /s /q C:\ style
    r"rmdir\s+/s",
]

# Risk levels (matches onemore.md spec)
RISK_LEVELS = {
    0: "Inspect (read-only)",
    1: "Cache Purge (safe whitelist)",
    2: "Migration (move + symlink)",
    3: "Destructive (permanent deletion)",
    4: "System Config (services/drivers/power)",
}


def _normalise_path(path_str: str) -> str:
    """Normalise a path string for consistent comparison."""
    if not path_str:
        return ""
    # Resolve env vars and expand ~ if present
    p = str(Path(path_str.strip().strip("'\"")).expanduser())
    # Ensure trailing separator is stripped for root-check regex
    if len(p) == 3 and p[1:] == ":\\":
        return p  # keep C:\ as-is for root detection
    return p.rstrip("\\/")


def _matches_any(path: str, patterns: list) -> tuple[bool, str]:
    """Return (matched, pattern) if path matches any pattern in the list."""
    for pattern in patterns:
        if re.search(pattern, path, re.IGNORECASE):
            return True, pattern
    return False, ""


def validate_action(action: dict) -> tuple[bool, str]:
    """
    Validate a janitor action dict against policy rules.

    Parameters
    ----------
    action : dict
        Must contain at least 'target_path', 'command', and 'risk_level'.

    Returns
    -------
    (is_safe: bool, reason: str)
        If is_safe is False, reason explains why it was blocked.
    """
    target_path = action.get("target_path", "")
    command = action.get("command", "")
    risk_level = int(action.get("risk_level", 0))

    # --- 1. Read-only / inspect always pass (risk level 0) -----------------
    if risk_level == 0:
        return True, "Read-only inspection — auto-approved."

    # --- 2. Validate target path -------------------------------------------
    norm_path = _normalise_path(target_path)

    # 2a. Blacklist check (hard block)
    is_blacklisted, blk_pattern = _matches_any(norm_path, BLACKLIST_PATTERNS)
    if is_blacklisted:
        return False, (
            f"🚫 BLOCKED: Path '{norm_path}' matches blacklist rule '{blk_pattern}'. "
            "This location is protected and cannot be modified."
        )

    # 2b. Whitelist check — non-read actions must be explicitly whitelisted
    is_whitelisted, _ = _matches_any(norm_path, WHITELIST_PATTERNS)
    if not is_whitelisted and risk_level >= 1:
        return False, (
            f"⚠️ BLOCKED: Path '{norm_path}' is not on the approved whitelist. "
            "Add it to WHITELIST_PATTERNS in guardian.py to allow modifications."
        )

    # --- 3. Forbidden command patterns -------------------------------------
    for pattern in FORBIDDEN_COMMAND_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False, (
                f"🚫 BLOCKED: Command contains a forbidden pattern ('{pattern}'). "
                "This command structure is never permitted."
            )

    # --- 4. Wildcard root delete guard ------------------------------------
    # Catch patterns like Remove-Item 'C:\*' -Recurse
    if re.search(r"[A-Za-z]:\\[\"']?\s*[\*\-]", command, re.IGNORECASE):
        return False, "🚫 BLOCKED: Wildcard operation detected at drive root level."

    return True, f"✅ APPROVED: Risk level {risk_level} ({RISK_LEVELS.get(risk_level, 'Unknown')})."


def validate_batch(actions: list) -> list[dict]:
    """
    Validate a list of action dicts.

    Returns a list of dicts with keys: action, is_safe, reason
    """
    results = []
    for action in actions:
        is_safe, reason = validate_action(action)
        results.append({"action": action, "is_safe": is_safe, "reason": reason})
    return results


# ---------------------------------------------------------------------------
# Telegram-hook interface (for future aria-core integration)
# ---------------------------------------------------------------------------
def validate_action_for_telegram(action: dict) -> dict:
    """
    Thin wrapper returning a serialisable dict for Telegram approval flow.
    Designed to be imported by aria-core/permission_gateway.py in the future.
    """
    is_safe, reason = validate_action(action)
    return {
        "action_summary": action.get("summary", "Unknown"),
        "target_path": action.get("target_path", ""),
        "risk_level": action.get("risk_level", 0),
        "risk_label": RISK_LEVELS.get(int(action.get("risk_level", 0)), "Unknown"),
        "is_safe": is_safe,
        "reason": reason,
        "requires_telegram_approval": not is_safe or int(action.get("risk_level", 0)) >= 2,
    }


if __name__ == "__main__":
    import sys as _sys
    _sys.stdout.reconfigure(encoding="utf-8")
    # Quick self-test
    test_cases = [
        {"summary": "List drives", "target_path": "", "command": "Get-PSDrive C, D", "risk_level": 0},
        {"summary": "Clear NVIDIA cache", "target_path": r"C:\ProgramData\NVIDIA Corporation\NVIDIA App\UpdateFramework", "command": "Remove-Item -Path 'C:\\ProgramData\\NVIDIA Corporation\\NVIDIA App\\UpdateFramework\\*' -Recurse -Force", "risk_level": 1},
        {"summary": "Delete Documents", "target_path": r"C:\Users\Dell\Documents", "command": "Remove-Item -Path 'C:\\Users\\Dell\\Documents\\*' -Recurse -Force", "risk_level": 3},
        {"summary": "Delete drive root", "target_path": r"C:\\", "command": "Remove-Item -Path 'C:\\' -Recurse -Force", "risk_level": 3},
    ]
    print("=== Guardian Self-Test ===")
    for tc in test_cases:
        ok, msg = validate_action(tc)
        status = "✅" if ok else "❌"
        print(f"{status} [{tc['summary']}]: {msg}")
