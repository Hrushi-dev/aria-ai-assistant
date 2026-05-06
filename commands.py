# ─── commands.py ──────────────────────────────────────────
# This file handles everything that touches your PC.
# Opening apps, websites, folders, controlling volume, system actions.
# It doesn't talk to Ollama. It doesn't know about Aria's personality.
# It just receives an action + params and executes it.

import os
import subprocess
import webbrowser
from urllib.parse import quote

from config import ALLOWED_ACTIONS


# ─── HELPERS ──────────────────────────────────────────────

def open_website(link: str):
    """Opens a URL in the default browser."""
    try:
        webbrowser.open(link)
    except Exception as e:
        print(f"[system]: couldn't open link — {e}")


def open_app(app_name: str):
    """
    Opens a Windows app by name.
    Tries the Microsoft Store app path first,
    then falls back to web if available.
    """
    store_apps = {
        "whatsapp":   "shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!WhatsApp",
        "calculator": "shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
        "spotify":    "shell:AppsFolder\\SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
        "settings":   "ms-settings:",
        "notepad":    "notepad.exe",
        "taskmgr":    "taskmgr.exe",
    }
    try:
        if app_name in store_apps:
            os.startfile(store_apps[app_name])
        else:
            subprocess.Popen(app_name)
    except FileNotFoundError:
        web_fallbacks = {
            "whatsapp": "https://web.whatsapp.com",
            "spotify":  "https://open.spotify.com",
        }
        if app_name in web_fallbacks:
            open_website(web_fallbacks[app_name])
        else:
            print(f"[system]: couldn't find {app_name}")
    except Exception as e:
        print(f"[system]: error opening {app_name} — {e}")


def open_folder(folder_name: str):
    """Opens a known folder by nickname (e.g. 'downloads', 'project')."""
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
        print(f"[system]: couldn't open folder — {e}")


def set_volume(level: int):
    """
    Sets system volume using nircmd.exe.
    level is 0-100. Internally converts to 0-65535 range.
    nircmd.exe must be in D:\\AI-AIS\\ for this to work.
    """
    try:
        subprocess.call(["nircmd.exe", "setsysvolume", str(int(level * 655.35))])
    except Exception:
        print("[system]: nircmd.exe not found — drop it in D:\\AI-AIS\\ for volume control")


# ─── MAIN EXECUTOR ────────────────────────────────────────

def execute_command(action: str, params: dict) -> bool:
    """
    Receives an action name and params dict from Aria's brain.
    Executes the matching PC function.
    Returns True if something was executed, False if not.

    This is the only function main.py needs to call from here.
    """

    # ignore unknown or empty actions
    if action not in ALLOWED_ACTIONS or action == "none":
        return False

    # dangerous actions need a confirmation prompt
    if action in ["shutdown", "restart", "sleep"]:
        confirm = input(f"Aria: you sure you want to {action}? (yes/no): ").strip().lower()
        if confirm not in ["yes", "y"]:
            print("[system]: cancelled.")
            return False

    # ── YOUTUBE ───────────────────────────────────────────
    if action == "youtube_open":
        open_website("https://youtube.com")

    elif action == "youtube_search":
        query = params.get("query", "")
        open_website(f"https://www.youtube.com/search?q={quote(query)}")

    elif action == "youtube_play":
        query  = params.get("query", "")
        artist = params.get("artist", "")
        search_term = f"{query} {artist}".strip()
        open_website(f"https://www.youtube.com/search?q={quote(search_term)}")

    # ── SPOTIFY ───────────────────────────────────────────
    elif action == "spotify_open":
        open_app("spotify")

    elif action == "spotify_play":
        query = params.get("query", "")
        open_website(f"https://open.spotify.com/search/{quote(query)}")

    # ── WHATSAPP ──────────────────────────────────────────
    elif action == "whatsapp_open":
        open_app("whatsapp")

    elif action == "whatsapp_message":
        message = params.get("message", "")
        open_website(f"https://wa.me/?text={quote(message)}")

    elif action == "whatsapp_call":
        open_app("whatsapp")

    # ── INSTAGRAM ─────────────────────────────────────────
    elif action == "instagram_open":
        open_website("https://instagram.com")

    elif action == "instagram_reels":
        open_website("https://www.instagram.com/reels/")

    elif action == "instagram_dm":
        open_website("https://www.instagram.com/direct/inbox/")

    elif action == "instagram_profile":
        username = params.get("username", "")
        open_website(f"https://www.instagram.com/{username}/")

    # ── OTHER WEBSITES ────────────────────────────────────
    elif action == "google_search":
        query = params.get("query", "")
        open_website(f"https://www.google.com/search?q={quote(query)}")

    elif action == "netflix_open":
        open_website("https://netflix.com")

    elif action == "netflix_search":
        query = params.get("query", "")
        open_website(f"https://www.netflix.com/search?q={quote(query)}")

    elif action == "github_open":
        open_website("https://github.com")

    elif action == "reddit_open":
        open_website("https://reddit.com")

    elif action == "gmail_open":
        open_website("https://mail.google.com")

    elif action == "maps_search":
        query = params.get("query", "")
        open_website(f"https://www.google.com/maps/search/{quote(query)}")

    # ── APPS ──────────────────────────────────────────────
    elif action == "open_calculator":
        open_app("calculator")

    elif action == "open_notepad":
        open_app("notepad")

    elif action == "open_taskmanager":
        open_app("taskmgr")

    elif action == "open_vscode":
        try:
            subprocess.Popen(["code", "."])
        except Exception:
            print("[system]: VS Code not in PATH")

    elif action == "open_settings":
        open_app("settings")

    elif action == "open_folder":
        folder = params.get("folder", "")
        open_folder(folder)

    # ── VOLUME ────────────────────────────────────────────
    elif action == "volume_up":
        set_volume(80)

    elif action == "volume_down":
        set_volume(30)

    elif action == "mute":
        try:
            subprocess.call(["nircmd.exe", "mutesysvolume", "1"])
        except Exception:
            print("[system]: nircmd.exe not found")

    elif action == "unmute":
        try:
            subprocess.call(["nircmd.exe", "mutesysvolume", "0"])
        except Exception:
            print("[system]: nircmd.exe not found")

    # ── SYSTEM ────────────────────────────────────────────
    elif action == "screenshot":
        try:
            subprocess.Popen(["snippingtool"])
        except Exception:
            subprocess.Popen(["SnippingTool.exe"])

    elif action == "shutdown":
        os.system("shutdown /s /t 5")

    elif action == "restart":
        os.system("shutdown /r /t 5")

    elif action == "sleep":
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")

    return True
