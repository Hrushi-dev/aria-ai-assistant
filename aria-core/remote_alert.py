# -*- coding: utf-8 -*-
"""
Aria Remote Alert & System Diagnostics
---------------------------------------
Provides:
1. Native laptop audio announcement via Windows SAPI (laptop speakers).
2. Windows toast notification.
3. System hardware & network status (battery, host, IP, CPU, RAM).
4. Live desktop screenshot capture for Telegram remote confirmation.
"""

import os
import sys
import socket
import logging
import threading
import subprocess
from pathlib import Path
from typing import Dict, Tuple, Optional

logger = logging.getLogger("remote_alert")

SANDBOX_DIR = Path(__file__).parent.parent / "aria-sandbox"
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)


def speak_on_laptop(text: str):
    """Speak text through the laptop's speakers using native Windows SAPI in background thread."""
    def _speak():
        try:
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            speaker.Volume = 95
            speaker.Rate = 0
            speaker.Speak(text)
            pythoncom.CoUninitialize()
        except Exception as e:
            logger.warning(f"[Remote Alert] SAPI speak failed: {e}")

    thread = threading.Thread(target=_speak, daemon=True)
    thread.start()


def show_laptop_toast(title: str, message: str):
    """Show a Windows toast balloon tip notification on the laptop screen."""
    def _toast():
        try:
            ps_script = (
                "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; "
                "$n.Icon = [System.Drawing.SystemIcons]::Application; "
                "$n.BalloonTipIcon = 'Info'; "
                f"$n.BalloonTipTitle = '{title}'; "
                f"$n.BalloonTipText = '{message}'; "
                "$n.Visible = $true; "
                "$n.ShowBalloonTip(5000); "
                "Start-Sleep -Seconds 6; "
                "$n.Dispose()"
            )
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script])
        except Exception as e:
            logger.warning(f"[Remote Alert] Toast notification failed: {e}")

    thread = threading.Thread(target=_toast, daemon=True)
    thread.start()


def get_system_diagnostics() -> Dict[str, str]:
    """Gather hardware and system status (Battery, Hostname, IP, CPU, RAM)."""
    diag = {
        "hostname": os.environ.get("COMPUTERNAME", socket.gethostname()),
        "battery": "Unknown",
        "power_plugged": "Unknown",
        "cpu_percent": "0%",
        "ram_percent": "0%",
        "ip_address": "127.0.0.1",
    }

    # IP address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        diag["ip_address"] = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    # psutil metrics
    try:
        import psutil
        diag["cpu_percent"] = f"{psutil.cpu_percent(interval=None)}%"
        diag["ram_percent"] = f"{psutil.virtual_memory().percent}%"

        battery = psutil.sensors_battery()
        if battery:
            diag["battery"] = f"{battery.percent}%"
            diag["power_plugged"] = "Plugged In ⚡" if battery.power_plugged else "On Battery 🔋"
    except Exception as e:
        logger.warning(f"[Remote Alert] psutil diagnostics failed: {e}")

    return diag


def capture_laptop_screenshot() -> Optional[str]:
    """Capture desktop screenshot using tool_executor helper and return filepath."""
    try:
        from tool_executor import take_desktop_screenshot
        res = take_desktop_screenshot()
        if res and res.startswith("SCREENSHOT:"):
            shot_file = res.replace("SCREENSHOT:", "").strip()
            if Path(shot_file).exists():
                return shot_file
    except Exception as e:
        logger.warning(f"[Remote Alert] Screenshot failed: {e}")
    return None


def trigger_laptop_startup_alert() -> Tuple[Dict[str, str], Optional[str]]:
    """
    Fires the combined audio + visual sign on the laptop and captures desktop state.
    Returns:
        (diagnostics_dict, screenshot_path)
    """
    # 1. Audible voice alert on laptop speakers
    speak_on_laptop("Aria system online. Remote link established with mobile.")

    # 2. Visual Toast on laptop screen
    show_laptop_toast("🚀 Aria Online", "Remote link established via Mobile (Telegram)")

    # 3. Gather stats
    stats = get_system_diagnostics()

    # 4. Capture screenshot
    screenshot = capture_laptop_screenshot()

    return stats, screenshot
