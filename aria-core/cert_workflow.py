"""
cert_workflow.py — ARIA Certificate Generation & Distribution Engine
====================================================================
Orchestrates the full certificate pipeline:
  1. Accept PDF template + CSV from Telegram file uploads OR a known folder
  2. Parse CSV via Certify's /api/process-data
  3. Generate a sample certificate and send preview to Telegram
  4. Accept position adjustments via Telegram (↑ ↓ ← →)
  5. Bulk-generate all certificates as ZIP via /api/generate-and-send
  6. Send ZIP to user on Telegram
  7. Open Gmail in browser and check for bounced/failed emails
  8. Send delivery report to Telegram

Requires Certify (D:\\Certify) to be running at localhost:3000.
"""

import os
import io
import json
import time
import asyncio
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env")

CERTIFY_PATH = Path("D:/Certify")
CERTIFY_URL = "http://localhost:3000"
CERTIFY_PORT = 3000

# Default layer settings (name position)
DEFAULT_LAYER = {
    "id": "layer_name",
    "type": "field",
    "fieldKey": "name",
    "label": "Name",
    "preview": "John Doe",
    "x": 0,       # CSS pixel x — will be set to centre of PDF on first render
    "y": 0,       # CSS pixel y
    "fontFamily": "GreatVibes",
    "fontSize": 48,
    "color": "#1a1a2e",
}

# Position adjustment step in PDF points
POSITION_STEP = 10  # points


# ── Server management ─────────────────────────────────────────────────────────

def _is_certify_running() -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", CERTIFY_PORT)) == 0

