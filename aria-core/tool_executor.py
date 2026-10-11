# -*- coding: utf-8 -*-
# tool_executor.py — Aria action engine
# FIX-01  take_desktop_screenshot  : native Pillow ImageGrab — zero console popup
# FIX-02  play_spotify             : Active window check prevents misfired media keys
# FIX-03  zip_files                : new ZIP archive handler
# FIX-04  volume_control           : pycaw Windows Core Audio hooks + safe VK math
# FIX-05  convert_to_pdf           : docx2pdf / reportlab conversion + COM thread safety
# FIX-06  gui_click                : coordinate + window-element automation (pyautogui)
# FIX-07  list_files               : Directory check prevents NotADirectoryError crashes

import os
import sys
import logging
import shutil
import time
import urllib.parse
import subprocess
import ctypes
import re
import webbrowser
import zipfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

import winreg

def _get_shell_folder(name: str) -> Path:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            val, _ = winreg.QueryValueEx(key, name)
            return Path(os.path.expandvars(val)).resolve()
    except Exception:
        return Path.home() / name

USER_HOME        = Path.home()
DESKTOP_DIR      = _get_shell_folder("Desktop")
DOWNLOADS_DIR    = _get_shell_folder("{374DE290-123F-4565-9164-39C4925E467B}") if not _get_shell_folder("Downloads").exists() else _get_shell_folder("Downloads")
if not DOWNLOADS_DIR.exists():
    DOWNLOADS_DIR = USER_HOME / "Downloads"
DOCUMENTS_DIR    = _get_shell_folder("Personal")
CURRENT_CORE_DIR = Path(__file__).parent.resolve()
DEFAULT_DUMP_DIR = Path("D:/AI-AIS/aria-sandbox").resolve()

_REAL_USER = USER_HOME.name 


# ─── Path resolver ──────────────────────────────────────────────────────────

def _sanitise_path(raw: str) -> str:
    _home_bs = str(USER_HOME).rstrip("\\") + "\\"
    _home_fs = str(USER_HOME).replace("\\", "/").rstrip("/") + "/"
    fixed = re.sub(
        r"(?i)C:\\[Uu]sers\\[^\\]+\\",
        lambda _: _home_bs,
        raw
    )
    fixed = re.sub(
        r"(?i)C:/[Uu]sers/[^/]+/",
        lambda _: _home_fs,
        fixed
    )
    return fixed


def resolve_target(target: str | None) -> Path:
    if not target or target.strip() in [".", "", "default", "current", "null", "None", "unspecified"]:
        return DEFAULT_DUMP_DIR

    cleaned = _sanitise_path(
        target.strip().replace("`", "").replace("'", "").replace('"', '')
    )

    if any(k in cleaned.lower() for k in ["your location", "this location", "here", "current folder", "working directory", "core"]):
        return CURRENT_CORE_DIR
    if "desktop" in cleaned.lower():
        sub = re.sub(r"(?:on|in|under)?\s*desktop\s*(?:folder)?", "", cleaned, flags=re.IGNORECASE).strip("/\\ ")
        return (DESKTOP_DIR / sub).resolve() if sub else DESKTOP_DIR
    if "download" in cleaned.lower():
        sub = re.sub(r"(?:on|in|under)?\s*downloads?\s*(?:folder)?", "", cleaned, flags=re.IGNORECASE).strip("/\\ ")
        return (DOWNLOADS_DIR / sub).resolve() if sub else DOWNLOADS_DIR
    if "document" in cleaned.lower():
        sub = re.sub(r"(?:on|in|under)?\s*documents?\s*(?:folder)?", "", cleaned, flags=re.IGNORECASE).strip("/\\ ")
        return (DOCUMENTS_DIR / sub).resolve() if sub else DOCUMENTS_DIR

    drive_match = re.search(r"\b([a-zA-Z])\s*:\s*\\?", cleaned)
    if drive_match:
        drive_letter = drive_match.group(1).upper()
        subpath = cleaned[drive_match.end():].strip().strip("/\\")
        if subpath:
            return Path(f"{drive_letter}:\\{subpath}").resolve()
        return Path(f"{drive_letter}:\\").resolve()

    expanded = os.path.expanduser(cleaned)
    resolved = Path(expanded).resolve()

    if not resolved.exists():
        if (DESKTOP_DIR / cleaned).exists():
            return (DESKTOP_DIR / cleaned).resolve()
        if (DEFAULT_DUMP_DIR / cleaned).exists():
            return (DEFAULT_DUMP_DIR / cleaned).resolve()

    return resolved


# ─── Window enumeration ─────────────────────────────────────────────────────

