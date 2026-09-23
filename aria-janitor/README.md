# ARIA System Janitor

A safety-gated Windows disk maintenance agent. Natural language in → validated PowerShell out.

## Architecture

```
User Goal (plain English)
        │
        ▼
  planner.py       ← Gemini API → JSON action plan
        │
        ▼
  guardian.py      ← Path whitelist/blacklist + command safety checks
        │
    ┌───┴───┐
    ▼       ▼
 LOW RISK  HIGH RISK
 Auto-run  Y/N prompt
    └───┬───┘
        │
  executor.py      ← PowerShell subprocess runner
        │
        ▼
audit_logger.py    ← JSON Lines + Markdown session log
```

## Quick Start

```bash
# 1. Copy the env template
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# 2. Run interactively
python main.py

# 3. One-shot goal
python main.py "clean NVIDIA cache and clear Windows Update downloads"

# 4. Preview without executing (safe)
python main.py "clean NVIDIA cache" --dry-run

# 5. View session history
python main.py --history
```

## Risk Levels

| Level | Category | Auto-Execute? |
|-------|----------|---------------|
| 0 | Inspect (read-only) | ✅ Yes |
| 1 | Cache Purge (whitelist only) | ✅ Yes |
| 2 | Migration (move + symlink) | ⚠️ Requires Y/N |
| 3 | Destructive (permanent delete) | ⚠️ Requires Y/N |
| 4 | System Config (services/power) | ⚠️ Requires Y/N |

## Protected Paths (Hard Block)

- `C:\Windows\*` (except Update staging)
- `C:\Users\Dell\Documents`, `Desktop`, `Pictures`, `Videos`, `Music`
- `C:\Users\Dell\AppData\Roaming\Sucker Punch\*` (Ghost of Tsushima saves)
- `C:\Program Files\*`, `C:\Program Files (x86)\*`
- `D:\WSL\*`, `D:\conda`, `D:\gemini` (symlink targets)

## Logs

Session logs are written to `aria-janitor/logs/`:
- `system_janitor_log.json` — JSON Lines, machine-readable, all-time history
- `session_YYYYMMDD_HHMMSS.md` — human-readable per-session report

## Future: Telegram Integration

The module exposes Telegram-ready hooks:
- `guardian.validate_action_for_telegram(action)` — serialisable validation result
- `planner.generate_plan_for_telegram(goal)` — plan with approval metadata
- `executor.execute_plan_for_telegram(plan)` — non-interactive execution (skips risky)

These can be wired into `aria-core/main_daemon.py` to trigger cleanups from your phone.
