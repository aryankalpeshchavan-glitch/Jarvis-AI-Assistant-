"""
J.A.R.V.I.S — Desktop Automation Engine
=======================================
Open-source local desktop AI assistant powered by FastAPI, Pyttsx3 TTS,
fuzzy app matching, a lightweight intent classifier (greetings vs commands
vs "I can't do that"), and a reliable cross-platform website opener.

Author: Aryan
License: MIT
"""

import os
import sys
import time
import json
import re
import random
import threading
import subprocess
import platform
import webbrowser
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from ai_brain import process_command_with_ai

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# ─── Environment & Logging Config ──────────────────────────────────────────
LOG_LEVEL = os.getenv("JARVIS_LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("jarvis")

# ─── Fuzzy Matching Engine ──────────────────────────────────────────────────
# rapidfuzz gives much better results than plain substring matching (handles
# typos like "ghost of tsunami" -> "Ghost of Tsushima"). Falls back to the
# stdlib difflib if rapidfuzz isn't installed, so the app never hard-fails
# just because of a missing optional dependency.
try:
    from rapidfuzz import fuzz as _rf_fuzz, process as _rf_process
    HAVE_RAPIDFUZZ = True
except ImportError:
    HAVE_RAPIDFUZZ = False
    import difflib
    log.warning("rapidfuzz not installed — falling back to difflib (lower quality fuzzy matching). "
                "Run: pip install rapidfuzz")


def fuzzy_best_match(query: str, candidates: List[str], threshold: int = 72) -> Tuple[Optional[str], float]:
    """
    Return (best_matching_candidate, score_0_to_100) or (None, best_score_seen)
    if nothing cleared the confidence threshold.
    """
    if not candidates:
        return None, 0.0

    if HAVE_RAPIDFUZZ:
        result = _rf_process.extractOne(query, candidates, scorer=_rf_fuzz.WRatio)
        if result is None:
            return None, 0.0
        match, score, _ = result
        return (match, score) if score >= threshold else (None, score)
    else:
        close = difflib.get_close_matches(query, candidates, n=1, cutoff=threshold / 100)
        if close:
            ratio = difflib.SequenceMatcher(None, query, close[0]).ratio() * 100
            return close[0], ratio
        # report the best-effort score even on failure, useful for logging
        scores = [(c, difflib.SequenceMatcher(None, query, c).ratio() * 100) for c in candidates]
        best = max(scores, key=lambda x: x[1]) if scores else (None, 0.0)
        return None, best[1]


# ─── Non-Blocking TTS Engine ───────────────────────────────────────────────
tts_lock = threading.Lock()
tts_engine = None


def _init_tts():
    """Initialize pyttsx3 offline text-to-speech engine in a worker thread."""
    global tts_engine
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 170)
        engine.setProperty("volume", 0.95)
        voices = engine.getProperty("voices")
        for v in voices:
            v_name = v.name.lower()
            if "david" in v_name or "mark" in v_name or "male" in v_name or "zira" in v_name:
                engine.setProperty("voice", v.id)
                break
        tts_engine = engine
        log.info("TTS engine initialized successfully.")
    except Exception as exc:
        log.warning(f"TTS engine initialization non-fatal warning: {exc}")


def speak(text: str):
    """Speak text asynchronously without blocking HTTP response handlers."""
    def _run_tts():
        with tts_lock:
            try:
                if tts_engine:
                    tts_engine.say(text)
                    tts_engine.runAndWait()
            except Exception as e:
                log.warning(f"TTS speech warning: {e}")

    threading.Thread(target=_run_tts, daemon=True).start()


# ─── Config (persisted to disk, editable via /config or the Settings panel) ─
if getattr(sys, "frozen", False):
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    CONFIG_DIR = Path(sys.executable).parent  # write config next to the .exe, not inside the read-only bundle
else:
    BASE_DIR = Path(__file__).parent.resolve()
    CONFIG_DIR = BASE_DIR

CONFIG_PATH = CONFIG_DIR / "jarvis_config.json"
DEFAULT_CONFIG = {"user_name": "Guest", "github_username": "", "asked_autostart": False}


def load_config() -> Dict[str, str]:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            return {**DEFAULT_CONFIG, **data}
        except Exception as e:
            log.warning(f"Config read warning: {e}")
    return dict(DEFAULT_CONFIG)


def save_config(cfg: Dict[str, str]):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    except Exception as e:
        log.warning(f"Config save warning: {e}")


CONFIG: Dict[str, str] = load_config()


# ─── Auto-start on login (Windows Startup folder) ───────────────────────────
def _startup_folder() -> Path:
    return Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"


def _startup_stub_path() -> Path:
    return _startup_folder() / "Jarvis.bat"


def is_autostart_enabled() -> bool:
    if platform.system() != "Windows":
        return False
    return _startup_stub_path().exists()


def enable_autostart():
    if platform.system() != "Windows":
        raise RuntimeError("Auto-start is currently only supported on Windows.")
    folder = _startup_folder()
    if not folder.exists():
        raise RuntimeError(f"Windows Startup folder not found at {folder}.")

    if getattr(sys, "frozen", False):
        # Packaged .exe: launch itself directly.
        launch_line = f'start "" "{sys.executable}"'
    else:
        # Running from source: reuse startup.bat, which starts the server
        # and opens the UI window the same way a manual double-click would.
        launch_line = f'call "{BASE_DIR / "startup.bat"}"'

    content = f'@echo off\r\ncd /d "{BASE_DIR}"\r\n{launch_line}\r\n'
    try:
        _startup_stub_path().write_text(content, encoding="utf-8")
    except Exception as e:
        raise RuntimeError(f"Couldn't write to the Startup folder ({e}).")


def disable_autostart():
    stub = _startup_stub_path()
    if stub.exists():
        try:
            stub.unlink()
        except Exception as e:
            raise RuntimeError(f"Couldn't remove the Startup entry ({e}).")


