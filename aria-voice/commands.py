# -*- coding: utf-8 -*-
# ─── commands.py ──────────────────────────────────────────
# Handles all PC-level actions for Aria.
# Receives (action, params) from assistant.py and executes them.
#
# Key fixes vs previous version:
#  1. screenshot   — silent PIL ImageGrab. Zero cmd/console window popup.
#  2. open_app     — resolves real .exe paths; falls back to MS-Store URIs
#                    then web. No more subprocess(string) → cmd.exe flash.
#  3. open_game    — added to execute_command.
#  4. spotify_play — launches Spotify URI then fires VK_MEDIA_PLAY_PAUSE.
#  5. WhatsApp     — opens app natively; wa.me deeplink for direct messages.
#  6. volume       — uses pycaw (Windows Core Audio) with nircmd fallback.
#  7. zip_files    — compresses sources into a .zip archive.
#  8. convert_pdf  — converts .docx / .txt files to PDF.

import os
import re
import glob
import subprocess
import webbrowser
import datetime
import time
import ctypes
import zipfile
from pathlib import Path
from urllib.parse import quote
from rich.console import Console

from config import ALLOWED_ACTIONS

console = Console()


# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════

def open_website(link: str):
    """Opens a URL in the default browser (no visible console window)."""
    try:
        webbrowser.open(link)
    except Exception as e:
        console.print(f"[bold yellow][system]: couldn't open link — {e}[/bold yellow]")


