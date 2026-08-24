@echo off
:: ── Kill ALL Aria processes ───────────────────────────────────────────────────
powershell -WindowStyle Hidden -Command "Get-Process python,pythonw -ErrorAction SilentlyContinue | Stop-Process -Force"

:: ── Stop Telegram Local API ────────────────────────────────────────────────────
docker stop aria-tg-api >nul 2>&1

:: ── Show Windows toast notification ──────────────────────────────────────────
powershell -WindowStyle Hidden -Command ^
  "Add-Type -AssemblyName System.Windows.Forms; ^
   $n = New-Object System.Windows.Forms.NotifyIcon; ^
   $n.Icon = [System.Drawing.SystemIcons]::Application; ^
   $n.BalloonTipIcon = 'Info'; ^
   $n.BalloonTipTitle = 'Aria AI'; ^
   $n.BalloonTipText = 'Aria has been stopped.'; ^
   $n.Visible = $true; ^
   $n.ShowBalloonTip(4000); ^
   Start-Sleep -Milliseconds 5000; ^
   $n.Dispose()"