# ─── Windows App Launcher Engine ─────────────────────────────────────────────
INSTALLED_APPS_CACHE: Dict[str, str] = {}
SHORTCUTS_CACHE: Dict[str, Path] = {}
STEAM_GAMES_CACHE: Dict[str, str] = {}  # lowercase game name -> Steam AppID
INDEXING_COMPLETE = threading.Event()  # set once startup indexing has finished (or given up)


def index_windows_apps():
    """Index installed Windows applications using PowerShell Get-StartApps, Start Menu
    shortcuts, Desktop shortcuts, and the local Steam game library."""
    global INSTALLED_APPS_CACHE, SHORTCUTS_CACHE
    if platform.system() != "Windows":
        INDEXING_COMPLETE.set()
        return

    log.info("Indexing installed Windows applications...")

    try:
        cmd = ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            raw_data = json.loads(res.stdout)
            if isinstance(raw_data, dict):
                raw_data = [raw_data]

            for item in raw_data:
                name = item.get("Name", "").strip()
                appid = item.get("AppID", "").strip()
                if name and appid:
                    INSTALLED_APPS_CACHE[name.lower()] = appid
            log.info(f"Indexed {len(INSTALLED_APPS_CACHE)} apps via Get-StartApps.")
    except Exception as e:
        log.warning(f"Get-StartApps indexing warning: {e}")

    try:
        shortcut_dirs = [
            Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
            Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
            # Desktop shortcuts too — a lot of game launchers (Steam, Epic, GOG) only
            # create a Desktop icon, not a Start Menu entry, so Start Menu alone misses them.
            Path(os.environ.get("USERPROFILE", "")) / "Desktop",
            Path(r"C:\Users\Public\Desktop"),
        ]
        for sdir in shortcut_dirs:
            if not sdir.exists():
                continue
            # Start Menu folders are searched recursively (apps are often nested in
            # publisher subfolders); Desktop is scanned top-level only.
            pattern = "**/*.lnk" if "Start Menu" in str(sdir) else "*.lnk"
            for lnk in sdir.glob(pattern):
                SHORTCUTS_CACHE.setdefault(lnk.stem.lower(), lnk)
        log.info(f"Indexed {len(SHORTCUTS_CACHE)} shortcuts (Start Menu + Desktop).")
    except Exception as e:
        log.warning(f"Shortcut indexing warning: {e}")

    index_steam_games()
    INDEXING_COMPLETE.set()


def _find_steam_install_path() -> Optional[Path]:
    for env_var, subpath in [("PROGRAMFILES(X86)", "Steam"), ("PROGRAMFILES", "Steam")]:
        candidate = Path(os.environ.get(env_var, "")) / subpath if os.environ.get(env_var) else None
        if candidate and candidate.exists():
            return candidate
    try:
        import winreg
        for hive, key_path, value_name in [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        ]:
            try:
                key = winreg.OpenKey(hive, key_path)
                value, _ = winreg.QueryValueEx(key, value_name)
                p = Path(value)
                if p.exists():
                    return p
            except Exception:
                continue
    except ImportError:
        pass
    return None


def _steam_library_folders(steam_path: Path) -> List[Path]:
    """Steam games can live in multiple library folders across different drives —
    parse libraryfolders.vdf to find all of them, not just the default install."""
    libs = [steam_path / "steamapps"]
    vdf_path = steam_path / "steamapps" / "libraryfolders.vdf"
    if vdf_path.exists():
        try:
            text = vdf_path.read_text(errors="ignore")
            for m in re.finditer(r'"path"\s*"([^"]+)"', text):
                lib = Path(m.group(1).replace("\\\\", "\\")) / "steamapps"
                if lib.exists():
                    libs.append(lib)
        except Exception as e:
            log.warning(f"Steam library folder parse warning: {e}")
    return libs


def index_steam_games():
    """
    Read Steam's own app manifests (appmanifest_*.acf) to build a name -> AppID
    map. This is far more reliable than hoping a game has a Start Menu or
    Desktop shortcut — Steam always writes these manifests for installed games,
    and games can then be launched directly via steam://rungameid/<appid>.
    """
    global STEAM_GAMES_CACHE
    if platform.system() != "Windows":
        return
    steam_path = _find_steam_install_path()
    if not steam_path:
        log.info("Steam installation not found — skipping Steam game indexing.")
        return
    count = 0
    for lib in _steam_library_folders(steam_path):
        try:
            for manifest in lib.glob("appmanifest_*.acf"):
                try:
                    text = manifest.read_text(errors="ignore")
                    name_m = re.search(r'"name"\s*"([^"]+)"', text)
                    appid_m = re.search(r'"appid"\s*"(\d+)"', text)
                    if name_m and appid_m:
                        STEAM_GAMES_CACHE[name_m.group(1).strip().lower()] = appid_m.group(1)
                        count += 1
                except Exception:
                    continue
        except Exception:
            continue
    log.info(f"Indexed {count} Steam games.")


# Protocol URIs and standard shell fallback commands (NOT websites — those are handled separately)
KNOWN_PROTOCOLS: Dict[str, str] = {
    "spotify": "spotify:",
    "whatsapp": "whatsapp:",
    "settings": "ms-settings:",
    "system settings": "ms-settings:",
    "chrome": "chrome",
    "edge": "msedge:",
    "firefox": "firefox",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "calculator": "calc",
    "calc": "calc",
    "notepad": "notepad",
    "task manager": "taskmgr",
    "explorer": "explorer",
    "file explorer": "explorer",
    "paint": "mspaint",
    "discord": "discord:",
    "telegram": "tg:",
    "steam": "steam:",
    "zoom": "zoommtg:",
    "browser": "",  # opens the OS default browser with no target page
}

