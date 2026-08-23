"""
Build a standalone Windows executable for Jarvis using PyInstaller.

Usage:
    pip install -r requirements.txt
    python build_exe.py

Output:
    dist/Jarvis/Jarvis.exe   (double-click to run — no Python required)

This is meant for GitHub Releases: keep developing from source (main.py +
index.html), but attach the zipped dist/Jarvis folder to a release so
non-technical users can just download and run it.
"""
import subprocess
import sys
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()


def main():
    icon_path = BASE_DIR / "assets" / "jarvis_icon.ico"
    print("[*] Building Jarvis.exe with PyInstaller...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "Jarvis",
        "--onedir",
        "--noconsole",
        "--add-data", f"{BASE_DIR / 'index.html'}{';' if sys.platform.startswith('win') else ':'}.",
        "--add-data", f"{BASE_DIR / 'assets'}{';' if sys.platform.startswith('win') else ':'}assets",
    ]
    if icon_path.exists():
        cmd += ["--icon", str(icon_path)]
    else:
        print("[!] assets/jarvis_icon.ico not found — building without a custom icon.")
    cmd.append(str(BASE_DIR / "main.py"))
    subprocess.run(cmd, check=True)

    dist_dir = BASE_DIR / "dist" / "Jarvis"
    print(f"\n[+] Build complete: {dist_dir}")
    print("    Zip that folder and attach it to a GitHub Release.")
    print("    Users run Jarvis.exe directly — no Python install needed.")


if __name__ == "__main__":
    main()
