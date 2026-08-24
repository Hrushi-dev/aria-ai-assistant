@echo off
:: ── Kill ALL existing Aria instances first ────────────────────────────────────
powershell -WindowStyle Hidden -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'main_daemon.py' } | Invoke-CimMethod -MethodName Terminate"
timeout /t 4 /nobreak >nul

:: ── Ensure Telegram Local API is running ─────────────────────────────────────
docker start aria-tg-api >nul 2>&1

:: ── Start exactly ONE Aria instance silently ─────────────────────────────────
start "" /B "D:\AI-AIS\aria-core\venv\Scripts\pythonw.exe" "D:\AI-AIS\aria-core\main_daemon.py"

:: ── Show Windows toast notification ──────────────────────────────────────────
powershell -WindowStyle Hidden -Command ^
  "Add-Type -AssemblyName System.Windows.Forms; ^
   $n = New-Object System.Windows.Forms.NotifyIcon; ^
   $n.Icon = [System.Drawing.SystemIcons]::Application; ^
   $n.BalloonTipIcon = 'Info'; ^
   $n.BalloonTipTitle = 'Aria AI'; ^
   $n.BalloonTipText = 'Aria is running in the background'; ^
   $n.Visible = $true; ^
   $n.ShowBalloonTip(4000); ^
   Start-Sleep -Milliseconds 5000; ^
   $n.Dispose()"