WEBSITE_MAP: Dict[str, str] = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "google mail": "https://mail.google.com",
    "github": "https://github.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "amazon": "https://www.amazon.com",
    "netflix": "https://www.netflix.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://www.twitter.com",
    "x": "https://www.x.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com",
    "wikipedia": "https://www.wikipedia.org",
    "chatgpt": "https://chat.openai.com",
    "claude": "https://claude.ai",
    "whatsapp web": "https://web.whatsapp.com",
    "translate": "https://translate.google.com",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
}

DOMAIN_PATTERN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?$", re.IGNORECASE)
WIN_PATH_PATTERN = re.compile(r"^[a-zA-Z]:\\|^\\\\")
UNIX_PATH_PATTERN = re.compile(r"^/[^ ]+")

# Windows' built-in "shell:" folder aliases — these work reliably across
# Windows versions regardless of the user's actual language/display names,
# unlike hardcoding paths like "C:\Users\X\Downloads".
SPECIAL_FOLDERS: Dict[str, str] = {
    "downloads": "shell:Downloads",
    "download": "shell:Downloads",
    "documents": "shell:Personal",
    "my documents": "shell:Personal",
    "desktop": "shell:Desktop",
    "pictures": "shell:My Pictures",
    "photos": "shell:My Pictures",
    "music": "shell:My Music",
    "videos": "shell:My Video",
    "this pc": "shell:MyComputerFolder",
    "my computer": "shell:MyComputerFolder",
    "recycle bin": "shell:RecycleBinFolder",
    "control panel": "shell:ControlPanelFolder",
    "appdata": "shell:AppData",
    "home folder": "shell:Profile",
    "home": "shell:Profile",
}
DRIVE_PATTERN = re.compile(r"^([a-z])\s*(?::)?\s*drive$", re.IGNORECASE)


def resolve_special_folder(query: str) -> Optional[str]:
    """Return a shell: alias or drive path if the query names a well-known folder."""
    q = query.strip().lower()
    q_nofolder = re.sub(r"\s+folder$", "", q).strip()
    for key in (q, q_nofolder):
        if key in SPECIAL_FOLDERS:
            return SPECIAL_FOLDERS[key]
    m = DRIVE_PATTERN.match(q_nofolder) or DRIVE_PATTERN.match(q)
    if m:
        return f"{m.group(1).upper()}:\\"
    return None


def search_named_folder(name: str) -> Optional[Path]:
    """
    Fuzzy-search common folders (Desktop, Documents, Downloads, home dir) for a
    subfolder matching `name` — handles "open project files folder" where
    "project files" isn't a well-known special folder but does exist on disk.
    """
    home = Path.home()
    roots = [home / "Desktop", home / "Documents", home / "Downloads", home]
    candidates: Dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        try:
            for entry in root.iterdir():
                if entry.is_dir():
                    candidates.setdefault(entry.name.lower(), entry)
        except Exception:
            continue
    if not candidates:
        return None
    match, score = fuzzy_best_match(name, list(candidates.keys()), threshold=72)
    return candidates[match] if match else None


def open_folder(target: str) -> Dict[str, Any]:
    try:
        subprocess.Popen(["explorer.exe", target])
        return {"method": "Folder", "target": target}
    except Exception as e:
        raise RuntimeError(f"Found that folder but couldn't open it ({e}).")


# ─── Closing running apps ───────────────────────────────────────────────────
CLOSE_VERBS = ("close ", "quit ", "kill ", "exit ", "stop ")


def _list_running_processes() -> List[str]:
    """Return the list of running process image names (e.g. 'chrome.exe')."""
    res = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=8)
    names = []
    for line in res.stdout.strip().splitlines():
        parts = line.split('","')
        if parts:
            names.append(parts[0].strip('"'))
    return names


def close_app(query: str) -> Dict[str, Any]:
    """Close a running app by (fuzzy-matched) name via taskkill."""
    if platform.system() != "Windows":
        raise RuntimeError("Closing apps by name is currently only supported on Windows.")

    try:
        running = _list_running_processes()
    except Exception as e:
        raise RuntimeError(f"Couldn't read the list of running processes ({e}).")

    if not running:
        raise RuntimeError("No running processes could be read.")

    query = query.strip().lower()
    guess = f"{query}.exe"
    match_name = next((p for p in running if p.lower() == guess), None)

    if not match_name:
        stripped = {p: (p[:-4] if p.lower().endswith(".exe") else p) for p in running}
        best, score = fuzzy_best_match(query, list(stripped.values()), threshold=72)
        if best:
            match_name = next((p for p, s in stripped.items() if s == best), None)

    if not match_name:
        raise RuntimeError(f"'{query}' doesn't seem to be running right now.")

    try:
        subprocess.run(["taskkill", "/IM", match_name, "/F"], capture_output=True, text=True, timeout=8)
        return {"method": "Close", "target": match_name}
    except Exception as e:
        raise RuntimeError(f"Found '{match_name}' running but couldn't close it ({e}).")


# ─── System power actions ───────────────────────────────────────────────────
# Lock/sleep are low-risk and reversible, so they execute immediately.
# Shutdown/restart/log-off can lose unsaved work, so they require a spoken
# "confirm" within a short window rather than firing on the first utterance
# — a single misheard word should never actually power off the machine.
SAFE_SYSTEM_ACTIONS: Dict[str, Tuple[str, List[str]]] = {
    "lock": ("Locking the screen.", ["rundll32.exe", "user32.dll,LockWorkStation"]),
    "lock screen": ("Locking the screen.", ["rundll32.exe", "user32.dll,LockWorkStation"]),
    "lock the screen": ("Locking the screen.", ["rundll32.exe", "user32.dll,LockWorkStation"]),
    "sleep": ("Putting the computer to sleep.", ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]),
    "go to sleep": ("Putting the computer to sleep.", ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]),
    "cancel shutdown": ("Shutdown cancelled.", ["shutdown", "/a"]),
    "abort shutdown": ("Shutdown cancelled.", ["shutdown", "/a"]),
}
DESTRUCTIVE_ACTIONS: Dict[str, Tuple[str, List[str]]] = {
    "shutdown": ("shut down the computer", ["shutdown", "/s", "/t", "5"]),
    "shut down": ("shut down the computer", ["shutdown", "/s", "/t", "5"]),
    "shut down the computer": ("shut down the computer", ["shutdown", "/s", "/t", "5"]),
    "turn off the computer": ("shut down the computer", ["shutdown", "/s", "/t", "5"]),
    "restart": ("restart the computer", ["shutdown", "/r", "/t", "5"]),
    "reboot": ("restart the computer", ["shutdown", "/r", "/t", "5"]),
    "restart the computer": ("restart the computer", ["shutdown", "/r", "/t", "5"]),
    "log off": ("log off", ["shutdown", "/l"]),
    "sign out": ("log off", ["shutdown", "/l"]),
}
CONFIRM_PHRASES = ("yes", "confirm", "yes confirm", "confirm it", "do it", "yes shutdown", "yes restart")
_PENDING_CONFIRMATION: Dict[str, float] = {}
_CONFIRMATION_WINDOW_SECONDS = 20