def get_open_windows_and_tabs() -> list[str]:
    titles = []
    EnumWindows        = ctypes.windll.user32.EnumWindows
    EnumWindowsProc    = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
    GetWindowText      = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLength= ctypes.windll.user32.GetWindowTextLengthW
    IsWindowVisible    = ctypes.windll.user32.IsWindowVisible

    def foreach_window(hwnd, lParam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLength(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                GetWindowText(hwnd, buff, length + 1)
                title = buff.value.strip()
                if title and title not in ["Default IME", "MSCTFIME UI", "Settings", "Program Manager"]:
                    titles.append(title)
        return True

    EnumWindows(EnumWindowsProc(foreach_window), 0)
    return titles


# ─── Window closer ──────────────────────────────────────────────────────────

PROTECTED_WINDOW_KEYWORDS = [
    "antigravity", "visual studio", "vscode", "code.exe", "cursor",
    "aria daemon", "powershell", "cmd.exe", "command prompt", "terminal",
    "task switching", "securityhealthsystray", "ms_webcheckmonitor",
    "default ime", "program manager", "settings", "windows input experience"
]

def close_window_or_tab(target_query: str) -> str:
    query = (target_query or "").lower().strip()
    closed = []

    pronouns = {"it", "this", "that", "the app", "app", "the window", "window", "current window", "active window", ""}
    if query in pronouns:
        try:
            import memory_store as mem
            last_app = mem.get_fact("last_opened_app")
            if last_app and last_app.lower() not in pronouns:
                query = last_app.lower().strip()
        except Exception:
            pass

    EnumWindows        = ctypes.windll.user32.EnumWindows
    EnumWindowsProc    = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
    GetWindowText      = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLength= ctypes.windll.user32.GetWindowTextLengthW
    IsWindowVisible    = ctypes.windll.user32.IsWindowVisible
    GetForegroundWindow= ctypes.windll.user32.GetForegroundWindow
    PostMessage        = ctypes.windll.user32.PostMessageW
    WM_CLOSE = 0x0010

    # If still a pronoun or empty, target foreground window safely
    if query in pronouns:
        fg_hwnd = GetForegroundWindow()
        if fg_hwnd:
            length = GetWindowTextLength(fg_hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                GetWindowText(fg_hwnd, buff, length + 1)
                fg_title = buff.value.strip()
                if not any(k in fg_title.lower() for k in PROTECTED_WINDOW_KEYWORDS):
                    PostMessage(fg_hwnd, WM_CLOSE, 0, 0)
                    return f"🛑 Successfully closed active window: '{fg_title}'"
                else:
                    return f"🛡️ Protected window '{fg_title}' cannot be closed automatically."

    def is_match(title_lower: str, q: str) -> bool:
        if any(k in title_lower for k in PROTECTED_WINDOW_KEYWORDS):
            return False
        if len(q) <= 3:
            return bool(re.search(rf"\b{re.escape(q)}\b", title_lower))
        return q in title_lower

    def foreach_window(hwnd, lParam):
        if not IsWindowVisible(hwnd):
            return True
        length = GetWindowTextLength(hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            GetWindowText(hwnd, buff, length + 1)
            title = buff.value.strip()
            if title and is_match(title.lower(), query):
                PostMessage(hwnd, WM_CLOSE, 0, 0)
                closed.append(title)
        return True

    EnumWindows(EnumWindowsProc(foreach_window), 0)
    if closed:
        return "🛑 Successfully closed window(s):\n" + "\n".join(f"• {w}" for w in closed[:5])

    app_map = {
        "notepad": "notepad.exe", "calc": "CalculatorApp.exe", "spotify": "Spotify.exe",
        "brave": "brave.exe", "chrome": "chrome.exe", "opera": "opera.exe", "discord": "Discord.exe"
    }
    if query in app_map or (len(query) >= 4 and query not in pronouns and not any(k in query for k in PROTECTED_WINDOW_KEYWORDS)):
        proc = app_map.get(query, f"{query}.exe")
        res = subprocess.run(
            f"taskkill /IM {proc} /F", shell=True, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if res.returncode == 0:
            return f"🛑 Successfully terminated process: '{query}'"
    return f"⚠️ No active window or process found matching '{target_query}'."



def minimize_window_or_tab(target_query: str) -> str:
    query = target_query.lower().strip()
    minimized = []

    EnumWindows = ctypes.windll.user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
    GetWindowText = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
    ShowWindow = ctypes.windll.user32.ShowWindow
    SW_MINIMIZE = 6

    def foreach_window(hwnd, lParam):
        length = GetWindowTextLength(hwnd)
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            GetWindowText(hwnd, buff, length + 1)
            title = buff.value.strip()
            if title and query in title.lower():
                ShowWindow(hwnd, SW_MINIMIZE)
                minimized.append(title)
        return True

    EnumWindows(EnumWindowsProc(foreach_window), 0)
    if minimized:
        return f"🔽 Successfully minimized window(s):\n" + "\n".join(f"• {w}" for w in minimized[:5])

    return f"⚠️ No active window found matching '{target_query}' to minimize."

def handle_system_power(command: str) -> str:
    power_cmd = (command or "").lower()
    if "sleep" in power_cmd:
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        return "💤 PC sent to sleep."
    elif "restart" in power_cmd:
        os.system("shutdown /r /t 5")
        return "🔄 PC restarting in 5 seconds."
    else:
        os.system("shutdown /s /t 5")
        return "🛑 PC shutting down in 5 seconds."


def launch_voice_assistant() -> str:

    import subprocess
    check = subprocess.run(
        'powershell "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match \'aria-voice\\\\main.py\' } | Select-Object -ExpandProperty ProcessId"',
        shell=True, capture_output=True, text=True
    )
    pids = [p.strip() for p in check.stdout.strip().split() if p.strip()]
    if pids:
        return "🎙️ **Aria Voice Assistant** is already running and listening!"

    python_exe = "D:\\AI-AIS\\venv\\Scripts\\python.exe"
    voice_script = "D:\\AI-AIS\\aria-voice\\main.py"
    voice_dir = "D:\\AI-AIS\\aria-voice"

    subprocess.Popen(
        [python_exe, voice_script],
        cwd=voice_dir,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    return (
        "🎙️ **Aria Voice Assistant Started!**\n\n"
        "• State: *Active & Listening*\n"
        "• Hearing: *Whisper STT*\n"
        "• Speech: *Kokoro TTS (af_bella)*\n\n"
        "Speak into your microphone anytime. Say *'switch to cloud'* or *'switch to local'* to toggle engines, or send *'stop voice'* to exit."
    )

def stop_voice_assistant() -> str:
    import subprocess
    subprocess.run(
        'powershell "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match \'aria-voice\\\\main.py\' } | Invoke-CimMethod -MethodName Terminate"',
        shell=True, capture_output=True, text=True
    )
    return "🛑 **Aria Voice Assistant stopped.**"


# ─── App / protocol launcher ────────────────────────────────────────────────

def launch_app_or_protocol(app_name: str) -> str:

    clean_app = re.sub(r"^(open|launch|start|run)\s+", "", app_name, flags=re.IGNORECASE).strip().lower()

    # Try resolving it as a folder first (e.g., 'open the folder DOWNLOADS')
    try:
        resolved = resolve_target(clean_app)
        if resolved.exists() and resolved.is_dir():
            os.startfile(str(resolved))
            return f"📁 Opened folder: {resolved.name}"
    except Exception:
        pass

    protocol_map = {
        "whatsapp":   "whatsapp:",
        "spotify":    "spotify:",
        "calc":       "calc.exe",
        "calculator": "calc.exe",
        "notepad":    "notepad.exe",
        "code":       "code",
        "vscode":     "code",
        "settings":   "ms-settings:",
        "camera":     "microsoft.windows.camera:",
        "photos":     "ms-photos:",
        "paint":      "mspaint.exe",
        "terminal":   "wt.exe",
        "cmd":        "cmd.exe",
        "chrome":     "start chrome",
        "opera":      "start opera",
        "brave":      "start brave",
        "edge":       "start msedge",
        "firefox":    "start firefox"
    }

    target = protocol_map.get(clean_app, clean_app)
    try:
        if re.match(r"^[a-zA-Z0-9-]+:", target) and not Path(target).exists() and not target.startswith("explorer.exe"):
            os.startfile(target)
        elif target.startswith("explorer.exe "):
            path_part = target[13:].strip().strip("'\"")
            resolved_path = resolve_target(path_part)
            if resolved_path.exists():
                os.startfile(str(resolved_path))
            else:
                subprocess.Popen(target, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            subprocess.Popen(
                target, shell=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        return f"🚀 Launched application: '{clean_app}'"
    except Exception as e:
        return f"⚠️ Could not launch application '{clean_app}': {e}"


# ─── Silent screenshot via Pillow ImageGrab ─────────────────────────

def take_desktop_screenshot() -> str:
    shot_dir = DEFAULT_DUMP_DIR
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shot_dir / "aria_screenshot.png"

    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=False)
        img.save(str(shot_path), "PNG")
        return f"SCREENSHOT:{shot_path}"
    except ImportError:
        pass
    except Exception as e:
        pass

    try:
        import pyautogui
        img = pyautogui.screenshot()
        img.save(str(shot_path))
        return f"SCREENSHOT:{shot_path}"
    except ImportError:
        pass
    except Exception:
        pass

    ps_path = str(shot_path).replace("\\", "/")
    ps_cmd = f"""
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $Screen   = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $Bitmap   = New-Object System.Drawing.Bitmap $Screen.Width, $Screen.Height
    $Graphics = [System.Drawing.Graphics]::FromImage($Bitmap)
    $Graphics.CopyFromScreen($Screen.X, $Screen.Y, 0, 0, $Screen.Size)
    $Bitmap.Save('{ps_path}', [System.Drawing.Imaging.ImageFormat]::Png)
    $Graphics.Dispose()
    $Bitmap.Dispose()
    """
    subprocess.run(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
        capture_output=True, timeout=12,
        creationflags=subprocess.CREATE_NO_WINDOW
    )
    if shot_path.exists():
        return f"SCREENSHOT:{shot_path}"
    return "⚠️ Screenshot capture failed — install Pillow: pip install pillow"


# ─── Spotify search + auto-play keypress ────────────────────────────

def _fire_media_play():
    try:
        _VK_MEDIA_PLAY_PAUSE = 0xB3
        KEYEVENTF_KEYUP = 0x0002
        ctypes.windll.user32.keybd_event(_VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(_VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_KEYUP, 0)
    except Exception:
        pass

def play_spotify_with_autoplay(query: str) -> str:
    clean_query = re.sub(
        r"^(play_spotify|open\s+spotify|play|search\s+for|search)\s*",
        "", query, flags=re.IGNORECASE
    ).strip()

    if not clean_query:
        return launch_app_or_protocol("spotify")

    encoded = urllib.parse.quote(clean_query)
    try:
        os.startfile(f"spotify:search:{encoded}")
    except Exception:
        webbrowser.open(f"https://open.spotify.com/search/{encoded}")

    time.sleep(3.0)
    
    # Safe Autoplay: Only fire media key if Spotify took focus
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if hwnd:
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
        if "spotify" in buff.value.lower():
            _fire_media_play()
            return f"🎵 Searching and auto-playing Spotify: \"{clean_query}\""

    return f"🎵 Opened Spotify search for: \"{clean_query}\""


# ─── ZIP archive creator ────────────────────────────────────────────

def create_zip_archive(source_paths: list[str], archive_name: str, dest_dir: str | None = None) -> str:
    dest = resolve_target(dest_dir) if dest_dir else DESKTOP_DIR
    dest.mkdir(parents=True, exist_ok=True)

    if not archive_name.lower().endswith(".zip"):
        archive_name += ".zip"
    zip_path = dest / archive_name

    added, skipped = [], []
    import tempfile
    import uuid
    import shutil
    
    # Exclusions as requested by spec
    exclusions = {".git", "node_modules", "venv", ".env", "__pycache__"}
    
    # Write to a non-synced scratch location first
    temp_zip_path = DEFAULT_DUMP_DIR / f"temp_{uuid.uuid4().hex}.zip"
    DEFAULT_DUMP_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        with zipfile.ZipFile(temp_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for sp in source_paths:
                p = Path(_sanitise_path(sp.strip()))
                if not p.exists():
                    skipped.append(str(p))
                    continue
                if p.is_dir():
                    for root, dirs, files in os.walk(p):
                        # Filter out excluded directories in-place so os.walk skips them entirely
                        dirs[:] = [d for d in dirs if d not in exclusions]
                        for file in files:
                            if file in exclusions:
                                continue
                            file_path = Path(root) / file
                            arcname = file_path.relative_to(p.parent)
                            zf.write(file_path, arcname)
                            added.append(file_path.name)
                else:
                    if p.name not in exclusions:
                        zf.write(p, p.name)
                        added.append(p.name)
                    
        # Verify it's a valid zip before reporting success
        if not zipfile.is_zipfile(temp_zip_path):
            raise ValueError("Created archive is corrupted or not a valid zip file.")
            
        # Move it to the final live/synced destination only after it's closed and verified
        shutil.move(str(temp_zip_path), str(zip_path))
        
        sandbox_copy = DEFAULT_DUMP_DIR / archive_name
        if str(zip_path.resolve()) != str(sandbox_copy.resolve()):
            shutil.copy2(str(zip_path), str(sandbox_copy))
            send_path = sandbox_copy
        else:
            send_path = zip_path
            
    except Exception as e:
        if temp_zip_path.exists():
            try:
                temp_zip_path.unlink()
            except:
                pass
        return f"⚠️ ZIP creation failed: {e}"

    note = f" | Skipped: {', '.join(skipped)}" if skipped else ""
    return f"SENDFILE:{send_path}|📦 Archive: {zip_path.name} ({len(added)} files){note}"


# ─── System volume control via pycaw ────────────────────────────────

def control_volume(action: str, level: int | None = None) -> str:
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        import comtypes
        from comtypes import CLSCTX_ALL

        devices  = AudioUtilities.GetSpeakers()
        volume   = comtypes.cast(
            devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None),
            comtypes.POINTER(IAudioEndpointVolume)
        )

        if action == "mute":
            volume.SetMute(1, None)
            return "🔇 System audio muted."
        elif action == "unmute":
            volume.SetMute(0, None)
            return "🔊 System audio unmuted."
        elif action == "set" and level is not None:
            scalar = max(0.0, min(1.0, level / 100.0))
            volume.SetMasterVolumeLevelScalar(scalar, None)
            return f"🔊 Volume set to {level}%."
        elif action == "up":
            cur = volume.GetMasterVolumeLevelScalar()
            new = min(1.0, cur + 0.1)
            volume.SetMasterVolumeLevelScalar(new, None)
            return f"🔊 Volume increased to {int(new * 100)}%."
        elif action == "down":
            cur = volume.GetMasterVolumeLevelScalar()
            new = max(0.0, cur - 0.1)
            volume.SetMasterVolumeLevelScalar(new, None)
            return f"🔉 Volume decreased to {int(new * 100)}%."
        else:
            return "⚠️ Unknown volume action."
    except ImportError:
        pass  
    except Exception:
        pass

    # Strategy 2: Virtual key events
    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_UP   = 0xAF
    KEYEVENTF_KEYUP = 0x0002

    def _vk(key):
        ctypes.windll.user32.keybd_event(key, 0, 0, 0)
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)

    if action == "mute":
        _vk(VK_VOLUME_MUTE); return "🔇 Audio toggled mute."
    elif action == "unmute":
        _vk(VK_VOLUME_MUTE); return "🔊 Audio unmuted (toggled)."
    elif action == "up":
        for _ in range(5): _vk(VK_VOLUME_UP)
        return "🔊 Volume increased."
    elif action == "down":
        for _ in range(5): _vk(VK_VOLUME_DOWN)
        return "🔉 Volume decreased."
    elif action == "set" and level is not None:
        # Guarantee zero state by spamming Volume Down, then step up
        for _ in range(50): _vk(VK_VOLUME_DOWN)
        steps = max(0, level // 2) 
        for _ in range(steps): _vk(VK_VOLUME_UP)
        return f"🔊 Volume set to ~{level}% (VK fallback)."
    return "⚠️ Unknown volume action."


# ─── Document-to-PDF converter ──────────────────────────────────────

def convert_to_pdf(source_path: str, dest_dir: str | None = None) -> str:
    src = Path(source_path.strip())
    if not src.exists():
        return f"⚠️ Source file not found: {src}"

    dest = resolve_target(dest_dir) if dest_dir else src.parent
    dest.mkdir(parents=True, exist_ok=True)
    pdf_path = dest / (src.stem + ".pdf")

    ext = src.suffix.lower()
    try:
        if ext == ".docx":
            try:
                import pythoncom
                pythoncom.CoInitialize() # Required for background thread COM access
            except ImportError:
                pass
                
            from docx2pdf import convert
            convert(str(src), str(pdf_path))
            
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass
            return f"📄 Converted to PDF: {pdf_path}"
            
        elif ext in [".txt", ".md"]:
            try:
                from reportlab.pdfgen import canvas as rl_canvas
                from reportlab.lib.pagesizes import A4
                c = rl_canvas.Canvas(str(pdf_path), pagesize=A4)
                width, height = A4
                lines = src.read_text(encoding="utf-8", errors="replace").splitlines()
                y = height - 40
                c.setFont("Helvetica", 11)
                for line in lines:
                    if y < 40:
                        c.showPage()
                        c.setFont("Helvetica", 11)
                        y = height - 40
                    c.drawString(40, y, line[:110])
                    y -= 14
                c.save()
                return f"📄 Converted to PDF: {pdf_path}"
            except ImportError:
                return "⚠️ reportlab not installed. Run: pip install reportlab"
        elif ext in [".xlsx", ".xls", ".csv"]:
            try:
                # Try Excel COM first for native PDF export
                import pythoncom
                pythoncom.CoInitialize()
                import win32com.client
                excel = win32com.client.Dispatch("Excel.Application")
                excel.Visible = False
                wb = excel.Workbooks.Open(str(src.resolve()))
                wb.ExportAsFixedFormat(0, str(pdf_path.resolve()))
                wb.Close(False)
                excel.Quit()
                pythoncom.CoUninitialize()
                return f"📄 Converted to PDF: {pdf_path}"
            except Exception as e:
                # Fallback to pandas and reportlab
                try:
                    import pandas as pd
                    from reportlab.pdfgen import canvas as rl_canvas
                    from reportlab.lib.pagesizes import A4
                    
                    if ext == ".csv":
                        df = pd.read_csv(str(src))
                    else:
                        df = pd.read_excel(str(src))
                        
                    text = df.to_string()
                    c = rl_canvas.Canvas(str(pdf_path), pagesize=A4)
                    width, height = A4
                    lines = text.splitlines()
                    y = height - 40
                    c.setFont("Helvetica", 8)
                    for line in lines:
                        if y < 40:
                            c.showPage()
                            c.setFont("Helvetica", 8)
                            y = height - 40
                        c.drawString(40, y, line[:180])
                        y -= 10
                    c.save()
                    return f"📄 Converted to PDF (via Pandas/ReportLab): {pdf_path}"
                except Exception as inner_e:
                    return f"⚠️ PDF conversion failed for {ext}: {inner_e}"
        else:
            return f"⚠️ Unsupported file type: {ext}. Supported: .docx, .txt, .md, .xlsx, .csv"
    except ImportError:
        return "⚠️ docx2pdf not installed. Run: pip install docx2pdf"
    except Exception as e:
        return f"⚠️ PDF conversion failed: {e}"


# ─── GUI / Cursor automation ────────────────────────────────────────

def _verify_gui_state(expected_description: str, max_retries: int = 2) -> dict:
    import asyncio
    from vision_gateway import verify_screen_state
    
    last_state = None
    for attempt in range(max_retries + 1):
        shot_res = take_desktop_screenshot()
        if not shot_res.startswith("SCREENSHOT:"):
            return {"approved": False, "reason": "Failed to take screenshot."}
        shot_path = shot_res.replace("SCREENSHOT:", "")
        
        try:
            state = asyncio.run(verify_screen_state(shot_path, expected_description))
        except Exception as e:
            return {"approved": False, "reason": f"Vision exception: {e}"}
            
        if state.get("approved"):
            return state
            
        last_state = state
        if attempt < max_retries:
            # Simple retry backoff (e.g., waiting for UI to load)
            time.sleep(3.0)
            
    return last_state or {"approved": False, "reason": "Max retries exceeded."}


def gui_click(x: int | None = None, y: int | None = None,
              window_title: str | None = None, element_text: str | None = None) -> str:
    try:
        import pyautogui
        old_fs = pyautogui.FAILSAFE
        pyautogui.FAILSAFE = False
        try:
            pyautogui.PAUSE    = 0.1

            if x is not None and y is not None:
                pyautogui.click(x, y)
                return f"🖱️ Clicked at ({x}, {y})."

            if element_text:
                loc = pyautogui.locateOnScreen(element_text, confidence=0.8)
                if loc:
                    pyautogui.click(loc)
                    return f"🖱️ Clicked element matching '{element_text}'."
                return f"⚠️ Could not locate '{element_text}' on screen."

            return "⚠️ Provide coordinates (x, y) or element_text for GUI click."
        finally:
            pyautogui.FAILSAFE = old_fs
    except ImportError:
        return "⚠️ pyautogui not installed. Run: pip install pyautogui"
    except Exception as e:
        return f"⚠️ GUI click failed: {e}"


def gui_type(text: str, delay: float = 0.05) -> str:
    try:
        import pyautogui
        pyautogui.typewrite(text, interval=delay)
        return f"⌨️ Typed: \"{text[:60]}{'...' if len(text) > 60 else ''}\""
    except ImportError:
        return "⚠️ pyautogui not installed. Run: pip install pyautogui"
    except Exception as e:
        return f"⚠️ GUI type failed: {e}"


# ─── YouTube visual picker ───────────────────────────────────────────────────

youtube_picker_targets = {}

def youtube_visual_search(query: str) -> str:
    global youtube_picker_targets
    youtube_picker_targets.clear()
    if not query.strip():
        webbrowser.open("https://www.youtube.com")
        return "▶️ Opened YouTube homepage."

    encoded = urllib.parse.quote(query.strip())
    url = f"https://www.youtube.com/results?search_query={encoded}"
    webbrowser.open(url)
    time.sleep(3.0)
    
    verify = _verify_gui_state(f"YouTube search results page for '{query}' is fully loaded and visible.")
    if not verify.get("approved"):
        return f"⚠️ YouTube verification failed: {verify.get('reason')} Hint: {verify.get('next_action_hint')}"

    shot_dir = DEFAULT_DUMP_DIR
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shot_dir / "yt_results.png"

    try:
        from PIL import ImageGrab, ImageDraw, ImageFont
        img = ImageGrab.grab(all_screens=False)
        w, h = img.size
        
        offset = 0
        try:
            import pytesseract
            top_crop = img.crop((0, 0, w, int(h * 0.4)))
            text = pytesseract.image_to_string(top_crop).lower()
            if "sponsored" in text or "ad" in text.split():
                offset = 120
        except Exception:
            pass
            
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 60)
        except Exception:
            font = ImageFont.load_default()
            
        for i in range(1, 4):
            x = int(w * 0.4)
            y = int(h * (0.35 + (i - 1) * 0.22))
            if i == 1 and offset > 0:
                y += offset
                
            youtube_picker_targets[i] = (x, y)
            r = 35
            draw.ellipse((x-r, y-r, x+r, y+r), fill="red", outline="white", width=3)
            draw.text((x-15, y-25), str(i), fill="white", font=font)
            
        img.save(str(shot_path), "PNG")
    except Exception:
        try:
            import pyautogui
            img = pyautogui.screenshot()
            img.save(str(shot_path))
        except Exception as e:
            return f"▶️ Searched YouTube for '{query}' but screenshot failed: {e}"

    return f"YTPICKER:{shot_path}|{query}"


def browser_scroll_and_screenshot() -> str:
    global youtube_picker_targets
    shot_dir  = DEFAULT_DUMP_DIR
    shot_dir.mkdir(parents=True, exist_ok=True)
    shot_path = shot_dir / "yt_results.png"

    try:
        import pyautogui
        old_fs = pyautogui.FAILSAFE
        pyautogui.FAILSAFE = False
        try:
            w, h = pyautogui.size()
            pyautogui.moveTo(w // 2, h // 2, duration=0.2)
            pyautogui.click()
            time.sleep(0.3)
            pyautogui.scroll(-750)
            time.sleep(1.0)

            from PIL import ImageGrab, ImageDraw, ImageFont
            img = ImageGrab.grab(all_screens=False)
            w, h = img.size
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("arial.ttf", 60)
            except Exception:
                font = ImageFont.load_default()

            youtube_picker_targets.clear()
            for i in range(1, 4):
                x = int(w * 0.4)
                y = int(h * (0.35 + (i - 1) * 0.22))
                youtube_picker_targets[i] = (x, y)
                r = 35
                draw.ellipse((x-r, y-r, x+r, y+r), fill="red", outline="white", width=3)
                draw.text((x-15, y-25), str(i), fill="white", font=font)

            img.save(str(shot_path), "PNG")
        finally:
            pyautogui.FAILSAFE = old_fs
    except Exception as e:
        return f"⚠️ Scroll failed: {e}"

    return f"YTPICKER:{shot_path}|scroll"



# ─── Action alias normalisation ─────────────────────────────────────────────
ACTION_ALIASES: dict[str, str] = {
    "create_folder":        "create_file_folder",
    "make_folder":          "create_file_folder",
    "new_folder":           "create_file_folder",
    "create_file":          "create_file_folder",
    "make_file":            "create_file_folder",
    "remove_folder":        "delete_folder",
    "remove_file":          "delete_file",
    "erase_file":           "delete_file",
    "erase_folder":         "delete_folder",
    "send_whatsapp_message": "whatsapp_message",
    "send_whatsapp":        "whatsapp_message",
    "whatsapp_send":        "whatsapp_message",
    "list_desktop":         "list_files",
    "show_files":           "list_files",
    "get_files":            "list_files",
    "list_directory":       "list_files",
    "show_folder":          "list_files",
    "zip_folder":           "create_zip",
    "compress":             "create_zip",
    "archive":              "create_zip",
    "zip_files":            "create_zip",
    "launch_app":           "open_app",
    "start_app":            "open_app",
    "youtube":              "play_youtube",
    "spotify":              "play_spotify",
    "play_music":           "play_spotify",
    "search_youtube":       "play_youtube",
    "minimize_window":      "minimize_app",
    "minimize_tab":         "minimize_app",
    "sleep_pc":             "system_power",
    "shutdown_pc":          "system_power",
    "check_tokens":         "token_quota"
}


# ─── Main action dispatcher ──────────────────────────────────────────────────

def execute_tool(intent: dict) -> str:
    raw_action   = intent.get("action")
    action       = ACTION_ALIASES.get(raw_action, raw_action) 
    target_str   = intent.get("target_path")
    folder_name  = intent.get("folder_name")
    file_name    = intent.get("file_name")
    command      = intent.get("command")
    file_content = intent.get("file_content") or ""

    try:
        if action == "create_file_folder":
            if folder_name:
                folder_name = re.sub(r"\s+(in that|inside it|in here|on desktop|here|there|please)$", "", folder_name, flags=re.IGNORECASE).strip()
            if file_name and str(file_name).lower() not in ["null", "none", ""]:
                file_name = re.sub(r"\s+(in that|inside it|in here|on desktop|here|there|please)$", "", str(file_name), flags=re.IGNORECASE).strip()
            
            base_dir = resolve_target(target_str)
            if folder_name:
                base_dir = base_dir / folder_name.strip()
            base_dir.mkdir(parents=True, exist_ok=True)

            if file_name and str(file_name).lower() not in ["null", "none", ""]:
                clean_filename = str(file_name).strip()
                if "." not in clean_filename:
                    clean_filename += ".txt"
                final_file_path = base_dir / clean_filename
                
                if clean_filename.lower().endswith(".docx"):
                    try:
                        from docx import Document
                        doc = Document()
                        if file_content:
                            doc.add_paragraph(file_content)
                        doc.save(str(final_file_path))
                    except ImportError:
                        final_file_path.write_text(file_content or "", encoding="utf-8")
                else:
                    final_file_path.write_text(file_content or "", encoding="utf-8")
                    
                return f"SENDFILE:{final_file_path}|📄 Created {final_file_path.name}"
            return f"📁 Folder created successfully at: {base_dir}"

        elif action in ["delete_folder", "remove_folder"]:
            target = resolve_target(target_str or folder_name or command)
            if not target.exists():
                return f"⚠️ Folder not found: {target}"
            if target.is_dir():
                shutil.rmtree(target)
                return f"🗑️ Successfully deleted folder and all contents: {target}"
            target.unlink()
            return f"🗑️ Successfully deleted file: {target.name}"

        elif action in ["delete_file", "remove_file"]:
            target = resolve_target(target_str or file_name or command)
            if not target.exists():
                return f"⚠️ File not found: {target}"
            if target.is_dir():
                shutil.rmtree(target)
                return f"🗑️ Successfully deleted folder: {target}"
            target.unlink()
            return f"🗑️ Successfully deleted file: {target.name}"


        elif action in ["close_app", "close_window"]:
            return close_window_or_tab(command or target_str or "")

        elif action == "minimize_app":
            return minimize_window_or_tab(command or target_str or "")

        elif action == "system_power":
            return handle_system_power(command or target_str or "")

        elif action == "token_quota":
            import memory_store as mem
            metrics = mem.get_engine_metric("API1")
            tokens = metrics.get("tokens_consumed", 0) if metrics else 0
            limit = 1500000
            left = limit - tokens
            pct = max(0, (left / limit) * 100)
            return f"📊 **Token Quota Status**\n\n• Consumed: {tokens:,}\n• Estimated Limit: {limit:,} (Daily)\n• Estimated Remaining: {pct:.1f}% ({left:,} tokens left)"

        elif action == "minimize_all":
            import pyautogui
            pyautogui.hotkey("win", "d")
            time.sleep(0.5)
            return "🖥️ Desktop minimized."

        elif action == "open_app":
            return launch_app_or_protocol(command or target_str or "")

        elif action == "play_youtube":
            raw = (command or "").strip()
            clean_query = re.sub(
                r"^(play_youtube|open\s+youtube|play\s+youtube|play|search\s+for|search)\s*",
                "", raw, flags=re.IGNORECASE
            ).strip()
            if not clean_query or clean_query.lower() in ["youtube", "play_youtube", ""]:
                webbrowser.open("https://www.youtube.com")
                return "▶️ Opened YouTube in your browser."
            return youtube_visual_search(clean_query)

        elif action == "youtube_visual_search":
            return youtube_visual_search(command or "")

        elif action == "youtube_scroll":
            return browser_scroll_and_screenshot()

        elif action == "youtube_click":
            num = int(command or 1)
            import pyautogui, ctypes
            old_fs = pyautogui.FAILSAFE
            pyautogui.FAILSAFE = False
            try:
                w, h = pyautogui.size()
                def foreach_window(hwnd, lParam):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                        if "youtube" in buff.value.lower():
                            ctypes.windll.user32.ShowWindow(hwnd, 3)
                            ctypes.windll.user32.SetForegroundWindow(hwnd)
                            return False
                    return True
                EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
                ctypes.windll.user32.EnumWindows(EnumWindowsProc(foreach_window), 0)
                import time as _t
                _t.sleep(0.3)
                
                global youtube_picker_targets
                if num in youtube_picker_targets:
                    x, y = youtube_picker_targets[num]
                else:
                    x = int(w * 0.4)
                    y = int(h * (0.35 + (num - 1) * 0.22))
                    
                pyautogui.moveTo(x, y, duration=0.4)
                pyautogui.click()
                return f"▶️ Playing video #{num}."
            finally:
                pyautogui.FAILSAFE = old_fs


        elif action == "play_spotify":
            return play_spotify_with_autoplay(command or "")

        elif action == "web_search":
            query = command or target_str or ""
            if "amazon" in query.lower():
                webbrowser.open(f"https://www.amazon.in/s?k={urllib.parse.quote(query)}")
            else:
                webbrowser.open(f"https://www.google.com/search?q={urllib.parse.quote(query)}")
            try:
                from duckduckgo_search import DDGS
                with DDGS() as ddgs:
                    results = [
                        f"🔹 **{r['title']}**\n{r['body']}\n🔗 {r['href']}"
                        for r in ddgs.text(query, max_results=3)
                    ]
                return (
                    f"🌐 Search results for '{query}':\n\n" + "\n\n".join(results)
                    if results else f"🌐 Opened search results in browser for '{query}'."
                )
            except Exception:
                return f"🌐 Search opened in browser for: '{query}'"

        elif action == "take_screenshot":
            return take_desktop_screenshot()

        elif action == "list_files":
            target = resolve_target(target_str or command)
            search_query = file_name or folder_name
            if not search_query and command and command != target_str:
                search_query = command
                
            if search_query:
                # User is asking "is there a file named X"
                if not target.exists() or not target.is_dir():
                    target = DESKTOP_DIR
                if target.exists() and target.is_dir():
                    s_lower = search_query.lower()
                    matches = [i for i in os.listdir(target) if s_lower in i.lower()]
                    if not matches:
                        return f"⚠️ No file named '{search_query}' was found in {target}."
                    return f"🔍 Found matching items in {target}:\n" + "\n".join(f"- {i}" for i in matches[:35])
            
            if not target.exists():
                return f"Path does not exist: {target}"
            if not target.is_dir():
                return f"⚠️ Path is a file, not a folder: {target}. Cannot list contents."
            items = os.listdir(target)
            return f"📁 Items in {target}:\n" + "\n".join(f"- {i}" for i in items[:35])

        elif action == "list_windows":
            windows = get_open_windows_and_tabs()
            return (
                "🪟 Active Windows & Tabs:\n" + "\n".join(f"• {w}" for w in windows[:15])
                if windows else "No active windows detected."
            )

        elif action == "set_memory_trigger":
            import memory_store as mem
            trigger_phrase = (intent.get("command") or "").strip().lower()
            payload        = intent.get("summary") or "Triggered!"
            user_id        = intent.get("_user_id")
            if trigger_phrase:
                try:
                    uid = int(user_id) if user_id else 0
                    mem.set_trigger(uid, trigger_phrase, payload)
                    return f"🔔 Trigger set! I'll remind you when you say: '{trigger_phrase}'"
                except Exception as e:
                    return f"⚠️ Could not save trigger: {e}"
            return "⚠️ No trigger phrase provided."

        elif action == "create_zip":
            sources = intent.get("source_paths") or []
            if isinstance(sources, str):
                sources = [s.strip() for s in sources.split(",") if s.strip()]
            
            matched_sources = []
            base_dir = resolve_target(target_str) if target_str else DESKTOP_DIR
            
            if not sources and command:
                sources = [command]
            elif not sources and target_str:
                resolved_target = resolve_target(target_str)
                if resolved_target.exists():
                    sources = [str(resolved_target)]
                    target_str = None
                else:
                    sources = [target_str]
                    target_str = None
            elif not sources and folder_name:
                sources = [folder_name]
                
            for s in sources:
                p = Path(_sanitise_path(s))
                
                if target_str and not p.is_absolute():
                    test_p = base_dir / s
                    if test_p.exists():
                        p = test_p

                if not p.is_absolute():
                    p = resolve_target(s)
                    
                if p.exists():
                    matched_sources.append(str(p))
                    continue
                
                # Fuzzy match in parent directory
                parent_dir = p.parent
                if parent_dir.exists() and parent_dir.is_dir():
                    found = False
                    s_lower = p.name.lower()
                    for item in os.listdir(parent_dir):
                        if s_lower in item.lower() or item.lower() in s_lower:
                            matched_sources.append(str(parent_dir / item))
                            found = True
                            break
                    if not found:
                        return f"⚠️ No file or folder found matching '{p.name}' in {parent_dir}"
                else:
                    return f"⚠️ No file or folder found matching '{s}'"
            
            archive_name = intent.get("file_name") or intent.get("command") or "aria_archive"
            return create_zip_archive(matched_sources, archive_name, target_str)

        elif action == "volume_control":
            vol_action = (intent.get("command") or "up").lower()
            level_raw  = intent.get("summary") or ""
            level      = None
            m = re.search(r"\d+", str(level_raw))
            if m:
                level = int(m.group())
            return control_volume(vol_action, level)

        elif action == "convert_to_pdf":
            source = _sanitise_path(target_str or command or "")
            return convert_to_pdf(source, intent.get("folder_name"))

        elif action == "gui_click":
            coords = intent.get("command") or ""
            m = re.findall(r"\d+", coords)
            x, y = (int(m[0]), int(m[1])) if len(m) >= 2 else (None, None)
            return gui_click(x, y, element_text=intent.get("summary"))

        elif action == "gui_type":
            return gui_type(command or "")

        elif action == "whatsapp_message":
            import pyautogui
            import pyperclip
            
            contact = intent.get("_wa_contact") or intent.get("command") or ""
            body    = intent.get("_wa_body") or intent.get("file_content") or ""
            digits = re.sub(r"\D", "", contact)
            if digits:
                encoded_body = urllib.parse.quote(body)
                webbrowser.open(f"https://wa.me/{digits}?text={encoded_body}")
                return f"📱 WhatsApp opened for '{contact}'. Message: \"{body[:60]}\""
            else:
                try:
                    os.startfile("whatsapp:")
                except Exception:
                    webbrowser.open("https://web.whatsapp.com")
                
                time.sleep(4.0)
                pyautogui.hotkey('ctrl', 'f')
                time.sleep(0.5)
                pyautogui.typewrite(contact, interval=0.05)
                time.sleep(0.5)
                pyautogui.press('enter')
                time.sleep(3.0)
                
                if body:
                    pyperclip.copy(body)
                    pyautogui.hotkey('ctrl', 'v')
                    time.sleep(0.5)
                    pyautogui.press('enter')
                    
                return f"✅ WhatsApp message blind-sent to '{contact}'."

        elif action == "media_control":
            cmd_lower = (command or "toggle").lower()
            if cmd_lower == "close":
                import pyautogui
                old_fs = pyautogui.FAILSAFE
                pyautogui.FAILSAFE = False
                try:
                    pyautogui.hotkey("alt", "f4")
                    return "🛑 Closed media window."
                finally:
                    pyautogui.FAILSAFE = old_fs
                
            if cmd_lower == "seekf":
                import pyautogui
                old_fs = pyautogui.FAILSAFE
                pyautogui.FAILSAFE = False
                try:
                    pyautogui.press("right")
                    return "⏩ Seek forward."
                finally:
                    pyautogui.FAILSAFE = old_fs
            if cmd_lower == "seekb":
                import pyautogui
                old_fs = pyautogui.FAILSAFE
                pyautogui.FAILSAFE = False
                try:
                    pyautogui.press("left")
                    return "⏪ Seek backward."
                finally:
                    pyautogui.FAILSAFE = old_fs

            if cmd_lower in ("play", "pause", "toggle"):
                import pyautogui
                EnumWindows = ctypes.windll.user32.EnumWindows
                EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
                GetWindowText = ctypes.windll.user32.GetWindowTextW
                GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
                IsWindowVisible = ctypes.windll.user32.IsWindowVisible
                yt_hwnds = []
                def find_yt(hwnd, lParam):
                    if IsWindowVisible(hwnd) and GetWindowTextLength(hwnd) > 0:
                        buff = ctypes.create_unicode_buffer(GetWindowTextLength(hwnd) + 1)
                        GetWindowText(hwnd, buff, len(buff))
                        if "youtube" in buff.value.lower():
                            yt_hwnds.append(hwnd)
                    return True
                EnumWindows(EnumWindowsProc(find_yt), 0)
                if yt_hwnds:
                    try:
                        ctypes.windll.user32.ShowWindow(yt_hwnds[0], 9)
                        ctypes.windll.user32.SetForegroundWindow(yt_hwnds[0])
                        time.sleep(0.15)
                        pyautogui.press("k")
                        return "⏯ YouTube play/pause toggled."
                    except Exception:
                        pass

            _VK = {
                "play":  0xB3, "pause": 0xB3, "toggle": 0xB3,
                "next":  0xB0, "prev":  0xB1, "previous": 0xB1,
                "stop":  0xB2,
            }
            vk = _VK.get(cmd_lower, 0xB3)
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            labels = {"play": "▶️ Playing", "pause": "⏸ Paused", "toggle": "⏯ Toggled",
                      "next": "⏭ Next track", "prev": "⏮ Previous track",
                      "previous": "⏮ Previous track", "stop": "⏹ Stopped"}
            return labels.get(cmd_lower, "⏯ Media key sent.")


        elif action == "antigravity_orchestrate":
            import asyncio
            from antigravity_orchestrator import run_orchestration
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Since execute_tool is often run in an executor, loop.run_until_complete won't work if it's the main loop.
                # Actually run_orchestration is async, and we're inside a sync function `execute_tool`.
                # If we're inside a thread pool, we can create a new loop.
                new_loop = asyncio.new_event_loop()
                return new_loop.run_until_complete(run_orchestration(intent))
            else:
                return loop.run_until_complete(run_orchestration(intent))


        # ── Project dev-task (Gemini-powered code editing + screenshot preview) ──
        elif action == "dev_task":
            project_name = (command or "").strip()
            task_description = (file_content or "").strip()
            if not project_name:
                return "⚠️ Please specify which project to edit (e.g. 'update certify — add dark mode')."
            if not task_description:
                return "⚠️ Please describe what you want to change."
            try:
                import asyncio as _asyncio
                import dev_task_tool as _dt
                result = _asyncio.run(_dt.run_dev_task(project_name, task_description, want_preview=True))
                out = result["summary"]
                if result.get("screenshot_path"):
                    out = f"SCREENSHOT:{result['screenshot_path']}|{out}"
                return out
            except Exception as e:
                import traceback
                return f"❌ Dev task failed: {e}\n{traceback.format_exc()}"

        # ── Certificate workflow ─────────────────────────────────────────────────
        elif action == "cert_workflow":
            sub = (command or "start").strip().lower()
            if sub == "start":
                return (
                    "📜 **Certificate Workflow Started!**\n\n"
                    "Please send me:\n"
                    "1. Your **PDF certificate template**\n"
                    "2. Your **CSV file** with recipient names (and optionally emails)\n\n"
                    "You can send them in any order. I'll parse the CSV and generate a sample for you to review first."
                )
            return f"⚠️ Unknown cert_workflow command: {sub}"

        # ── List registered projects ─────────────────────────────────────────────
        elif action == "list_projects":
            try:
                import dev_task_tool as _dt
                return _dt.list_projects()
            except Exception as e:
                return f"❌ Could not list projects: {e}"

        # ── ARIA System Janitor (Disk Cleanup & Cache Purge) ────────────────────
        elif action in ("janitor_clean", "system_cleanup"):
            try:
                import sys
                janitor_dir = (Path(__file__).parent.parent / "aria-janitor").resolve()
                if str(janitor_dir) not in sys.path:
                    sys.path.insert(0, str(janitor_dir))
                import planner as _jp
                import executor as _je
                import audit_logger as _ja

                goal = (command or file_content or intent.get("summary") or "Clean safe temp caches and purge installer downloads").strip()
                try:
                    plan = _jp.generate_plan_sync(goal)
                except Exception as _plan_err:
                    import logging
                    logging.warning("[Janitor] Plan generation failed: %s. Using default safe plan.", _plan_err)
                    plan = _jp.get_default_safe_plan()


                session = _ja.start_session(goal, dry_run=False)
                results = _je.execute_plan(plan, dry_run=False, auto_approve=True)
                for r in results:
                    _ja.log_result(r, session_md_path=session["md_path"])
                summary_data = _ja.finish_session(session, results)

                reclaimed = summary_data["total_reclaimed_gb"]
                details = []
                for r in results:
                    status = r.status_icon
                    rec = f"+{r.space_reclaimed_gb:.2f}GB" if r.space_reclaimed_gb else "0GB"
                    details.append(f"{status} {r.action_summary} ({rec})")

                return (
                    f"🧹 **Janitor Cleanup Finished!**\n\n"
                    f"Total Reclaimed: **{reclaimed:.3f} GB**\n"
                    f"Session Log: `{summary_data.get('log_path', 'saved')}`\n\n"
                    + "\n".join(details)
                )
            except Exception as e:
                import traceback
                return f"❌ Janitor cleanup failed: {e}\n{traceback.format_exc()}"
        elif action in ("start_voice_assistant", "launch_voice_assistant", "voice_assistant"):
            return launch_voice_assistant()

        elif action in ("stop_voice_assistant", "kill_voice_assistant", "close_voice_assistant"):
            return stop_voice_assistant()

        # ── Personal Assistant: Todos Management ──────────────────────────────
        elif action in ("add_todo", "create_todo"):
            import memory_store as om
            task = (command or file_content or intent.get("summary") or "").strip()
            return om.add_todo(task)

        elif action in ("list_todos", "show_todos", "get_todos"):
            import memory_store as om
            todos = om.get_todos("all")
            if not todos:
                return "📋 **Your Obsidian Todo list is currently empty!**\nSay *'add [task] to my todo list'* to add one."
            pending = [t for t in todos if not t["completed"]]
            done = [t for t in todos if t["completed"]]
            lines = ["📋 **Your Obsidian Todo List:**\n"]
            if pending:
                lines.append(f"⏳ **Pending ({len(pending)}):**")
                for t in pending:
                    lines.append(f"• `- [ ]` {t['task']}")
            else:
                lines.append("🎉 *No pending tasks! All caught up.*")
            if done:
                lines.append(f"\n✅ **Completed ({len(done)}):**")
                for t in done[:5]:
                    lines.append(f"• `- [x]` {t['task']}")
                if len(done) > 5:
                    lines.append(f"• ... and {len(done)-5} more in [[Todos]]")
            return "\n".join(lines)

        elif action in ("complete_todo", "done_todo"):
            import memory_store as om
            task = (command or file_content or intent.get("summary") or "").strip()
            return om.complete_todo(task)

        elif action in ("remove_todo", "delete_todo"):
            import memory_store as om
            task = (command or file_content or intent.get("summary") or "").strip()
            return om.remove_todo(task)

        # ── Personal Assistant: Reminders & Schedule ──────────────────────────
        elif action in ("add_reminder", "set_reminder"):
            import memory_store as om
            text = (command or file_content or "").strip()
            due = (folder_name or intent.get("summary") or "").strip() or None
            return om.add_reminder(text, due_time=due)

        elif action in ("list_reminders", "show_reminders", "get_reminders"):
            import memory_store as om
            reminders = om.get_reminders(active_only=False)
            if not reminders:
                return "⏰ **No reminders configured in Obsidian!**\nSay *'remind me to [task]'* to set one."
            active = [r for r in reminders if r["active"]]
            dismissed = [r for r in reminders if not r["active"]]
            lines = ["⏰ **Your Obsidian Reminders:**\n"]
            if active:
                lines.append(f"🔔 **Active ({len(active)}):**")
                for r in active:
                    lines.append(f"• {r['text']}")
            else:
                lines.append("🔕 *No active reminders right now.*")
            if dismissed:
                lines.append(f"\n🔕 **Past/Dismissed ({len(dismissed)}):**")
                for r in dismissed[:3]:
                    lines.append(f"• {r['text']}")
            return "\n".join(lines)

        elif action in ("dismiss_reminder", "cancel_reminder"):
            import memory_store as om
            q = (command or file_content or "").strip()
            return om.dismiss_reminder(q)

        # ── Personal Assistant: Notes & Profile ───────────────────────────────
        elif action in ("save_note", "take_note", "create_note"):
            import memory_store as om
            title = (file_name or folder_name or "Quick Note").strip()
            content = (file_content or command or intent.get("summary") or "").strip()
            return om.save_note(title, content)

        elif action in ("show_profile", "get_profile"):
            import memory_store as om
            facts = om.get_all_facts()
            name = facts.get("user_name", "User")
            mode = facts.get("active_model_mode", "CLOUD")
            model = facts.get("active_llm_model", "gemini-2.5-flash")
            vault = str(om.get_vault_path())
            lines = [
                f"👤 **Personal Assistant Profile (Obsidian):**\n",
                f"• **Name:** <code>{name}</code>",
                f"• **Active AI Engine:** <code>{mode}</code> (<code>{model}</code>)",
                f"• **Obsidian Vault:** <code>{vault}</code>",
                f"• **Database Engine:** <i>Pure Obsidian Markdown (SQLite removed)</i>",
            ]
            custom_facts = [f"• `{k}`: {v}" for k, v in facts.items() if k not in ("user_name", "active_model_mode", "active_llm_model") and not k.startswith("ag_")]
            if custom_facts:
                lines.append("\n<b>Known Facts:</b>")
                lines.extend(custom_facts[:8])
            return "\n".join(lines)

        # ── Obsidian Vault Search & Notes ─────────────────────────────────────
        elif action in ("sync_obsidian", "export_obsidian", "connect_obsidian"):
            import memory_store as om
            facts = om.get_all_facts()
            todos = om.get_todos("all")
            reminders = om.get_reminders(active_only=False)
            vault_dir = om.get_vault_path()
            return (
                "🌌 **Aria Obsidian Memory Vault Active!**\n\n"
                f"• 👤 **Facts & Profile:** {len(facts)} items\n"
                f"• 📋 **Todo Tasks:** {len(todos)} tasks\n"
                f"• ⏰ **Reminders:** {len(reminders)} reminders\n"
                f"• 💾 **Storage Engine:** <i>Pure Markdown (SQLite removed)</i>\n\n"
                f"📁 **Vault Location:** `{vault_dir}`\n"
                "Everything you say or change is saved directly into Obsidian!"
            )

        elif action == "search_obsidian":
            try:
                import memory_store as om
                q = (command or file_content or intent.get("summary") or "").strip()
                if not q:
                    return "⚠️ Please specify what to search for in Obsidian."
                matches = om.search_vault(q, max_results=5)
                if not matches:
                    return f"🔍 No notes found in Obsidian matching **'{q}'**."
                lines = [f"🔍 **Found {len(matches)} Obsidian note(s) matching '{q}':**\n"]
                for m in matches:
                    lines.append(f"• 📄 **[[{m['note']}]]** (`{m['rel_path']}`)\n  > {m['snippet']}")
                return "\n".join(lines)
            except Exception as e:
                return f"❌ Failed to search Obsidian: {e}"

        elif action == "read_obsidian_note":
            try:
                import memory_store as om
                note_name = (command or file_name or "").strip()
                if not note_name:
                    return "⚠️ Please specify which note to read from Obsidian."
                content = om.read_note(note_name)
                if not content:
                    return f"📂 Note **'{note_name}'** not found in Obsidian vault."
                if len(content) > 3000:
                    content = content[:2900] + "\n\n... *(truncated for Telegram)*"
                return f"📄 **Note: `{note_name}`**\n\n{content}"
            except Exception as e:
                return f"❌ Failed to read note from Obsidian: {e}"

        return f"Action '{action}' recognized but has no execution handler."



    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logging.error("[Aria] Tool execution error: %s", tb)

        # Translate common errors into user-friendly messages
        err_str = str(e)
        if "UnboundLocalError" in err_str or "NameError" in err_str:
            friendly = "😕 Something went wrong internally — a component wasn't loaded properly. Try again, and if it keeps happening, let Hrushi know."
        elif "FileNotFoundError" in type(e).__name__ or "No such file" in err_str:
            friendly = f"📂 Couldn't find that file or folder. Double-check the name and try again."
        elif "PermissionError" in type(e).__name__ or "Access is denied" in err_str:
            friendly = "🔒 I don't have permission to do that. The file might be in use or protected."
        elif "TimeoutError" in type(e).__name__ or "timed out" in err_str.lower():
            friendly = "⏱️ That took too long and timed out. Try again in a bit."
        elif "ConnectionError" in type(e).__name__ or "connection" in err_str.lower():
            friendly = "🌐 Couldn't connect — check your internet or make sure the service is running."
        elif "ModuleNotFoundError" in type(e).__name__ or "No module named" in err_str:
            module = err_str.split("'")[1] if "'" in err_str else "unknown"
            friendly = f"🧩 Missing a required package: '{module}'. Ask Hrushi to install it."
        elif "zipfile" in err_str.lower() or "zip" in err_str.lower():
            friendly = f"📦 Something went wrong creating/reading the archive. The file might be corrupted or in use."
        else:
            friendly = f"😕 Something went wrong: {err_str[:150]}"

        return f"{friendly}\n\n<i>🔧 Tech detail: {type(e).__name__}: {err_str[:200]}</i>"


def _wrap_result(raw_result: str) -> dict:
    """Wraps legacy tool returns into a structured envelope."""
    success = True
    return_code = 0
    stdout = str(raw_result)
    stderr = ""
    artifacts = []
    
    if stdout.startswith("Execution error") or "failed" in stdout.lower() or "not found" in stdout.lower() or stdout.startswith("⚠️ Could not") or "unsupported" in stdout.lower():
        success = False
        return_code = 1
        stderr = stdout
        stdout = ""
        
    elif stdout.startswith("SENDFILE:"):
        parts = stdout.split("SENDFILE:", 1)[1].split("|", 1)
        path = parts[0].strip()
        stdout = parts[1].strip() if len(parts) > 1 else "File created."
        artifacts.append(path)
        
    elif stdout.startswith("SCREENSHOT:"):
        path = stdout.split("SCREENSHOT:", 1)[1].strip()
        stdout = "Screenshot captured."
        artifacts.append(path)
        
    elif stdout.startswith("YTPICKER:"):
        parts = stdout.split("YTPICKER:", 1)[1].split("|", 1)
        path = parts[0].strip()
        stdout = parts[1].strip() if len(parts) > 1 else "YouTube picker created."
        artifacts.append(path)
        
    elif "Converted to PDF: " in stdout:
        path = stdout.split("Converted to PDF: ")[1].strip()
        artifacts.append(path)
        
    return {
        "success": success,
        "return_code": return_code,
        "stdout": stdout,
        "stderr": stderr,
        "artifacts": artifacts,
    }

async def execute_tool_structured(intent: dict) -> dict:
    """Parallel entry point that guarantees a structured dictionary return."""
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        
        # Check if we are already in an executor or synchronous context without a running loop
        if not loop.is_running():
            raw = execute_tool(intent)
        else:
            raw = await loop.run_in_executor(None, execute_tool, intent)
                
        return _wrap_result(raw)
    except Exception as e:
        return {
            "success": False,
            "return_code": 1,
            "stdout": "",
            "stderr": f"Exception in tool execution: {e}",
            "artifacts": []
        }