def ensure_certify_running(timeout: int = 60) -> bool:
    """Start Certify if not already running. Returns True when ready."""
    if _is_certify_running():
        return True

    start_bat = CERTIFY_PATH / "start.bat"
    if not start_bat.exists():
        return False

    subprocess.Popen(
        ["cmd", "/c", str(start_bat)],
        cwd=str(CERTIFY_PATH),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_certify_running():
            time.sleep(2)
            return True
        time.sleep(1)
    return False


# ── CSV parser via Certify API ────────────────────────────────────────────────

async def parse_csv(csv_path: Path) -> list[dict]:
    """
    Upload CSV to Certify's /api/process-data and get parsed recipients.
    Returns list of recipient dicts with at least 'name' and optionally 'email'.
    """
    import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        with open(csv_path, "rb") as f:
            files = {"file": (csv_path.name, f, "text/csv")}
            resp = await client.post(f"{CERTIFY_URL}/api/process-data", files=files)
        resp.raise_for_status()
        data = resp.json()

    recipients = data.get("recipients", [])
    if not recipients:
        raise ValueError("No recipients found in CSV. Check column headers include 'name' or 'email'.")
    return recipients


# ── Certificate generator via Certify API ─────────────────────────────────────

async def generate_certificates(
    template_path: Path,
    recipients: list[dict],
    layers: list[dict],
    action: str = "zip",
    email_subject: str = "Your Certificate",
    email_body: str = "Hello {{name}},\n\nPlease find your certificate attached.\n\nBest regards",
) -> dict:
    """
    POST to /api/generate-and-send.
    action: 'zip' → returns downloadUrl for ZIP
            'email' → emails each recipient
    Returns API response dict.
    """
    import httpx

    async with httpx.AsyncClient(timeout=300) as client:
        with open(template_path, "rb") as f:
            template_bytes = f.read()

        form = {
            "data": json.dumps(recipients),
            "layers": json.dumps(layers),
            "emailSubject": email_subject,
            "emailBody": email_body,
            "action": action,
        }
        files = {
            "template": (template_path.name, io.BytesIO(template_bytes), "application/pdf"),
        }

        resp = await client.post(
            f"{CERTIFY_URL}/api/generate-and-send",
            data=form,
            files=files,
        )
        resp.raise_for_status()
        return resp.json()


async def generate_sample(template_path: Path, sample_recipient: dict, layers: list[dict]) -> bytes | None:
    """Generate a single sample certificate PDF and return raw bytes."""
    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        with open(template_path, "rb") as f:
            template_bytes = f.read()

        form = {
            "data": json.dumps([sample_recipient]),
            "layers": json.dumps(layers),
            "emailSubject": "Sample",
            "emailBody": "Sample",
            "action": "zip",
        }
        files = {
            "template": (template_path.name, io.BytesIO(template_bytes), "application/pdf"),
        }

        resp = await client.post(
            f"{CERTIFY_URL}/api/generate-and-send",
            data=form,
            files=files,
        )
        resp.raise_for_status()
        data = resp.json()

        # Download the ZIP and extract the single PDF
        download_url = data.get("downloadUrl")
        if not download_url:
            return None

        zip_resp = await client.get(f"{CERTIFY_URL}{download_url}")
        zip_resp.raise_for_status()

        import zipfile
        with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as z:
            names = z.namelist()
            if names:
                return z.read(names[0])
    return None


# ── Position adjustment helpers ───────────────────────────────────────────────

def adjust_layer_position(layer: dict, direction: str, step: int = POSITION_STEP) -> dict:
    """Move the name layer by `step` points in the given direction."""
    layer = dict(layer)
    if direction == "up":
        layer["y"] = layer.get("y", 0) - step
    elif direction == "down":
        layer["y"] = layer.get("y", 0) + step
    elif direction == "left":
        layer["x"] = layer.get("x", 0) - step
    elif direction == "right":
        layer["x"] = layer.get("x", 0) + step
    return layer


# ── WhatsApp file downloader ──────────────────────────────────────────────────

async def download_files_from_whatsapp(contact_name: str, file_types: list[str] = ["pdf", "csv"]) -> dict[str, Path | None]:
    """
    Open WhatsApp Desktop, navigate to contact, and download the most recent
    PDF and CSV attachments. Returns {ext: Path} dict.
    Uses ARIA's existing GUI automation (pyautogui + vision_gateway).
    """
    import pyautogui
    import ctypes
    import sys

    result = {ext: None for ext in file_types}

    # Open WhatsApp Desktop
    os.startfile("whatsapp:")
    time.sleep(3)

    # Try to bring WhatsApp to foreground
    hwnd_found = [None]
    def _enum(hwnd, _):
        buf_len = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if buf_len > 0:
            buf = ctypes.create_unicode_buffer(buf_len + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, buf_len + 1)
            if "whatsapp" in buf.value.lower():
                hwnd_found[0] = hwnd
                return False
        return True
    PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
    ctypes.windll.user32.EnumWindows(PROC(_enum), 0)
    if hwnd_found[0]:
        ctypes.windll.user32.ShowWindow(hwnd_found[0], 9)
        ctypes.windll.user32.SetForegroundWindow(hwnd_found[0])
    time.sleep(1.5)

    # Use vision gateway to find and click the contact
    try:
        sys.path.insert(0, str(_HERE))
        import vision_gateway
        from PIL import ImageGrab

        # Take screenshot and ask Gemini to locate the contact
        screenshot_path = Path(tempfile.mktemp(suffix=".png"))
        ImageGrab.grab().save(str(screenshot_path))

        guidance = await vision_gateway.verify_screen_state(
            str(screenshot_path),
            f"WhatsApp Desktop is open and showing the chat list. The contact '{contact_name}' should be visible.",
            context=f"Find the chat with '{contact_name}' and return coordinates to click on it."
        )

        if not guidance["approved"]:
            # Fallback: use search bar
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.5)
            pyautogui.typewrite(contact_name, interval=0.05)
            time.sleep(1.5)
            pyautogui.press("enter")
            time.sleep(1)

    except Exception:
        # Blind fallback
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.5)
        pyautogui.typewrite(contact_name, interval=0.05)
        time.sleep(1.5)
        pyautogui.press("enter")
        time.sleep(1)

    # Note: Full WhatsApp file download automation requires additional
    # vision-guided steps that are handled by main_daemon.py's WhatsApp flow.
    # This function returns None paths as a signal to use Telegram upload instead.
    return result