def resolve_system_command(raw_query: str) -> Optional[Dict[str, Any]]:
    """
    Returns a result dict if `raw_query` is a recognized system action,
    None if it isn't a system command at all (caller should keep resolving
    it some other way). Raises RuntimeError for the "please confirm" case —
    that's not a failure, it's a message that needs to reach the user/voice.
    """
    q = raw_query.strip().lower()

    if q in CONFIRM_PHRASES:
        now = time.time()
        for action, expiry in list(_PENDING_CONFIRMATION.items()):
            if now < expiry:
                label, cmd = DESTRUCTIVE_ACTIONS[action]
                _PENDING_CONFIRMATION.clear()
                try:
                    subprocess.Popen(cmd)
                except Exception as e:
                    raise RuntimeError(f"Confirmed, but couldn't actually {label} ({e}).")
                return {"method": "System", "target": label}
        return None  # "yes" with nothing pending — not a system command

    if q in SAFE_SYSTEM_ACTIONS:
        label, cmd = SAFE_SYSTEM_ACTIONS[q]
        try:
            subprocess.Popen(cmd)
        except Exception as e:
            raise RuntimeError(f"Couldn't do that ({e}).")
        return {"method": "System", "target": label}

    if q in DESTRUCTIVE_ACTIONS:
        label, cmd = DESTRUCTIVE_ACTIONS[q]
        _PENDING_CONFIRMATION.clear()
        _PENDING_CONFIRMATION[q] = time.time() + _CONFIRMATION_WINDOW_SECONDS
        raise RuntimeError(
            f"Say \"confirm\" within {_CONFIRMATION_WINDOW_SECONDS} seconds to {label}. "
            f"Nothing has happened yet."
        )

    return None


# ─── Media / volume controls (simulated media keys — no extra dependencies) ─
MEDIA_KEY_COMMANDS: Dict[str, str] = {
    "mute": "[char]173",
    "unmute": "[char]173",
    "volume up": "[char]175",
    "increase volume": "[char]175",
    "volume down": "[char]174",
    "decrease volume": "[char]174",
    "play": "[char]179",
    "pause": "[char]179",
    "play music": "[char]179",
    "pause music": "[char]179",
    "play pause": "[char]179",
    "next track": "[char]176",
    "next song": "[char]176",
    "skip track": "[char]176",
    "previous track": "[char]177",
    "previous song": "[char]177",
}


def resolve_media_command(raw_query: str) -> Optional[Dict[str, Any]]:
    q = raw_query.strip().lower()
    key_expr = MEDIA_KEY_COMMANDS.get(q)
    if key_expr is None:
        return None
    try:
        subprocess.Popen([
            "powershell", "-NoProfile", "-Command",
            f"(New-Object -ComObject WScript.Shell).SendKeys({key_expr})",
        ])
    except Exception as e:
        raise RuntimeError(f"Couldn't send that media command ({e}).")
    return {"method": "Media", "target": q}


# ─── Screenshot & Recycle Bin ───────────────────────────────────────────────
_SCREENSHOT_PS = (
    "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
    "$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
    "$bmp=New-Object System.Drawing.Bitmap $s.Width,$s.Height; "
    "$g=[System.Drawing.Graphics]::FromImage($bmp); "
    "$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size); "
    "$p=\"$env:USERPROFILE\\Pictures\\Jarvis_Screenshot_$(Get-Date -Format yyyyMMdd_HHmmss).png\"; "
    "$bmp.Save($p)"
)


def resolve_utility_command(raw_query: str) -> Optional[Dict[str, Any]]:
    q = raw_query.strip().lower()
    if q in ("take a screenshot", "screenshot", "take screenshot"):
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-Command", _SCREENSHOT_PS])
        except Exception as e:
            raise RuntimeError(f"Couldn't take a screenshot ({e}).")
        return {"method": "Utility", "target": "screenshot saved to Pictures"}

    if q in ("empty recycle bin", "empty the recycle bin", "empty trash"):
        try:
            subprocess.Popen(["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"])
        except Exception as e:
            raise RuntimeError(f"Couldn't empty the recycle bin ({e}).")
        return {"method": "Utility", "target": "recycle bin emptied"}

    if q in ("what time is it", "what's the time", "current time", "tell me the time"):
        return {"method": "Info", "target": time.strftime("It's %I:%M %p").lstrip("0")}

    if q in ("what's the date", "what is the date", "what's today's date", "today's date"):
        return {"method": "Info", "target": time.strftime("Today is %A, %B %d, %Y")}

    return None


LEADING_VERBS = ("please ", "open ", "launch ", "run ", "start ", "play ", "go to ", "search ")

WAKE_PHRASES = ("hey jarvis", "hello jarvis", "ok jarvis", "okay jarvis", "jarvis")

SPLIT_PATTERN = re.compile(r"\s*,\s*|\s+and then\s+|\s+then\s+|\s+and also\s+|\s+and\s+", re.IGNORECASE)
_LEADING_CONNECTOR = re.compile(r"^(then|also|and)\s+", re.IGNORECASE)