# ─── App paths: common install locations ──────────────────
# Maps a short name → list of candidate exe paths (checked in order).
# If none exist, falls back to MS-Store URI, then web URL.
_APP_EXE_CANDIDATES = {
    "opera": [
        os.path.expanduser(r"~\AppData\Local\Programs\Opera\opera.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\Opera GX\opera.exe"),
        r"C:\Program Files\Opera\opera.exe",
        r"C:\Program Files (x86)\Opera\opera.exe",
        r"C:\Program Files\Opera GX\opera.exe",
    ],
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "brave": [
        os.path.expanduser(r"~\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe"),
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
    "vlc": [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ],
    "discord": [
        os.path.expanduser(r"~\AppData\Local\Discord\app-*\Discord.exe"),  # glob
        os.path.expanduser(r"~\AppData\Local\Discord\Discord.exe"),
    ],
    "steam": [
        r"C:\Program Files (x86)\Steam\steam.exe",
        r"C:\Program Files\Steam\steam.exe",
    ],
    "notepad++": [
        r"C:\Program Files\Notepad++\notepad++.exe",
        r"C:\Program Files (x86)\Notepad++\notepad++.exe",
    ],
}

# MS-Store app shell URIs (for apps installed from the Store)
_STORE_URIS = {
    "whatsapp":   "shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!WhatsApp",
    "spotify":    "shell:AppsFolder\\SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
    "calculator": "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
    "settings":   "ms-settings:",
    "notepad":    "notepad.exe",
    "taskmgr":    "taskmgr.exe",
    "wordpad":    "write.exe",
}

# Web fallbacks for apps that have no installed candidate
_WEB_FALLBACKS = {
    "whatsapp": "https://web.whatsapp.com",
    "spotify":  "https://open.spotify.com",
}


def _resolve_exe(candidates: list[str]) -> str | None:
    """
    Iterates through candidate paths (supports glob * in path).
    Returns the first path that exists, or None.
    """
    for path in candidates:
        if "*" in path:
            matches = sorted(glob.glob(path))
            if matches:
                return matches[-1]   # pick latest version
        elif os.path.exists(path):
            return path
    return None


def open_app(app_name: str):
    """
    Launches a Windows app smartly:
      1. Known exe paths  → subprocess.Popen([exe])  (no console window)
      2. MS-Store URI     → os.startfile(uri)
      3. Web fallback     → webbrowser.open(url)
      4. Give up + log
    """
    name = app_name.lower().strip()
    console.print(f"[dim green][system]: opening app '{name}'...[/dim green]")

    # 1. Try known exe candidates
    if name in _APP_EXE_CANDIDATES:
        exe = _resolve_exe(_APP_EXE_CANDIDATES[name])
        if exe:
            try:
                subprocess.Popen(
                    [exe],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                )
                return
            except Exception as e:
                console.print(f"[dim yellow][system]: exe launch failed — {e}[/dim yellow]")

    # 2. Try MS-Store URIs
    if name in _STORE_URIS:
        try:
            os.startfile(_STORE_URIS[name])
            return
        except Exception as e:
            console.print(f"[dim yellow][system]: store URI failed — {e}[/dim yellow]")

    # 3. Try web fallback
    if name in _WEB_FALLBACKS:
        open_website(_WEB_FALLBACKS[name])
        return

    console.print(f"[bold yellow][system]: couldn't find '{name}'. Add its exe path to _APP_EXE_CANDIDATES.[/bold yellow]")


def open_folder(folder_name: str):
    """Opens a known folder by nickname."""
    folders = {
        "downloads": os.path.expanduser("~\\Downloads"),
        "documents": os.path.expanduser("~\\Documents"),
        "desktop":   os.path.expanduser("~\\Desktop"),
        "pictures":  os.path.expanduser("~\\Pictures"),
        "music":     os.path.expanduser("~\\Music"),
        "videos":    os.path.expanduser("~\\Videos"),
        "d drive":   "D:\\",
        "project":   "D:\\AI-AIS",
    }
    try:
        path = folders.get(folder_name.lower(), folder_name)
        os.startfile(path)
    except Exception as e:
        console.print(f"[bold yellow][system]: couldn't open folder '{folder_name}' — {e}[/bold yellow]")


def take_screenshot() -> str:
    """
    Captures the full screen silently (no window flash, no user clicks).
    Uses PIL ImageGrab — pure Python, zero subprocess, zero console popup.
    Saves to Desktop with a timestamp filename. Returns the save path.
    """
    try:
        from PIL import ImageGrab
        ts        = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_dir  = os.path.expanduser("~\\Desktop")
        save_path = os.path.join(save_dir, f"aria_screenshot_{ts}.png")
        img       = ImageGrab.grab(all_screens=False)  # captures primary monitor
        img.save(save_path)
        console.print(f"[dim green][system]: screenshot saved → {save_path}[/dim green]")
        return save_path
    except ImportError:
        console.print("[bold yellow][system]: Pillow not installed. Run: pip install pillow[/bold yellow]")
        return ""
    except Exception as e:
        console.print(f"[bold yellow][system]: screenshot failed — {e}[/bold yellow]")
        return ""


def set_volume(level: int):
    """
    Sets system master volume (0-100) using pycaw (Windows Core Audio API).
    Falls back to nircmd.exe if pycaw is not installed.
    """
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from comtypes import CLSCTX_ALL
        devices   = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume    = interface.QueryInterface(IAudioEndpointVolume)
        scalar    = max(0.0, min(1.0, level / 100.0))
        volume.SetMasterVolumeLevelScalar(scalar, None)
        console.print(f"[dim green][system]: volume set to {level}% via pycaw[/dim green]")
    except ImportError:
        try:
            subprocess.call(
                ["nircmd.exe", "setsysvolume", str(int(level * 655.35))],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception:
            console.print("[dim yellow][system]: nircmd.exe not found — drop it in D:\\AI-AIS\\ for volume control[/dim yellow]")
    except Exception as e:
        console.print(f"[dim yellow][system]: volume set failed — {e}[/dim yellow]")


def zip_files(source_paths: list[str], archive_name: str, dest_dir: str | None = None) -> str:
    """
    Compresses one or more files/folders into a ZIP archive.
    Returns the path to the created archive.
    """
    dest = Path(dest_dir).resolve() if dest_dir else Path.home() / "Desktop"
    dest.mkdir(parents=True, exist_ok=True)
    if not archive_name.lower().endswith(".zip"):
        archive_name += ".zip"
    zip_path = dest / archive_name
    added = []
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for sp in source_paths:
                p = Path(sp.strip())
                if p.is_dir():
                    for f in p.rglob("*"):
                        if f.is_file():
                            zf.write(f, f.relative_to(p.parent))
                            added.append(f.name)
                elif p.is_file():
                    zf.write(p, p.name)
                    added.append(p.name)
        console.print(f"[dim green][system]: ZIP created → {zip_path} ({len(added)} files)[/dim green]")
        return str(zip_path)
    except Exception as e:
        console.print(f"[bold yellow][system]: zip failed — {e}[/bold yellow]")
        return ""


def convert_to_pdf(source_path: str, dest_dir: str | None = None) -> str:
    """
    Converts a .docx or .txt file to PDF.
    Uses docx2pdf for Word files; reportlab for plain text.
    Returns the path to the output PDF.
    """
    src = Path(source_path.strip())
    if not src.exists():
        console.print(f"[bold yellow][system]: source not found — {src}[/bold yellow]")
        return ""
    dest    = Path(dest_dir).resolve() if dest_dir else src.parent
    dest.mkdir(parents=True, exist_ok=True)
    pdf_out = dest / (src.stem + ".pdf")
    ext     = src.suffix.lower()
    try:
        if ext == ".docx":
            from docx2pdf import convert
            convert(str(src), str(pdf_out))
        elif ext in [".txt", ".md"]:
            from reportlab.pdfgen import canvas as rl_canvas
            from reportlab.lib.pagesizes import A4
            c = rl_canvas.Canvas(str(pdf_out), pagesize=A4)
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
        else:
            console.print(f"[bold yellow][system]: unsupported format for PDF conversion: {ext}[/bold yellow]")
            return ""
        console.print(f"[dim green][system]: PDF created → {pdf_out}[/dim green]")
        return str(pdf_out)
    except ImportError as ie:
        console.print(f"[bold yellow][system]: missing library — {ie}[/bold yellow]")
        return ""
    except Exception as e:
        console.print(f"[bold yellow][system]: PDF conversion failed — {e}[/bold yellow]")
        return ""


# ═══════════════════════════════════════════════════════════
#  MAIN EXECUTOR
# ═══════════════════════════════════════════════════════════

def execute_command(action: str, params: dict) -> bool:
    """
    Receives (action, params) from Aria's brain and executes the
    corresponding PC action. Returns True if something ran.
    """
    if action not in ALLOWED_ACTIONS or action == "none":
        return False

    if action in ["shutdown", "restart", "sleep"]:
        console.print(f"[bold red][system]: executing {action} in 5 seconds — Ctrl+C to cancel.[/bold red]")

    # ── YOUTUBE ───────────────────────────────────────────
    if action == "youtube_open":
        open_website("https://youtube.com")

    elif action == "youtube_search":
        open_website(f"https://www.youtube.com/search?q={quote(params.get('query', ''))}")

    elif action == "youtube_play":
        q = f"{params.get('query', '')} {params.get('artist', '')}".strip()
        open_website(f"https://www.youtube.com/search?q={quote(q)}")

    # ── SPOTIFY ───────────────────────────────────────────
    elif action == "spotify_open":
        open_app("spotify")

    elif action == "spotify_play":
        query = params.get("query", "")
        # Launch Spotify via URI so it navigates directly to the search result
        encoded = quote(query)
        try:
            os.startfile(f"spotify:search:{encoded}")
        except Exception:
            open_website(f"https://open.spotify.com/search/{encoded}")
        # Wait for Spotify to focus, then fire VK_MEDIA_PLAY_PAUSE
        time.sleep(2.5)
        try:
            VK_MEDIA_PLAY_PAUSE = 0xB3
            KEYEVENTF_KEYUP     = 0x0002
            ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
            time.sleep(0.05)
            ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_KEYUP, 0)
            console.print("[dim green][system]: Spotify play keystroke sent[/dim green]")
        except Exception as ke:
            console.print(f"[dim yellow][system]: play keystroke failed — {ke}[/dim yellow]")

    # ── WHATSAPP ──────────────────────────────────────────
    elif action == "whatsapp_open":
        open_app("whatsapp")

    elif action == "whatsapp_message":
        contact = params.get("contact", "")
        message = params.get("message", "")
        # If contact looks like a phone number, use wa.me deeplink
        digits = re.sub(r"\D", "", contact)
        if digits:
            open_website(f"https://wa.me/{digits}?text={quote(message)}")
        else:
            # Open WhatsApp app and paste message (user selects contact)
            open_app("whatsapp")
            if message:
                open_website(f"https://web.whatsapp.com/send?text={quote(message)}")

    elif action == "whatsapp_call":
        digits = re.sub(r"\D", "", params.get("contact", ""))
        if digits:
            open_website(f"https://wa.me/{digits}")
        else:
            open_app("whatsapp")

    # ── INSTAGRAM ─────────────────────────────────────────
    elif action == "instagram_open":
        open_website("https://instagram.com")

    elif action == "instagram_reels":
        open_website("https://www.instagram.com/reels/")

    elif action == "instagram_dm":
        open_website("https://www.instagram.com/direct/inbox/")

    elif action == "instagram_profile":
        open_website(f"https://www.instagram.com/{params.get('username', '')}/")

    # ── OTHER WEBSITES ────────────────────────────────────
    elif action == "google_search":
        open_website(f"https://www.google.com/search?q={quote(params.get('query', ''))}")

    elif action == "netflix_open":
        open_website("https://netflix.com")

    elif action == "netflix_search":
        open_website(f"https://www.netflix.com/search?q={quote(params.get('query', ''))}")

    elif action == "github_open":
        open_website("https://github.com")

    elif action == "reddit_open":
        open_website("https://reddit.com")

    elif action == "gmail_open":
        open_website("https://mail.google.com")

    elif action == "maps_search":
        open_website(f"https://www.google.com/maps/search/{quote(params.get('query', ''))}")

    # ── DESKTOP APPS ──────────────────────────────────────
    elif action == "open_calculator":
        open_app("calculator")

    elif action == "open_notepad":
        open_app("notepad")

    elif action == "open_taskmanager":
        open_app("taskmgr")

    elif action == "open_vscode":
        try:
            subprocess.Popen(
                ["code", "."],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            # Try finding code.exe directly
            code_path = os.path.expanduser(r"~\AppData\Local\Programs\Microsoft VS Code\Code.exe")
            if os.path.exists(code_path):
                subprocess.Popen([code_path], creationflags=subprocess.DETACHED_PROCESS)
            else:
                console.print("[bold yellow][system]: VS Code not found in PATH or default install[/bold yellow]")

    elif action == "open_settings":
        open_app("settings")

    elif action == "open_folder":
        open_folder(params.get("folder", ""))

    elif action == "open_game":
        game = params.get("game", "").lower().strip()
        # First: check if it's a known app in our exe candidates list
        if game in _APP_EXE_CANDIDATES:
            open_app(game)
        else:
            # Try launching via Steam (for actual games)
            steam_exe = _resolve_exe(_APP_EXE_CANDIDATES.get("steam", []))
            if steam_exe:
                try:
                    subprocess.Popen(
                        [steam_exe],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                    )
                except Exception:
                    pass
            # Fall back to Steam store search in browser
            open_website(f"https://store.steampowered.com/search/?term={quote(game)}")

    # ── VOLUME ────────────────────────────────────────────
    elif action == "volume_up":
        try:
            subprocess.call(
                ["nircmd.exe", "changesysvolume", "6554"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            set_volume(70)

    elif action == "volume_down":
        try:
            subprocess.call(
                ["nircmd.exe", "changesysvolume", "-6554"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            set_volume(40)

    elif action == "mute":
        try:
            subprocess.call(
                ["nircmd.exe", "mutesysvolume", "1"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            console.print("[dim yellow][system]: nircmd.exe not found[/dim yellow]")

    elif action == "unmute":
        try:
            subprocess.call(
                ["nircmd.exe", "mutesysvolume", "0"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            console.print("[dim yellow][system]: nircmd.exe not found[/dim yellow]")

    # ── SYSTEM ────────────────────────────────────────────
    elif action == "screenshot":
        take_screenshot()

    elif action == "shutdown":
        os.system("shutdown /s /t 5")

    elif action == "restart":
        os.system("shutdown /r /t 5")

    elif action == "sleep":
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")

    return True