# ── Gmail bounce checker ──────────────────────────────────────────────────────

def open_gmail_and_check_bounces() -> str:
    """
    Open Gmail in browser and return instructions for checking bounce report.
    Full automation of Gmail reading requires Gmail API or IMAP — 
    this version opens Gmail and takes a screenshot for vision analysis.
    """
    import webbrowser
    webbrowser.open("https://mail.google.com/#search/subject%3Afailed+delivery+OR+undelivered+OR+mailer-daemon")
    time.sleep(4)

    # Take a screenshot for Gemini to analyze
    try:
        from PIL import ImageGrab
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shot_path = Path(tempfile.gettempdir()) / f"gmail_bounces_{ts}.png"
        ImageGrab.grab().save(str(shot_path))
        return str(shot_path)
    except Exception:
        return ""


# ── Main orchestrator (Telegram session state) ────────────────────────────────

class CertSession:
    """
    Holds state for an ongoing certificate workflow session.
    Persisted in memory; keyed by Telegram user_id in main_daemon.py.
    """
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.template_path: Path | None = None
        self.csv_path: Path | None = None
        self.recipients: list[dict] = []
        self.layers: list[dict] = [dict(DEFAULT_LAYER)]
        self.state: str = "awaiting_files"   # state machine
        self.sample_pdf_bytes: bytes | None = None
        self.zip_download_url: str | None = None
        self.started_at = datetime.now()

    @property
    def sample_recipient(self) -> dict:
        """Return the first recipient as a sample."""
        return self.recipients[0] if self.recipients else {"name": "Sample Name", "email": "sample@example.com"}

    def adjust(self, direction: str):
        """Move name layer in the given direction."""
        self.layers[0] = adjust_layer_position(self.layers[0], direction)

    def to_status(self) -> str:
        count = len(self.recipients)
        x = self.layers[0].get("x", 0)
        y = self.layers[0].get("y", 0)
        return (
            f"📋 **Certificate Session Status**\n"
            f"• Recipients: {count}\n"
            f"• Name position: x={x}, y={y}\n"
            f"• Font: {self.layers[0]['fontFamily']} {self.layers[0]['fontSize']}pt\n"
            f"• State: `{self.state}`"
        )


# Active sessions keyed by user_id
_cert_sessions: dict[int, CertSession] = {}

def get_or_create_session(user_id: int) -> CertSession:
    if user_id not in _cert_sessions:
        _cert_sessions[user_id] = CertSession(user_id)
    return _cert_sessions[user_id]

def clear_session(user_id: int):
    _cert_sessions.pop(user_id, None)


async def process_uploaded_file(user_id: int, file_path: Path, mime_type: str) -> str:
    """
    Handle a file uploaded to Telegram during a cert session.
    Auto-detects template PDF vs CSV.
    """
    session = get_or_create_session(user_id)
    ext = file_path.suffix.lower()

    if ext == ".pdf" or mime_type == "application/pdf":
        session.template_path = file_path
        if session.csv_path:
            return await _advance_to_parse(session)
        return "✅ Template PDF received! Now send me the CSV with recipient names (and optionally emails)."

    elif ext in (".csv", ".xlsx", ".xls") or "spreadsheet" in mime_type or "csv" in mime_type:
        session.csv_path = file_path
        if session.template_path:
            return await _advance_to_parse(session)
        return "✅ CSV received! Now send me the PDF certificate template."

    return "⚠️ Unrecognized file. Please send a PDF template or a CSV/Excel file with recipient names."