def split_commands(text: str) -> List[str]:
    """Split a natural-language utterance into one or more atomic commands."""
    raw_parts = [p.strip() for p in SPLIT_PATTERN.split(text) if p.strip()]
    parts = []
    for p in raw_parts:
        cleaned = _LEADING_CONNECTOR.sub("", p).strip()
        if cleaned:
            parts.append(cleaned)
    return parts or [text.strip()]


def _strip_wake_phrase(text: str) -> str:
    t = text.strip().lower()
    for phrase in WAKE_PHRASES:
        if t.startswith(phrase):
            t = t[len(phrase):].strip(" ,.!")
    return t


def _strip_leading_verb(query: str) -> str:
    q = query.strip().lower()
    changed = True
    while changed:
        changed = False
        for prefix in LEADING_VERBS:
            if q.startswith(prefix):
                q = q[len(prefix):].strip()
                changed = True
    return q


# ─── Intent Classification (greeting / chitchat / command) ─────────────────
GREETING_PHRASES = ["hi", "hello", "hey", "yo", "sup", "hola", "greetings"]
HOWAREYOU_PHRASES = ["how are you", "how's it going", "hows it going", "what's up", "whats up", "how you doing"]
THANKS_PHRASES = ["thanks", "thank you", "thx", "appreciate it", "cheers"]
FAREWELL_PHRASES = ["bye", "goodbye", "see you", "good night", "catch you later"]
# "exit", "quit", "shutdown", "shut down" are deliberately NOT here — they're
# real functional commands now (closing apps / shutting down the PC), so
# treating them as pure chitchat would swallow "quit spotify" as a goodbye
# instead of actually closing Spotify.

GREETING_RESPONSES = [
    "Hello! How can I help you today?",
    "Hey there — what can I do for you?",
    "Hi! Ready when you are. What would you like me to open or do?",
]
HOWAREYOU_RESPONSES = [
    "I'm running smoothly, thanks for asking. What can I help with?",
    "All systems nominal. What do you need?",
]
THANKS_RESPONSES = ["You're welcome!", "Anytime.", "Happy to help."]
FAREWELL_RESPONSES = ["Goodbye!", "See you later.", "Talk soon."]

_CHITCHAT_BUCKETS = [
    ("greeting", GREETING_PHRASES, GREETING_RESPONSES),
    ("howareyou", HOWAREYOU_PHRASES, HOWAREYOU_RESPONSES),
    ("thanks", THANKS_PHRASES, THANKS_RESPONSES),
    ("farewell", FAREWELL_PHRASES, FAREWELL_RESPONSES),
]


def classify_chitchat(raw_text: str) -> Optional[Tuple[str, str]]:
    """
    Detect greetings / small talk that should get a conversational reply
    instead of being treated as an app-launch command.
    Returns (category, reply_text) or None if this looks like a real command.
    """
    t = _strip_wake_phrase(raw_text).strip(" ,.!?")
    if not t:
        # bare wake word with nothing else said, e.g. just "Hey Jarvis"
        return "greeting", random.choice(GREETING_RESPONSES)

    # Only classify short utterances as chitchat — a long sentence containing
    # "hi" somewhere is much more likely to be a real command.
    word_count = len(t.split())
    if word_count > 6:
        return None

    for category, phrases, responses in _CHITCHAT_BUCKETS:
        for phrase in phrases:
            if t == phrase or t.startswith(phrase + " ") or t.endswith(" " + phrase):
                return category, random.choice(responses)
            # tolerate minor typos on short greeting words ("helo", "heyy")
            if word_count <= 2 and len(phrase.split()) == 1:
                _, score = fuzzy_best_match(t, [phrase], threshold=80)
                if score >= 80:
                    return category, random.choice(responses)
    return None


# ─── GitHub integration ("open my top github repo") ─────────────────────────
GITHUB_INTENT_PATTERN = re.compile(
    r"\b(top|best|most\s+starred|popular|main|pinned)?\s*(my\s+)?github\s*(repo|repository|profile)?\b",
    re.IGNORECASE,
)


def is_github_intent(query: str) -> bool:
    return "github" in query and ("repo" in query or "profile" in query or "my github" in query)


def resolve_github_intent(query: str) -> Dict[str, Any]:
    username = (CONFIG.get("github_username") or "").strip()
    if not username:
        raise RuntimeError(
            "I don't know your GitHub username yet. Set it once in the Settings panel "
            "(top-right gear icon) and I'll remember it."
        )

    if "profile" in query and "repo" not in query:
        return open_website(f"https://github.com/{username}")

    # "top" / "best" / "most starred" repo -> query the GitHub API and pick by stars
    import requests
    api_url = f"https://api.github.com/users/{username}/repos?per_page=100&sort=updated"
    try:
        resp = requests.get(api_url, timeout=6, headers={"Accept": "application/vnd.github+json"})
    except Exception as e:
        raise RuntimeError(f"Couldn't reach GitHub right now ({e}).")

    if resp.status_code == 404:
        raise RuntimeError(f"GitHub user '{username}' not found — check the username in Settings.")
    if resp.status_code == 403:
        raise RuntimeError(
            "GitHub is rate-limiting unauthenticated requests from this network right now. "
            "Try again in a few minutes."
        )
    if not resp.ok:
        raise RuntimeError(f"GitHub API returned an error ({resp.status_code}).")

    repos = resp.json()
    if not repos:
        raise RuntimeError(f"'{username}' has no public repositories to open.")

    top = max(repos, key=lambda r: r.get("stargazers_count", 0))
    return open_website(top["html_url"])


