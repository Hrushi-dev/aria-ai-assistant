# ARIA System Janitor: Safe Maintenance & Storage Agent

> **Status:** Specification & Architecture Blueprint  
> **Target:** Safe, automated Windows maintenance without risk of accidental data loss  
> **Model Backend:** Gemini Free Tier (API) for structured intent & reasoning (fallback to local models for offline read-only inspection)

---

## 1. Executive Summary

During previous maintenance sessions, manual commands successfully reclaimed over **33 GB** of storage across C: and D: drives (cleaning NVIDIA caches, moving `.conda` and `.gemini`, migrating WSL2 virtual disks). However:
- Running raw shell commands manually is slow and error-prone (e.g., PowerShell parser errors, syntax slips).
- Letting a local or autonomous LLM run unconstrained shell commands is hazardous (accidental deletion of game saves, user files, or system drivers).

**ARIA System Janitor** is a specialized, safety-gated execution engine that acts as the protective shield between the AI's planning brain and your operating system.

---

## 2. The Golden Safety Rule: Whitelist & Risk Classification

The LLM **never** gets direct shell execution privileges. Every proposed action passes through a deterministic Python gate.

```text
User Request ("Clean up my C: drive")
          │
          ▼
   Gemini Free Tier
  (Generates JSON Action Plan)
          │
          ▼
┌─────────────────────────────────┐
│     ARIA SAFETY GATEWAY         │
│  1. Path Whitelist Check        │
│  2. Path Blacklist / Trap Check │
│  3. Risk Level Assessment       │
└────────────────┬────────────────┘
                 │
      ┌──────────┴──────────┐
      ▼                     ▼
[LOW RISK / READ]    [HIGH / DESTRUCTIVE]
Auto-execute         Require User Approval (Y/N)
      │                     │
      └──────────┬──────────┘
                 ▼
       PowerShell Runner
                 │
                 ▼
       Audit Log (audit.json)
```

---

## 3. Path Policies

### Protected Paths (Strict Blacklist — Hard Block)
The agent will refuse to delete or overwrite anything in these locations, regardless of LLM instructions:
- `C:\Windows\*` (except specific vetted maintenance utilities like `Dism.exe` / `pnputil`)
- `C:\Users\Dell\Documents\*`
- `C:\Users\Dell\Desktop\*`
- `C:\Users\Dell\Pictures\*` / `Videos\*` / `Music\*`
- Active game configs to keep (e.g., `C:\Users\Dell\AppData\Roaming\Sucker Punch Productions`)
- Root drive definitions (`C:\`, `D:\`)

### Allowed Targets (Vetted Whitelist)
Only explicit maintenance targets can be modified or purged:
- `C:\ProgramData\NVIDIA Corporation\NVIDIA App\UpdateFramework\*`
- `C:\ProgramData\NVIDIA Corporation\Downloader\*`
- `C:\ProgramData\Dell\SARemediation\SystemRepair\Snapshots\*`
- `C:\Windows\SoftwareDistribution\Download\*`
- `C:\Users\Dell\AppData\Local\Temp\*`
- User-specified game folders flagged for removal (e.g., `.minecraft`)

---

## 4. Risk Classification Matrix

| Level | Category | Examples | Auto-Execute? |
| :--- | :--- | :--- | :--- |
| **0 - Inspect** | Read-only scan | `Get-PSDrive`, checking folder sizes, listing installed packages | **Yes** (Safe) |
| **1 - Cache Purge** | Known temp/installer caches | Emptying `UpdateFramework`, deleting Windows update staging downloads | **Yes** (Safe within whitelist) |
| **2 - Migration** | Moving directories + Symlink | Robocopying `.conda` / `.gemini` to `D:\` and running `mklink` | **Requires Prompt** |
| **3 - Destructive** | Permanent deletion | Removing game installations, save data, or unregistering WSL distros | **Requires Strict Confirmation** |
| **4 - System Config** | System service / Power state | `powercfg /h`, stopping services, driver uninstalls via `pnputil` | **Requires Strict Confirmation** |

---

## 5. Machine Blueprint (Current State)

This system state is pre-recorded so the agent does not attempt redundant actions:

| Component | Current Location / State | Notes |
| :--- | :--- | :--- |
| **C: Free Space** | ~40.67 GB Free | Baseline as of September 2026 |
| **Conda Directory** | `C:\Users\Dell\.conda` → `D:\conda` | **Symlink active.** Do not re-migrate. |
| **Gemini Directory** | `C:\Users\Dell\.gemini` → `D:\gemini` | **Symlink active.** Do not re-migrate. |
| **WSL Ubuntu** | `D:\WSL\Ubuntu` | WSL2 distro running off D: |
| **WSL Docker** | `D:\WSL\Docker` | WSL2 distro running off D: |
| **Hibernation** | Disabled (`powercfg /h off`) | Can be restored via `powercfg /h on` if desired |
| **Ghost of Tsushima** | Preserved | Save & config preserved |

---

## 6. Architecture & Implementation Modules

When creating this module under ARIA, it consists of 4 clean Python scripts:

### 1. `guardian.py` (The Policy Engine)
- Contains the path whitelist, blacklist, and regex checks.
- Validates every command or file path before the runner touches it.
- Rejects wildcard deletes (`*.*` on root folders) immediately.

### 2. `planner.py` (Gemini API Integration)
- Connects to Google AI Studio using Gemini Flash (free tier).
- Enforces strict structured output (JSON schema):
```json
{
  "summary": "Purge NVIDIA App download cache",
  "risk_level": 1,
  "requires_confirmation": false,
  "target_path": "C:\\ProgramData\\NVIDIA Corporation\\NVIDIA App\\UpdateFramework",
  "command": "Remove-Item -Path 'C:\\ProgramData\\NVIDIA Corporation\\NVIDIA App\\UpdateFramework\\*' -Recurse -Force",
  "estimated_reclaim_gb": 7.3
}
```

### 3. `executor.py` (Safe PowerShell Runner)
- Executes validated commands via PowerShell subprocess.
- Automatically handles quotes, paths, and catches errors.
- Enforces timeout limits so scripts don't hang indefinitely.

### 4. `audit_logger.py` (Session History)
- Logs every operation to `system_janitor_log.json` and human-readable Markdown:
  - Timestamp
  - Action taken
  - Starting free space vs. Ending free space
  - Confirmation status

---

## 7. Future Feature Extension (Placeholder)

> **User Note:** Space reserved for your upcoming feature request. Once specified, it will be integrated into the intent router and execution pipeline below.

- [ ] *Pending: Upcoming Feature Specification*
- [ ] *Integration with Telegram / Voice interfaces when ARIA expands*

---

## 8. Quick Start Verification Command

To check system baseline at any time without making changes:

```powershell
# Quick Storage & Symlink Health Check
Get-PSDrive C, D | Select-Object Root, @{Name="FreeGB";Expression={[math]::Round($_.Free/1GB, 2)}}, @{Name="UsedGB";Expression={[math]::Round($_.Used/1GB, 2)}}
Get-Item "C:\Users\Dell\.conda", "C:\Users\Dell\.gemini" | Select-Object FullName, LinkType, Target
```