async def _advance_to_parse(session: CertSession) -> str:
    """Parse CSV and move to preview state."""
    if not _is_certify_running():
        ok = ensure_certify_running()
        if not ok:
            return "❌ Could not start Certify server. Make sure Node.js is installed and D:\\Certify exists."

    try:
        session.recipients = await parse_csv(session.csv_path)
    except Exception as e:
        return f"❌ Failed to parse CSV: {e}"

    session.state = "awaiting_preview_approval"
    count = len(session.recipients)
    sample = session.sample_recipient

    # Generate sample cert
    try:
        session.sample_pdf_bytes = await generate_sample(
            session.template_path, sample, session.layers
        )
    except Exception:
        session.sample_pdf_bytes = None

    return (
        f"✅ Parsed **{count} recipients**. Sample: _{sample.get('name', 'Unknown')}_\n\n"
        f"📄 Here's a sample certificate. Use the buttons below to adjust the name position:\n"
        f"↑ ↓ ← → to move | ✅ to confirm and generate all | ❌ to cancel"
    )


async def handle_position_command(user_id: int, direction: str) -> tuple[str, bytes | None]:
    """
    Adjust name position and regenerate sample.
    Returns (message, new_sample_pdf_bytes).
    """
    session = get_or_create_session(user_id)
    session.adjust(direction)

    try:
        new_sample = await generate_sample(
            session.template_path, session.sample_recipient, session.layers
        )
        session.sample_pdf_bytes = new_sample
        x = session.layers[0]["x"]
        y = session.layers[0]["y"]
        return f"Moved {direction}. Position: x={x}, y={y}. How does this look?", new_sample
    except Exception as e:
        return f"⚠️ Could not regenerate sample: {e}", session.sample_pdf_bytes


async def confirm_and_generate(user_id: int) -> tuple[str, Path | None]:
    """
    User approved preview. Generate full ZIP.
    Returns (message, zip_path).
    """
    session = get_or_create_session(user_id)
    session.state = "generating"

    try:
        result = await generate_certificates(
            session.template_path,
            session.recipients,
            session.layers,
            action="zip",
        )
        download_url = result.get("downloadUrl")
        if not download_url:
            return "❌ Certify did not return a download URL.", None

        session.zip_download_url = download_url

        # Download the ZIP
        import httpx
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(f"{CERTIFY_URL}{download_url}")
            resp.raise_for_status()
            zip_bytes = resp.content

        # Save locally
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = Path(tempfile.gettempdir()) / f"Certificates_{ts}.zip"
        zip_path.write_bytes(zip_bytes)

        count = len(session.recipients)
        successes = result.get("results", {}).get("successes", count)
        session.state = "done"

        msg = (
            f"✅ **{successes}/{count} certificates generated!**\n"
            f"📦 ZIP file ready — sending to you now.\n\n"
            f"_Want me to also check Gmail for delivery bounces?_ Reply **yes** to check."
        )
        return msg, zip_path

    except Exception as e:
        session.state = "error"
        return f"❌ Generation failed: {e}", None


async def check_gmail_bounces_with_vision() -> str:
    """
    Open Gmail bounce search, screenshot it, and ask Gemini to interpret results.
    Returns a human-readable delivery report.
    """
    screenshot_path = open_gmail_and_check_bounces()

    if not screenshot_path or not Path(screenshot_path).exists():
        return "⚠️ Could not screenshot Gmail. Please check Gmail manually for bounce emails."

    try:
        sys.path = [str(_HERE)] + sys.path
        import vision_gateway
        result = await vision_gateway.verify_screen_state(
            screenshot_path,
            "Gmail is open showing search results for bounce/undelivered emails. List any failure emails visible.",
            context="The user sent certificate emails to multiple recipients. Check if there are any 'Mail Delivery Failed' or 'Undelivered Mail Returned' messages."
        )
        if result["approved"]:
            return f"📧 **Gmail Delivery Report**\n\n✅ No bounce emails found — all certificates likely delivered successfully!"
        else:
            return (
                f"📧 **Gmail Delivery Report**\n\n"
                f"⚠️ {result['reason']}\n\n"
                f"_Check Gmail manually for details:_ https://mail.google.com"
            )
    except Exception as e:
        return f"⚠️ Could not analyze Gmail: {e}. Please check manually."