# ─── Website Resolver ───────────────────────────────────────────────────────
def resolve_website(query: str) -> Optional[str]:
    """Return a full URL if `query` refers to a known site or looks like a domain."""
    if query in WEBSITE_MAP:
        return WEBSITE_MAP[query]

    words = query.split()
    for name, url in WEBSITE_MAP.items():
        name_words = name.split()
        if len(name_words) == 1:
            # Single-word site names (e.g. "x", "maps") must match a WHOLE
            # word in the query, not a substring — otherwise "xyz123" would
            # false-positive match "x" (Twitter/X) just because it starts
            # with the letter x.
            if name in words:
                return url
        else:
            padded_query = f" {query} "
            if f" {name} " in padded_query or query == name:
                return url

    if query.startswith("http://") or query.startswith("https://"):
        return query
    if DOMAIN_PATTERN.match(query.replace(" ", "")):
        candidate = query.replace(" ", "")
        return candidate if candidate.startswith("http") else f"https://{candidate}"

    # Fuzzy fallback for typo'd site names ("gogle" -> "google") — higher bar
    # than app matching since a wrong redirect is more surprising than a
    # wrong app. Very short names (<=3 chars, e.g. "x") are excluded here
    # too: fuzzy scores on short strings are unreliable and prone to the
    # same false-positive problem as the substring check above.
    fuzzy_candidates = [name for name in WEBSITE_MAP if len(name) > 3]
    match, score = fuzzy_best_match(query, fuzzy_candidates, threshold=82)
    if match:
        return WEBSITE_MAP[match]
    return None


def open_website(url: str) -> Dict[str, Any]:
    """
    Fire off the browser launch on a background thread and return immediately.
    webbrowser.open() can block for several seconds (or hang indefinitely on
    some Linux setups with no fast browser handler) — never call it inline
    inside a request handler.
    """
    def _open():
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            log.warning(f"Website open warning for '{url}': {e}")

    threading.Thread(target=_open, daemon=True).start()
    return {"method": "Website", "target": url}


def _looks_like_path(query: str) -> bool:
    return bool(WIN_PATH_PATTERN.match(query) or UNIX_PATH_PATTERN.match(query))


def launch_windows_app(query: str) -> Dict[str, Any]:
    """
    Multi-tier Windows app launcher with fuzzy matching:
      1. Exact / substring match against indexed Start-Apps + shortcuts + Steam games
      2. Fuzzy match against the same pool (typo tolerance, e.g. "ghost of
         tsunami" -> "Ghost of Tsushima")
      3. Known protocol URIs (spotify:, ms-settings:, etc.)
      4. Explicit file paths, launched as-is
      5. Named folder search (Desktop/Documents/Downloads/home subfolders)
    If NONE of these are confident matches, we raise a clear "couldn't find
    it" error instead of blindly shelling out to `start "" "<garbage>"` —
    that's what used to pop the raw Windows "can't find this app" dialog.
    """
    log.info(f"Attempting to launch Windows app for query: '{query}'")

    candidates: Dict[str, Tuple[str, Any]] = {}
    for name, appid in INSTALLED_APPS_CACHE.items():
        candidates[name] = ("app", appid)
    for name, path in SHORTCUTS_CACHE.items():
        candidates.setdefault(name, ("shortcut", path))
    for name, appid in STEAM_GAMES_CACHE.items():
        # Steam's own manifest is the most reliable source for a game that's
        # actually installed, so let it win over a possibly-stale shortcut.
        candidates[name] = ("steam", appid)

    match_name: Optional[str] = None
    match_score = 100.0

    if query in candidates:
        match_name = query
    else:
        for name in candidates:
            if query == name:
                match_name = name
                break
            # Guard against short-name false positives (the same class of
            # bug fixed in resolve_website): only allow "name is a substring
            # of the query" when name is long enough to be meaningful, and
            # always require the match to land on a word boundary.
            if len(name) >= 3 and re.search(rf"\b{re.escape(name)}\b", query):
                match_name = name
                break
            if len(query) >= 3 and query in name:
                match_name = name
                break

    if not match_name and candidates:
        best, score = fuzzy_best_match(query, list(candidates.keys()), threshold=72)
        if best:
            match_name, match_score = best, score

    if match_name:
        kind, payload = candidates[match_name]
        try:
            if kind == "app":
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{payload}"])
                method = "AppID" if match_score >= 99 else f"AppID (fuzzy match, {match_score:.0f}%)"
                log.info(f"Launched via {method}: {match_name}")
                return {"method": method, "target": match_name, "appid": payload}
            elif kind == "steam":
                subprocess.Popen(["cmd", "/c", "start", "", f"steam://rungameid/{payload}"])
                method = "Steam" if match_score >= 99 else f"Steam (fuzzy match, {match_score:.0f}%)"
                log.info(f"Launched via {method}: {match_name} (AppID {payload})")
                return {"method": method, "target": match_name, "appid": payload}
            else:
                subprocess.Popen(["cmd", "/c", "start", "", str(payload)])
                method = "Shortcut" if match_score >= 99 else f"Shortcut (fuzzy match, {match_score:.0f}%)"
                log.info(f"Launched via {method}: {payload}")
                return {"method": method, "target": match_name}
        except Exception as e:
            log.error(f"Launch failed for matched app '{match_name}': {e}")
            raise RuntimeError(f"I found '{match_name}' but couldn't launch it ({e}).")

    proto = KNOWN_PROTOCOLS.get(query)
    if proto is None:
        for k, v in KNOWN_PROTOCOLS.items():
            if k in query or query in k:
                proto = v
                break

    if proto is not None:
        try:
            if proto == "":
                return open_website("about:blank")
            subprocess.Popen(["cmd", "/c", "start", "", proto])
            log.info(f"Launched via Protocol: {proto}")
            return {"method": "Protocol", "target": proto}
        except Exception as e:
            log.warning(f"Protocol launch failed: {e}")

    if _looks_like_path(query) and Path(query).exists():
        try:
            subprocess.Popen(["cmd", "/c", "start", "", query])
            log.info(f"Launched via explicit path: {query}")
            return {"method": "Path", "target": query}
        except Exception as e:
            raise RuntimeError(f"Found the file '{query}' but couldn't open it ({e}).")

    # Last resort before giving up: maybe this is a folder name that exists
    # somewhere under Desktop/Documents/Downloads/home, just not a "special" one.
    folder_query = re.sub(r"\s+folder$", "", query).strip()
    found_folder = search_named_folder(folder_query or query)
    if found_folder:
        log.info(f"Launched via named-folder search: {found_folder}")
        return open_folder(str(found_folder))

    # Nothing matched with any confidence — fail gracefully instead of
    # blindly shelling out (which used to trigger a raw Windows error popup).
    raise RuntimeError(
        f"I couldn't find “{query}” on this PC — it's not in your installed apps, "
        f"Start Menu/Desktop shortcuts, Steam library, or a website I recognize. "
        f"If it is installed, try the exact name from the Start Menu."
    )


