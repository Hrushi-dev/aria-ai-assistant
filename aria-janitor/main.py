"""
main.py — ARIA System Janitor CLI Entry Point
=============================================
Usage:
    python main.py                          # Interactive loop
    python main.py --dry-run                # Plan without executing
    python main.py "clean NVIDIA cache"     # One-shot goal
    python main.py "clean NVIDIA cache" --dry-run
"""

import sys
import asyncio
import argparse
import subprocess
from pathlib import Path

# Ensure we can import sibling modules
sys.path.insert(0, str(Path(__file__).parent))

from planner import generate_plan
from executor import execute_plan, ExecutionResult
from audit_logger import start_session, log_result, finish_session, get_recent_sessions

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    _RICH = True
except ImportError:
    _RICH = False

console = Console() if _RICH else None

BANNER = r"""
  █████╗ ██████╗ ██╗ █████╗      ██╗ █████╗ ███╗   ██╗██╗████████╗ ██████╗ ██████╗
 ██╔══██╗██╔══██╗██║██╔══██╗     ██║██╔══██╗████╗  ██║██║╚══██╔══╝██╔═══██╗██╔══██╗
 ███████║██████╔╝██║███████║     ██║███████║██╔██╗ ██║██║   ██║   ██║   ██║██████╔╝
 ██╔══██║██╔══██╗██║██╔══██║██   ██║██╔══██║██║╚██╗██║██║   ██║   ██║   ██║██╔══██╗
 ██║  ██║██║  ██║██║██║  ██║╚█████╔╝██║  ██║██║ ╚████║██║   ██║   ╚██████╔╝██║  ██║
 ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═╝ ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝   ╚═╝    ╚═════╝ ╚═╝  ╚═╝
                          ⚙️  System Janitor v1.0
"""


def _print(msg: str, style: str = ""):
    if _RICH:
        console.print(msg, style=style)
    else:
        print(msg)


def _get_disk_summary() -> str:
    """Get a quick C: and D: free space summary via PowerShell."""
    try:
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-Command",
             "Get-PSDrive C, D | Select-Object Root, "
             "@{Name='FreeGB';Expression={[math]::Round($_.Free/1GB,2)}}, "
             "@{Name='UsedGB';Expression={[math]::Round($_.Used/1GB,2)}} | "
             "Format-Table -AutoSize | Out-String"],
            capture_output=True, text=True, timeout=15
        )
        return result.stdout.strip()
    except Exception:
        return "Could not query disk info."


def _print_disk_status():
    disk_info = _get_disk_summary()
    if _RICH:
        console.print(Panel(disk_info, title="💾 Disk Status", border_style="cyan"))
    else:
        print("\n=== Disk Status ===")
        print(disk_info)


