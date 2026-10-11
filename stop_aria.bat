@echo off
:: ── Kill ALL Aria processes ───────────────────────────────────────────────────
powershell -WindowStyle Hidden -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'main_daemon.py' } | Invoke-CimMethod -MethodName Terminate"

:: ── Stop Telegram Local API ────────────────────────────────────────────────────
docker stop aria-tg-api >nul 2>&1

powershell -WindowStyle Hidden -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; $n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Application; $n.BalloonTipIcon = 'Info'; $n.BalloonTipTitle = 'Aria AI'; $n.BalloonTipText = 'Aria has been stopped.'; $n.Visible = $true; $n.ShowBalloonTip(4000); Start-Sleep -Seconds 5; $n.Dispose()"