def launch_native_app(query: str) -> Dict[str, Any]:
    system = platform.system()
    if system == "Windows":
        return launch_windows_app(query)
    elif system == "Darwin":
        try:
            subprocess.run(["open", "-a", query], check=True, capture_output=True, timeout=5)
            return {"method": "macOS open", "target": query}
        except Exception:
            raise RuntimeError(
                f"I couldn't find an app called “{query}” on this Mac. "
                f"App-name matching on macOS is more limited than Windows right now."
            )
    else:
        try:
            subprocess.run(["xdg-open", query], check=True, capture_output=True, timeout=5)
            return {"method": "Linux xdg-open", "target": query}
        except Exception:
            raise RuntimeError(
                f"I couldn't find an app called “{query}” on this system. "
                f"App-name matching on Linux is more limited than Windows right now."
            )


def resolve_single_command(raw: str) -> Dict[str, Any]:
    """Resolve exactly one atomic command: close/system/media/utility action,
    GitHub intent, website, folder, or native app launch."""
    raw_wake_stripped = _strip_wake_phrase(raw)
    lowered = raw_wake_stripped.strip().lower()

    # Close-app verbs are checked on the raw (pre-generic-stripping) text,
    # since "close "/"quit " are a distinct verb family from "open ".
    for verb in CLOSE_VERBS:
        if lowered.startswith(verb):
            return close_app(lowered[len(verb):].strip())

    if platform.system() == "Windows":
        sys_result = resolve_system_command(lowered)
        if sys_result:
            return sys_result
        media_result = resolve_media_command(lowered)
        if media_result:
            return media_result

    util_result = resolve_utility_command(lowered)
    if util_result:
        return util_result

    # "search for X" / "google X" / "search X" -> an actual search query,
    # not just the Google homepage.
    search_match = re.match(r"^(?:search(?: for)?|google)\s+(.+)$", lowered)
    if search_match:
        search_term = search_match.group(1).strip()
        if search_term:
            import urllib.parse
            return open_website(f"https://www.google.com/search?q={urllib.parse.quote(search_term)}")

    query = _strip_leading_verb(raw_wake_stripped)
    if not query:
        raise RuntimeError("Empty command after parsing.")

    if is_github_intent(query):
        return resolve_github_intent(query)

    url = resolve_website(query)
    if url:
        return open_website(url)

    if query == "browser":
        return open_website("about:blank")

    if platform.system() == "Windows":
        folder_target = resolve_special_folder(query)
        if folder_target:
            return open_folder(folder_target)

    return launch_native_app(query)


def launch_app(command_text: str) -> Dict[str, Any]:
    """
    Parse a natural-language utterance that may contain MULTIPLE intents
    (e.g. "open chrome and open my top github repo") and execute each in turn.
    """
    sub_commands = split_commands(command_text)
    results: List[Dict[str, Any]] = []
    errors: List[str] = []

    for sub in sub_commands:
        try:
            results.append(resolve_single_command(sub))
        except Exception as e:
            errors.append(str(e))

    if not results and errors:
        raise RuntimeError(" ".join(errors))

    return {
        "results": results,
        "errors": errors,
        "target": ", ".join(r.get("target", "") for r in results),
    }


# ─── Lifespan Context Manager ────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    log.info("Starting Jarvis Engine Lifespan...")
    threading.Thread(target=_init_tts, daemon=True).start()

    # Indexing runs BEFORE the server starts accepting requests (not in a
    # fire-and-forget background thread) — otherwise a command sent right
    # after startup can race ahead of an empty app/game cache and wrongly
    # report "not found" even for things that are actually installed.
    await asyncio.to_thread(index_windows_apps)

    yield
    log.info("Shutting down Jarvis Engine...")


# ─── FastAPI Application ─────────────────────────────────────────────────────
app = FastAPI(
    title="J.A.R.V.I.S AI Assistant Engine",
    description="Local Desktop Automation Server with Voice Synthesis & Arc Reactor HUD UI.",
    version="2.7.0",
    lifespan=lifespan,
)

