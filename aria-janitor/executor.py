"""
executor.py — ARIA System Janitor Safe PowerShell Runner
=========================================================
Validates actions through guardian.py, prompts the user for high-risk
confirmations, then runs PowerShell and measures space reclaimed.
"""

import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional
from guardian import validate_action, RISK_LEVELS

# Default timeout for a single PowerShell command (seconds)
DEFAULT_TIMEOUT = 60

# Risk levels that always require explicit Y/N confirmation
CONFIRMATION_THRESHOLD = 2


@dataclass
class ExecutionResult:
    """Result of a single action execution."""
    action_summary: str
    target_path: str
    risk_level: int
    command: str
    success: bool
    stdout: str = ""
    stderr: str = ""
    space_before_gb: float = 0.0
    space_after_gb: float = 0.0
    space_reclaimed_gb: float = 0.0
    duration_seconds: float = 0.0
    blocked_reason: Optional[str] = None
    skipped: bool = False
    dry_run: bool = False

    @property
    def status_icon(self) -> str:
        if self.dry_run:
            return "🔍"
        if self.blocked_reason:
            return "🚫"
        if self.skipped:
            return "⏭️"
        return "✅" if self.success else "❌"


def _get_free_gb(drive: str = "C") -> float:
    """Query free space on a drive letter via PowerShell. Returns GB as float."""
    try:
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-Command",
             f"(Get-PSDrive {drive} | Select-Object -ExpandProperty Free) / 1GB"],
            capture_output=True, text=True, timeout=10
        )
        return round(float(result.stdout.strip()), 3)
    except Exception:
        return 0.0


def _run_powershell(command: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[bool, str, str]:
    """
    Run a PowerShell command.

    Returns
    -------
    (success: bool, stdout: str, stderr: str)
    """
    try:
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout
        )
        success = result.returncode == 0
        return success, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout}s."
    except Exception as e:
        return False, "", str(e)


def _prompt_confirmation(action: dict) -> bool:
    """
    Show a formatted confirmation prompt for high-risk actions.
    Returns True if user confirms, False if skipped.
    """
    risk = int(action.get("risk_level", 0))
    print("\n" + "=" * 60)
    print(f"⚠️  HIGH-RISK ACTION — Risk Level {risk}: {RISK_LEVELS.get(risk, 'Unknown')}")
    print("=" * 60)
    print(f"  Summary    : {action.get('summary', '')}")
    print(f"  Target     : {action.get('target_path', '')}")
    print(f"  Estimated  : -{action.get('estimated_reclaim_gb', '?')} GB")
    print(f"  Command    :\n    {action.get('command', '')}")
    print("=" * 60)
    while True:
        answer = input("  Proceed? [y/N]: ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no", ""):
            return False
        print("  Please enter 'y' or 'n'.")


def execute_action(
    action: dict,
    dry_run: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    auto_approve: bool = False,
) -> ExecutionResult:
    """
    Execute a single janitor action.

    Parameters
    ----------
    action : dict
        Action dict from planner.py (summary, risk_level, target_path, command, etc.)
    dry_run : bool
        If True, validate and display the action but do not execute.
    timeout : int
        Max seconds to wait for the PowerShell command.
    auto_approve : bool
        If True, skip interactive prompts (for scripted / Telegram-triggered runs).
        High-risk actions are then skipped rather than auto-approved.
    """
    summary = action.get("summary", "Unknown action")
    target = action.get("target_path", "")
    command = action.get("command", "")
    risk = int(action.get("risk_level", 0))

    # --- 1. Guardian validation ---
    is_safe, reason = validate_action(action)
    if not is_safe:
        return ExecutionResult(
            action_summary=summary,
            target_path=target,
            risk_level=risk,
            command=command,
            success=False,
            blocked_reason=reason,
        )

    # --- 2. Dry-run mode ---
    if dry_run:
        return ExecutionResult(
            action_summary=summary,
            target_path=target,
            risk_level=risk,
            command=command,
            success=True,
            dry_run=True,
            stdout=f"[DRY RUN] Would execute: {command}",
        )

    # --- 3. Confirmation for high-risk actions ---
    if risk >= CONFIRMATION_THRESHOLD:
        if auto_approve:
            # Non-interactive mode: skip rather than blindly run risky actions
            return ExecutionResult(
                action_summary=summary,
                target_path=target,
                risk_level=risk,
                command=command,
                success=False,
                skipped=True,
                blocked_reason="Skipped (non-interactive mode — requires manual approval).",
            )
        confirmed = _prompt_confirmation(action)
        if not confirmed:
            return ExecutionResult(
                action_summary=summary,
                target_path=target,
                risk_level=risk,
                command=command,
                success=False,
                skipped=True,
                blocked_reason="User declined.",
            )

    # --- 4. Measure space before ---
    drive_letter = "C"
    if target and len(target) >= 1:
        drive_letter = target[0].upper()
    space_before = _get_free_gb(drive_letter)

    # --- 5. Execute ---
    start = time.monotonic()
    success, stdout, stderr = _run_powershell(command, timeout=timeout)
    duration = round(time.monotonic() - start, 2)

    # --- 6. Measure space after ---
    space_after = _get_free_gb(drive_letter)
    reclaimed = round(max(space_after - space_before, 0.0), 3)

    return ExecutionResult(
        action_summary=summary,
        target_path=target,
        risk_level=risk,
        command=command,
        success=success,
        stdout=stdout,
        stderr=stderr,
        space_before_gb=space_before,
        space_after_gb=space_after,
        space_reclaimed_gb=reclaimed,
        duration_seconds=duration,
    )


def execute_plan(
    plan: dict,
    dry_run: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    auto_approve: bool = False,
) -> list[ExecutionResult]:
    """
    Execute all actions in a plan sequentially.

    Parameters
    ----------
    plan : dict
        Plan dict from planner.py.

    Returns
    -------
    list[ExecutionResult]
    """
    actions = plan.get("actions", [])
    results = []
    for action in actions:
        result = execute_action(action, dry_run=dry_run, timeout=timeout, auto_approve=auto_approve)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Telegram-hook interface (for future aria-core integration)
# ---------------------------------------------------------------------------
def execute_plan_for_telegram(plan: dict, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
    """
    Execute a plan in non-interactive mode (auto_approve=False → risky skipped).
    Returns serialisable dicts suitable for Telegram message formatting.
    Designed to be called from aria-core/main_daemon.py.
    """
    results = execute_plan(plan, auto_approve=True, timeout=timeout)
    return [
        {
            "summary": r.action_summary,
            "status": r.status_icon,
            "risk_level": r.risk_level,
            "space_reclaimed_gb": r.space_reclaimed_gb,
            "success": r.success,
            "skipped": r.skipped,
            "blocked_reason": r.blocked_reason,
            "duration_seconds": r.duration_seconds,
        }
        for r in results
    ]