def _print_plan(plan: dict, dry_run: bool):
    actions = plan.get("actions", [])
    mode_label = "[DRY RUN] " if dry_run else ""
    title = f"{mode_label}📋 Action Plan: {plan.get('goal_description', '')}"

    if _RICH:
        table = Table(title=title, box=box.ROUNDED, show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Summary", style="bold white")
        table.add_column("Risk", justify="center", width=6)
        table.add_column("Confirm?", justify="center", width=8)
        table.add_column("Est. Reclaim", justify="right", width=12)

        risk_colors = {0: "green", 1: "green", 2: "yellow", 3: "red", 4: "red"}
        for i, action in enumerate(actions, 1):
            risk = action.get("risk_level", 0)
            color = risk_colors.get(risk, "white")
            reclaim = action.get("estimated_reclaim_gb", 0)
            confirm = "✅ YES" if action.get("requires_confirmation") else "🤖 Auto"
            table.add_row(
                str(i),
                action.get("summary", ""),
                Text(str(risk), style=color),
                confirm,
                f"{reclaim:.2f} GB" if reclaim else "—",
            )
        console.print(table)
        total = plan.get("total_estimated_reclaim_gb", 0)
        console.print(f"[bold green]  Estimated total reclaim: {total:.2f} GB[/bold green]")
    else:
        print(f"\n{title}")
        for i, action in enumerate(actions, 1):
            risk = action.get("risk_level", 0)
            reclaim = action.get("estimated_reclaim_gb", 0)
            print(f"  {i}. [Risk {risk}] {action.get('summary', '')} (~{reclaim:.2f} GB)")
        print(f"  Total estimated: {plan.get('total_estimated_reclaim_gb', 0):.2f} GB")


def _print_results(results: list[ExecutionResult]):
    if _RICH:
        table = Table(title="📊 Execution Results", box=box.ROUNDED, show_lines=True)
        table.add_column("Status", justify="center", width=6)
        table.add_column("Action", style="bold white")
        table.add_column("Reclaimed", justify="right", width=10)
        table.add_column("Duration", justify="right", width=9)
        table.add_column("Note", style="dim")

        for r in results:
            note = r.blocked_reason or r.stdout[:60] or ""
            table.add_row(
                r.status_icon,
                r.action_summary,
                f"+{r.space_reclaimed_gb:.3f} GB" if r.space_reclaimed_gb else "—",
                f"{r.duration_seconds}s",
                note,
            )
        console.print(table)
    else:
        print("\n=== Results ===")
        for r in results:
            reclaim = f"+{r.space_reclaimed_gb:.3f} GB" if r.space_reclaimed_gb else "—"
            print(f"  {r.status_icon} {r.action_summary} | {reclaim} | {r.duration_seconds}s")


async def run_goal(goal: str, dry_run: bool):
    """Full pipeline: plan → display → execute → log → summarize."""
    _print(f"\n[bold cyan]🎯 Goal:[/bold cyan] {goal}" if _RICH else f"\nGoal: {goal}")
    _print_disk_status()

    # Plan
    _print("\n[bold]⏳ Generating action plan...[/bold]" if _RICH else "\nGenerating action plan...")
    try:
        plan = await generate_plan(goal)
    except Exception as e:
        _print(f"[red]❌ Planning failed: {e}[/red]" if _RICH else f"Planning failed: {e}", "red")
        return

    _print_plan(plan, dry_run)

    if dry_run:
        _print("\n[bold yellow]🔍 Dry run complete — no changes made.[/bold yellow]" if _RICH
               else "\nDry run complete — no changes made.")
        return

    # Confirm before executing anything
    if _RICH:
        console.print("\n[bold]Proceed with execution?[/bold] ", end="")
    else:
        print("\nProceed with execution? ", end="")
    answer = input("[y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        _print("[yellow]Aborted.[/yellow]" if _RICH else "Aborted.")
        return

    # Session logging
    session = start_session(goal, dry_run=False)

    # Execute
    _print("\n[bold]⚡ Executing...[/bold]" if _RICH else "\nExecuting...")
    results = execute_plan(plan, dry_run=False)

    # Log each result
    for r in results:
        log_result(r, session_md_path=session["md_path"])

    _print_results(results)

    # Session summary
    summary = finish_session(session, results)
    total = summary["total_reclaimed_gb"]
    log_path = summary["log_path"]

    if _RICH:
        console.print(Panel(
            f"[bold green]Total Reclaimed:[/bold green] {total:.3f} GB\n"
            f"[dim]Session log: {log_path}[/dim]",
            title="✅ Session Complete",
            border_style="green",
        ))
    else:
        print(f"\n=== Done ===\nTotal reclaimed: {total:.3f} GB\nLog: {log_path}")


def _show_history():
    sessions = get_recent_sessions(10)
    if not sessions:
        _print("[dim]No previous sessions found.[/dim]" if _RICH else "No previous sessions found.")
        return
    if _RICH:
        table = Table(title="📂 Recent Sessions", box=box.SIMPLE)
        table.add_column("Date")
        table.add_column("Actions", justify="right")
        table.add_column("Reclaimed", justify="right")
        for s in sessions:
            table.add_row(s["date"], str(s["actions"]), f"{s['total_reclaimed_gb']:.3f} GB")
        console.print(table)
    else:
        for s in sessions:
            print(f"  {s['date']} | {s['actions']} actions | {s['total_reclaimed_gb']:.3f} GB reclaimed")


def main():
    parser = argparse.ArgumentParser(
        description="ARIA System Janitor — Safe Windows disk maintenance agent"
    )
    parser.add_argument("goal", nargs="?", help="Maintenance goal in plain English")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, do not execute")
    parser.add_argument("--history", action="store_true", help="Show recent session history")
    args = parser.parse_args()

    if _RICH:
        console.print(BANNER, style="bold cyan")
    else:
        print(BANNER)

    if args.history:
        _show_history()
        return

    if args.goal:
        asyncio.run(run_goal(args.goal, dry_run=args.dry_run))
        return

    # Interactive loop
    _print("[bold]Type a maintenance goal, 'history', or 'quit'.[/bold]\n" if _RICH
           else "Type a maintenance goal, 'history', or 'quit'.\n")
    while True:
        try:
            if _RICH:
                goal = console.input("[bold green]janitor>[/bold green] ").strip()
            else:
                goal = input("janitor> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break

        if not goal:
            continue
        if goal.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break
        if goal.lower() == "history":
            _show_history()
            continue

        asyncio.run(run_goal(goal, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