_host = os.getenv("JARVIS_HOST", "127.0.0.1")
_port = os.getenv("JARVIS_PORT", "8000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        f"http://{_host}:{_port}"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR)), name="static")


@app.get("/favicon.ico")
async def favicon():
    icon_file = BASE_DIR / "assets" / "jarvis_icon.ico"
    if icon_file.exists():
        return FileResponse(str(icon_file), headers={"Cache-Control": "public, max-age=86400"})
    raise HTTPException(status_code=404, detail="favicon not found")


class CommandPayload(BaseModel):
    command: str


class TTSPayload(BaseModel):
    text: str


class ConfigPayload(BaseModel):
    user_name: Optional[str] = None
    github_username: Optional[str] = None


class AutostartPayload(BaseModel):
    enable: bool


@app.get("/", response_class=FileResponse)
async def serve_index():
    index_file = BASE_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    # Explicitly forbid caching — otherwise a browser can silently keep
    # serving an old cached copy of the UI even after main.py/index.html
    # have been updated, making it look like changes "didn't happen".
    return FileResponse(
        str(index_file),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/health")
async def health_check():
    return {
        "status": "online",
        "assistant": "Jarvis",
        "version": "2.7.0",
        "platform": platform.system(),
        "indexed_apps": len(INSTALLED_APPS_CACHE),
        "indexed_shortcuts": len(SHORTCUTS_CACHE),
        "indexed_steam_games": len(STEAM_GAMES_CACHE),
        "indexing_complete": INDEXING_COMPLETE.is_set(),
        "fuzzy_engine": "rapidfuzz" if HAVE_RAPIDFUZZ else "difflib",
        "timestamp": time.time(),
    }


@app.post("/reindex")
async def reindex_endpoint():
    """Force a re-scan of installed apps, shortcuts, and Steam games without
    restarting the server — useful right after installing new software."""
    import asyncio
    INDEXING_COMPLETE.clear()
    await asyncio.to_thread(index_windows_apps)
    return {
        "success": True,
        "indexed_apps": len(INSTALLED_APPS_CACHE),
        "indexed_shortcuts": len(SHORTCUTS_CACHE),
        "indexed_steam_games": len(STEAM_GAMES_CACHE),
    }


@app.get("/config")
async def get_config():
    return CONFIG


@app.post("/config")
async def set_config(payload: ConfigPayload):
    if payload.user_name is not None:
        CONFIG["user_name"] = payload.user_name.strip() or "Guest"
    if payload.github_username is not None:
        CONFIG["github_username"] = payload.github_username.strip()
    save_config(CONFIG)
    return {"success": True, "config": CONFIG}


@app.get("/autostart")
async def get_autostart():
    return {
        "enabled": is_autostart_enabled(),
        "asked": bool(CONFIG.get("asked_autostart", False)),
        "supported": platform.system() == "Windows",
    }


@app.post("/autostart")
async def set_autostart(payload: AutostartPayload):
    CONFIG["asked_autostart"] = True
    try:
        if payload.enable:
            enable_autostart()
        else:
            disable_autostart()
        save_config(CONFIG)
        return {"success": True, "enabled": is_autostart_enabled()}
    except Exception as e:
        save_config(CONFIG)
        raise HTTPException(status_code=422, detail=str(e))


def _format_result_message(r: Dict[str, Any]) -> str:
    """Build a natural spoken/written message for one resolved sub-command.
    Different action types read very differently — "Opening It's 07:13 AM"
    (the old generic "Opening {target}.title()" behavior) is wrong for
    anything that isn't actually launching something."""
    method = r.get("method", "")
    target = r.get("target", "") or ""
    if method == "Info":
        return target  # already a complete natural sentence
    if method == "Close":
        return f"Closed {target}"
    if method == "System":
        return target[0].upper() + target[1:] if target else "Done."
    if method == "Media":
        return target[0].upper() + target[1:] if target else "Done."
    if method == "Utility":
        return target[0].upper() + target[1:] if target else "Done."
    return f"Opening {target.title()}" if target else "Done."


@app.post("/launch")
async def launch_endpoint(payload: CommandPayload):
    import asyncio

    cmd = payload.command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Command text cannot be empty.")

    # Greetings / small talk get a conversational reply — never treated as
    # an app-launch attempt. Speaking is handled by the browser (frontend
    # Web Speech Synthesis) so the response is heard immediately and
    # doesn't depend on server-side TTS/OS voices being configured.
    chitchat = classify_chitchat(cmd)
    if chitchat:
        category, reply = chitchat
        return {"success": True, "chat": True, "category": category, "message": reply}

    def is_deterministic(c: str) -> bool:
        cl = c.lower()
        if any(cl.startswith(v) for v in ("open ", "launch ", "run ", "start ", "play ", "take a ", "what time", "lock ")):
            return True
        if cl in ("shutdown", "restart", "sleep", "lock", "hibernate", "logoff", "log off", "confirm", "yes"):
            return True
        if "recycle bin" in cl or "trash" in cl:
            return True
        return False

    try:
        # Offload to a thread: app-launching itself is fast, but GitHub API
        # calls involve real network I/O and must not block the event loop.
        if is_deterministic(cmd):
            res = await asyncio.to_thread(launch_app, cmd)
            results = res.get("results") or []
            msg = "; ".join(_format_result_message(r) for r in results) or "Done."
            if res.get("errors"):
                msg += f" (partial failure: {' '.join(res['errors'])})"
            return {"success": True, "message": msg, "details": res}
        else:
            try:
                ai_res = await asyncio.to_thread(process_command_with_ai, cmd, launch_app)
                return ai_res
            except Exception as e:
                log.warning(f"AI Brain failed, falling back to rule engine: {e}")
                res = await asyncio.to_thread(launch_app, cmd)
                results = res.get("results") or []
                msg = "; ".join(_format_result_message(r) for r in results) or "Done."
                if res.get("errors"):
                    msg += f" (partial failure: {' '.join(res['errors'])})"
                return {"success": True, "message": msg, "details": res}
    except Exception as err:
        err_msg = str(err)
        raise HTTPException(status_code=422, detail=err_msg)


@app.post("/speak")
async def speak_endpoint(payload: TTSPayload):
    text = payload.text.strip()
    if text:
        speak(text)
        return {"success": True, "text": text}
    return {"success": False, "detail": "Empty text"}


@app.get("/apps")
async def list_apps_endpoint():
    app_list = sorted(set(
        list(INSTALLED_APPS_CACHE.keys()) + list(SHORTCUTS_CACHE.keys()) + list(STEAM_GAMES_CACHE.keys())
        + list(KNOWN_PROTOCOLS.keys()) + list(WEBSITE_MAP.keys()) + list(SPECIAL_FOLDERS.keys())
    ))
    return {"count": len(app_list), "apps": app_list}


if __name__ == "__main__":
    port = int(os.getenv("JARVIS_PORT", "8000"))
    host = os.getenv("JARVIS_HOST", "127.0.0.1")
    uvicorn.run("main:app", host=host, port=port, reload=False)
