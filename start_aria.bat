@echo off
REM Kill ALL existing Aria instances first
powershell -WindowStyle Hidden -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'main_daemon.py' } | Invoke-CimMethod -MethodName Terminate"
timeout /t 2 /nobreak >nul

REM Start exactly ONE Aria instance in background
start "Aria Daemon" /B "D:\AI-AIS\venv\Scripts\python.exe" "D:\AI-AIS\aria-core\main_daemon.py"

REM Show toast notification on laptop
powershell -WindowStyle Hidden -Command "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; $n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Application; $n.BalloonTipIcon = 'Info'; $n.BalloonTipTitle = 'Aria AI'; $n.BalloonTipText = 'Aria is running. Ready for mobile commands.'; $n.Visible = $true; $n.ShowBalloonTip(4000); Start-Sleep -Seconds 5; $n.Dispose()"
