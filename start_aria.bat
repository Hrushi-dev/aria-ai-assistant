@echo off
:: ── Kill ALL existing Aria instances first ────────────────────────────────────
powershell -WindowStyle Hidden -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'main_daemon.py' } | Invoke-CimMethod -MethodName Terminate"
timeout /t 3 /nobreak >nul

:: ── Start exactly ONE Aria instance (visible console for debugging) ────────────
:: Uses the root venv — change to pythonw.exe if you want it fully background
start "Aria Daemon" /B "D:\AI-AIS\venv\Scripts\python.exe" "D:\AI-AIS\aria-core\main_daemon.py"

powershell -WindowStyle Hidden -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; $n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Application; $n.BalloonTipIcon = 'Info'; $n.BalloonTipTitle = 'Aria AI'; $n.BalloonTipText = 'Aria is running. Send /ping on Telegram to verify.'; $n.Visible = $true; $n.ShowBalloonTip(4000); Start-Sleep -Seconds 5; $n.Dispose()"

