"""
setup_startup.py — Jarvis AI Assistant Startup Configurator
============================================================
Automatically installs Jarvis to run at Windows/macOS login.

Usage:
    python setup_startup.py install    # Register with OS startup
    python setup_startup.py remove     # Unregister from OS startup
    python setup_startup.py status     # Check current registration
    python setup_startup.py run        # Launch Jarvis right now
"""

import os
import sys
import shutil
import platform
import subprocess
import argparse
import textwrap
from pathlib import Path

PROJECT_DIR  = Path(__file__).parent.resolve()
STARTUP_BAT  = PROJECT_DIR / "startup.bat"
PLIST_NAME   = "com.aryan.jarvis"

# ─── Helper ────────────────────────────────────────────────────────
def log(msg:  str, level: str = "INFO"):
    icons = {"INFO": "ℹ️", "OK": "✅", "WARN": "⚠️", "ERR": "❌"}
    print(f"  {icons.get(level, '•')} {msg}")


# ════════════════════════════════════════════════════════════════════
# WINDOWS
# ════════════════════════════════════════════════════════════════════
def install_windows():
    startup_folder = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    if not startup_folder.exists():
        log(f"Startup folder not found: {startup_folder}", "ERR")
        sys.exit(1)

    dest = startup_folder / "Jarvis.bat"

    # Write a launcher stub that sets the working dir first
    stub = textwrap.dedent(f"""\
        @echo off
        cd /d "{PROJECT_DIR}"
        call "{STARTUP_BAT}"
    """)
    dest.write_text(stub, encoding="utf-8")

    log(f"Stub installed → {dest}", "OK")
    log("Jarvis will now launch automatically on next Windows login.", "OK")

    # Also create a desktop shortcut via PowerShell
    _create_shortcut_windows()


def remove_windows():
    startup_folder = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    dest = startup_folder / "Jarvis.bat"
    if dest.exists():
        dest.unlink()
        log(f"Removed startup entry: {dest}", "OK")
    else:
        log("No startup entry found. Nothing to remove.", "WARN")


def status_windows():
    startup_folder = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    dest = startup_folder / "Jarvis.bat"
    if dest.exists():
        log(f"Jarvis IS registered for startup → {dest}", "OK")
    else:
        log("Jarvis is NOT registered for startup.", "WARN")


def _create_shortcut_windows():
    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
    shortcut = desktop / "Jarvis.lnk"
    ps = textwrap.dedent(f"""\
        $ws  = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut('{shortcut}')
        $lnk.TargetPath       = '{STARTUP_BAT}'
        $lnk.WorkingDirectory = '{PROJECT_DIR}'
        $lnk.Description      = 'Jarvis AI Assistant'
        $lnk.Save()
    """)
    try:
        subprocess.run(["powershell", "-Command", ps], check=True, capture_output=True)
        log(f"Desktop shortcut created → {shortcut}", "OK")
    except Exception as e:
        log(f"Could not create desktop shortcut: {e}", "WARN")


# ════════════════════════════════════════════════════════════════════
# macOS
# ════════════════════════════════════════════════════════════════════
PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>              <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>{project_dir}/startup.sh</string>
    </array>
    <key>RunAtLoad</key>          <true/>
    <key>KeepAlive</key>          <false/>
    <key>WorkingDirectory</key>   <string>{project_dir}</string>
    <key>StandardOutPath</key>    <string>{project_dir}/jarvis.log</string>
    <key>StandardErrorPath</key>  <string>{project_dir}/jarvis_err.log</string>
</dict>
</plist>
"""

STARTUP_SH_CONTENT = """\
#!/bin/bash
# Jarvis macOS startup script
cd "$(dirname "$0")"
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000 &
sleep 3
open -a "Google Chrome" --args --app=http://127.0.0.1:8000 --window-size=1100,750
"""


def install_macos():
    agents = Path.home() / "Library/LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)

    plist_path = agents / f"{PLIST_NAME}.plist"
    plist_path.write_text(
        PLIST_TEMPLATE.format(label=PLIST_NAME, project_dir=PROJECT_DIR),
        encoding="utf-8",
    )
    log(f"plist written → {plist_path}", "OK")

    # Create startup.sh
    sh = PROJECT_DIR / "startup.sh"
    sh.write_text(STARTUP_SH_CONTENT, encoding="utf-8")
    sh.chmod(0o755)
    log("startup.sh created and made executable.", "OK")

    # Load immediately
    subprocess.run(["launchctl", "load", str(plist_path)], check=False)
    log("LaunchAgent loaded. Jarvis will auto-start on login.", "OK")


def remove_macos():
    plist_path = Path.home() / f"Library/LaunchAgents/{PLIST_NAME}.plist"
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
        plist_path.unlink()
        log(f"Removed: {plist_path}", "OK")
    else:
        log("No plist found. Nothing to remove.", "WARN")


def status_macos():
    plist_path = Path.home() / f"Library/LaunchAgents/{PLIST_NAME}.plist"
    if plist_path.exists():
        log(f"Jarvis IS registered (LaunchAgent) → {plist_path}", "OK")
    else:
        log("Jarvis is NOT registered for login.", "WARN")


# ════════════════════════════════════════════════════════════════════
# DEPENDENCY INSTALLER
# ════════════════════════════════════════════════════════════════════
def install_deps():
    req = PROJECT_DIR / "requirements.txt"
    log("Installing Python dependencies...", "INFO")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req), "--quiet"],
        capture_output=False,
    )
    if result.returncode == 0:
        log("All dependencies installed successfully.", "OK")
    else:
        log("Pip install encountered errors — check output above.", "WARN")


# ════════════════════════════════════════════════════════════════════
# RUN JARVIS NOW
# ════════════════════════════════════════════════════════════════════
def run_now():
    if platform.system() == "Windows":
        subprocess.Popen(
            ["cmd", "/c", str(STARTUP_BAT)],
            cwd=str(PROJECT_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        log("Jarvis launched in a new console window.", "OK")
    else:
        sh = PROJECT_DIR / "startup.sh"
        if sh.exists():
            subprocess.Popen(["bash", str(sh)], cwd=str(PROJECT_DIR))
            log("Jarvis launched via startup.sh.", "OK")
        else:
            log("startup.sh not found. Run install first.", "ERR")


# ════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="Jarvis AI Assistant — Startup Configurator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python setup_startup.py install    # Register startup on this OS
              python setup_startup.py remove     # Unregister
              python setup_startup.py status     # Check registration
              python setup_startup.py run        # Launch Jarvis right now
        """),
    )
    parser.add_argument(
        "action",
        choices=["install", "remove", "status", "run", "deps"],
        help="Action to perform",
    )
    args = parser.parse_args()

    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║  Jarvis Startup Configurator v2.0    ║")
    print("  ╚══════════════════════════════════════╝")
    print()

    os_name = platform.system()
    log(f"Detected OS: {os_name}", "INFO")
    log(f"Project dir: {PROJECT_DIR}", "INFO")
    print()

    action = args.action

    if action == "deps":
        install_deps()
    elif action == "run":
        run_now()
    elif os_name == "Windows":
        if action == "install":
            install_deps()
            install_windows()
        elif action == "remove":
            remove_windows()
        elif action == "status":
            status_windows()
    elif os_name == "Darwin":
        if action == "install":
            install_deps()
            install_macos()
        elif action == "remove":
            remove_macos()
        elif action == "status":
            status_macos()
    else:
        log(f"Unsupported OS: {os_name}. Manual setup required.", "WARN")
        log("Run: uvicorn main:app --host 127.0.0.1 --port 8000", "INFO")

    print()


if __name__ == "__main__":
    main()
