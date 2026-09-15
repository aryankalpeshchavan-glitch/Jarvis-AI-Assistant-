import os
import sys
import time
import ctypes
import threading
import logging
from pathlib import Path

import uvicorn
import webview
import pystray
from PIL import Image
import keyboard
import requests

from main import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("JarvisCompanion")

# ─── 1. Single Instance Mutex ──────────────────────────────────────────────────
# Prevents multiple copies of Jarvis from running simultaneously.
MUTEX_NAME = "Jarvis_Companion_Mutex_2.0"
mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    print("Jarvis is already running. Exiting.")
    # Here we could optionally use FindWindow to bring the existing instance to the front.
    sys.exit(0)

# ─── 2. State & Lifecycle variables ───────────────────────────────────────────
window = None
tray_icon = None
is_quitting = False
is_ui_visible = True

# ─── 3. Tray Actions & Hotkey ─────────────────────────────────────────────────
def toggle_window():
    global is_ui_visible
    log.info("HOTKEY CALLBACK ENTERED")
    if window:
        try:
            if is_ui_visible:
                log.info("Attempting to hide()...")
                window.hide()
                is_ui_visible = False
            else:
                log.info("Attempting to show() and restore()...")
                window.show()
                window.restore()
                is_ui_visible = True
        except Exception as e:
            log.error(f"Exception in toggle_window: {e}", exc_info=True)

def show_jarvis(icon=None, item=None):
    global is_ui_visible
    if window:
        window.show()
        window.restore()
        is_ui_visible = True

def hide_jarvis(icon=None, item=None):
    global is_ui_visible
    if window:
        window.hide()
        is_ui_visible = False

def quit_jarvis(icon=None, item=None):
    global is_quitting
    is_quitting = True
    log.info("Quitting Jarvis...")
    if tray_icon:
        tray_icon.stop()
    if window:
        window.destroy()
    # The application will naturally exit once webview.start() completes.

def on_closing():
    global is_quitting, is_ui_visible
    if is_quitting:
        return True  # Allow the window to be destroyed
    
    # Otherwise, just hide the window to keep Jarvis in the background
    window.hide()
    is_ui_visible = False
    return False

# ─── 4. Background Services ───────────────────────────────────────────────────
def start_fastapi():
    log.info("Starting FastAPI backend in background...")
    # Using access_log=False to keep the console clean, since Jarvis logs to file/console manually
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning", access_log=False)

def start_tray():
    global tray_icon
    icon_path = Path(__file__).parent / "assets" / "jarvis_icon.ico"
    if icon_path.exists():
        image = Image.open(icon_path)
    else:
        # Fallback empty image if asset is missing
        image = Image.new('RGB', (64, 64), color=(30, 30, 30))

    menu = (
        pystray.MenuItem('Show Jarvis', show_jarvis, default=True),
        pystray.MenuItem('Hide Jarvis', hide_jarvis),
        pystray.MenuItem('Talk to Jarvis (Placeholder)', show_jarvis),
        pystray.MenuItem('Startup Briefing (Placeholder)', lambda: None),
        pystray.MenuItem('Settings (Placeholder)', lambda: None),
        pystray.MenuItem('Quit Jarvis', quit_jarvis),
    )
    tray_icon = pystray.Icon("Jarvis", image, "J.A.R.V.I.S.", menu)
    log.info("Starting System Tray icon...")
    tray_icon.run()

# ─── 5. Main Entry Point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    # Start the backend server
    threading.Thread(target=start_fastapi, daemon=True).start()
    
    # Wait for the backend to become healthy
    log.info("Waiting for FastAPI server to initialize...")
    server_ready = False
    for _ in range(20):
        try:
            r = requests.get("http://127.0.0.1:8000/health", timeout=1)
            if r.status_code == 200:
                server_ready = True
                break
        except Exception:
            pass
        time.sleep(1)
        
    if not server_ready:
        log.error("FastAPI server failed to start within 20 seconds. Exiting.")
        ctypes.windll.kernel32.ReleaseMutex(mutex)
        sys.exit(1)

    log.info("Server is online.")

    # Start the tray icon in a daemon thread
    threading.Thread(target=start_tray, daemon=True).start()

    # Register the global hotkey
    try:
        keyboard.add_hotkey('ctrl+shift+space', toggle_window)
        log.info("Registered global hotkey: Ctrl+Shift+Space")
    except Exception as e:
        log.warning(f"Could not register global hotkey: {e}")

    # Create and start the webview companion
    window = webview.create_window(
        'J.A.R.V.I.S AI Assistant Engine', 
        'http://127.0.0.1:8000',
        width=1080, height=720,
        text_select=False
    )
    window.events.closing += on_closing

    log.info("Launching Companion UI...")
    webview.start()

    # Cleanup after window is destroyed (during quit)
    log.info("Cleaning up...")
    keyboard.unhook_all()
    ctypes.windll.kernel32.ReleaseMutex(mutex)
    log.info("Jarvis lifecycle complete.")
