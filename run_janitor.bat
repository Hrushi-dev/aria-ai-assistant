@echo off
chcp 65001 >nul
title ARIA System Janitor — Disk Cleaner
cd /d "%~dp0\aria-janitor"

set "PYTHON=%~dp0venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    set "PYTHON=python"
)

if not "%~1"=="" (
    "%PYTHON%" main.py "%~1"
    goto end
)

:menu
cls
echo =====================================================================
echo                 ARIA System Janitor — Windows Disk Cleaner
echo =====================================================================
echo.
echo   1. Quick Safe Clean (Temp, Windows Update staging, NVIDIA caches)
echo   2. Dry Run Only (Inspect and estimate reclaimable space safely)
echo   3. Launch Interactive Janitor CLI Loop
echo   4. View Previous Cleaning History
echo   5. Exit
echo.
echo =====================================================================
set /p choice="Select an option (1-5): "

if "%choice%"=="1" (
    echo.
    echo Running Safe Disk Cleanup...
    "%PYTHON%" main.py "Clean temp files, Windows update staging, and NVIDIA caches"
    goto pause_end
)
if "%choice%"=="2" (
    echo.
    echo Running Dry Run Inspection...
    "%PYTHON%" main.py --dry-run "Inspect disk and find all safe reclaim targets"
    goto pause_end
)
if "%choice%"=="3" (
    "%PYTHON%" main.py
    goto end
)
if "%choice%"=="4" (
    "%PYTHON%" main.py --history
    goto pause_end
)
if "%choice%"=="5" (
    goto end
)

goto menu

:pause_end
echo.
echo Press any key to return to menu...
pause >nul
goto menu

:end
