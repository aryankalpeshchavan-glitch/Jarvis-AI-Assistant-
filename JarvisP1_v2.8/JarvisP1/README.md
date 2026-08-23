# J.A.R.V.I.S — Open-Source Local Desktop AI Assistant

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-009688.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-lightgrey.svg)]()

A local, open-source desktop AI assistant with a wake-word voice interface
("**Hey Jarvis**") and a minimal pulsing-core interface. It runs a small
FastAPI server on your own machine that can launch apps, close them, control
system power, and more — no cloud account, no data leaving your PC.

## Architecture — why this shape

Browsers can't launch desktop apps or run system commands (that's a security
boundary, not a limitation of this project). So Jarvis is a **local web app**:

- `main.py` — a FastAPI backend that does the actual work (launching/closing
  apps, system power actions, opening sites, speaking replies).
- `index.html` — the UI, served by that same backend and opened in your
  browser (or a borderless Chrome "app mode" window via `startup.bat`).

This keeps the whole thing **open source and hackable** (just Python + HTML/JS,
no build step) while still being able to control your desktop. For people who
don't want to install Python, `build_exe.py` packages the same app into a
double-click `Jarvis.exe` using PyInstaller — attach that to a GitHub Release.
Source stays open; the `.exe` is just a convenience artifact.

## Features

**Voice & interface**
- 🎙️ **Wake-word activation** — say "Hey Jarvis" and it starts listening
  automatically. Push-to-talk mic button also available.
- 🔊 **Spoken responses** — every reply is spoken aloud via the browser's
  built-in speech synthesis, not just shown as text.
- 💬 **Greeting & small-talk detection** — "hello" gets a conversational
  reply instead of trying to launch an app called "hello".
- 🖥️ **Minimal pulsing-core UI** — a single glowing particle-sphere as the
  focal point, with a collapsible side drawer (session log, weather, quick
  launch, backend status) so the main view stays clean.

**Opening things**
- 🗣️ **Multi-intent commands** — "open browser and open google" runs both.
- 🔎 **Fuzzy app matching** — "open ghost of tsunami" still launches "Ghost
  of Tsushima" (powered by `rapidfuzz`).
- 🎮 **Steam game detection** — reads Steam's own library manifests directly
  (across all library folders), so installed games launch reliably via
  `steam://rungameid/...` even without a Start Menu shortcut.
- 📁 **Folder opening** — "open downloads", "open desktop", "open d drive",
  or a custom folder name under Desktop/Documents/Downloads/home.
- 🌐 **Reliable website opening** — via Python's `webbrowser` module,
  non-blocking. "search for X" runs an actual Google search, not just the
  homepage.
- 🐙 **"Open my top GitHub repo"** — set your GitHub username once in
  Settings and Jarvis opens your most-starred public repo via the GitHub API.
- 🚫 **No blind shell fallback** — unrecognized commands get a clear spoken
  + written explanation instead of a raw Windows error dialog.

**Controlling the PC**
- ❌ **Close apps** — "close spotify", "quit chrome" (matched against
  actually-running processes).
- 🔒 **Lock / sleep** — execute immediately, fully reversible.
- ⏻ **Shutdown / restart / log off** — require you to say **"confirm"**
  within 20 seconds first. This is deliberate: a single misheard word should
  never actually power off your machine or lose unsaved work.
- 🔊 **Media controls** — mute, volume up/down, play/pause, next/previous track.
- 📸 **Screenshot** (saved to Pictures) and **empty recycle bin**.
- 🕐 **Time/date queries** — "what time is it".

**Setup & reliability**
- 🚀 **Auto-start on boot** — first-run prompt asks permission once; backed
  by real `/autostart` endpoints, not just a doc you have to run manually.
- ⏱️ **No startup race condition** — app/game indexing runs to completion
  *before* the server accepts requests, so the first command you send won't
  wrongly fail.
- 📱 **Works from your phone too** — see [Mobile / LAN access](#mobile--lan-access-controlling-your-pc-from-your-phone) below.

## Quick Start

### 1. Prerequisites
- **Python 3.10+**
- **Google Chrome** or **Microsoft Edge** (for app-mode window; any browser works for the plain URL)

### 2. Install & run
```powershell
git clone https://github.com/YOUR_USERNAME/JarvisP1.git
cd JarvisP1
pip install -r requirements.txt
python main.py
```
Open **http://127.0.0.1:8000** in your browser — or double-click
**`startup.bat`** to start the backend and open the UI automatically.

> **If double-clicking `startup.bat` doesn't run it** (e.g. it opens in a
> code editor instead, or seems to do nothing), your system's `.bat` file
> association has likely been changed by something else you've installed.
> Right-click **`create_shortcut.ps1`** → *Run with PowerShell* once — it
> creates a Desktop shortcut that launches Jarvis reliably regardless of
> that association, using the Jarvis icon.

Click the ear icon to arm wake-word listening, then just say
**"Hey Jarvis, open spotify"**. Every response is spoken aloud automatically.

Click the gear icon (top-right) once to set your name and GitHub username.
Click the arrow tab on the left edge to open the drawer.

On first launch, you'll be asked once whether Jarvis should start
automatically with your PC — answer however you like; you can change it
later via the same prompt logic through `/autostart`.

### 3. Build a standalone .exe
```powershell
pip install pyinstaller
python build_exe.py
```
Produces `dist/Jarvis/Jarvis.exe` with the Jarvis icon — no Python required
to run it. See [Packaging as an .exe](#packaging-as-an-exe-step-by-step) below for the full walkthrough.

## Mobile / LAN access — controlling your PC from your phone

A Windows `.exe` genuinely cannot run on a phone — that's not something any
amount of code changes fixes. What **does** work: your phone's browser
connecting to the same local server over your home WiFi, since the whole UI
is just a webpage.

**Steps:**
1. On the PC running Jarvis, find its local IP address:
   ```powershell
   ipconfig
   ```
   Look for "IPv4 Address" under your active adapter (e.g. `192.168.1.42`).
2. Start Jarvis listening on your whole network instead of just this PC:
   ```powershell
   set JARVIS_HOST=0.0.0.0
   python main.py
   ```
3. On your phone (connected to the **same WiFi network**), open:
   ```
   http://192.168.1.42:8000
   ```
   (using the IP from step 1). The UI, wake-word listening, and voice
   responses all work the same as on desktop.

**⚠️ Security note:** `JARVIS_HOST=0.0.0.0` makes the server reachable by
**any device on your network**, not just your phone — including opening and
closing apps, and (after a spoken "confirm") shutting down your PC. Only do
this on a network you trust (e.g. your home WiFi, not a public/office one),
and switch back to the default `127.0.0.1` when you're done if that's a
concern. This is why it's opt-in via an environment variable rather than
the default.

## Packaging as an .exe, step by step

1. Make sure everything runs correctly from source first (`python main.py`,
   test in your browser).
2. Install the build tool: `pip install pyinstaller` (already in
   `requirements.txt`).
3. Run `python build_exe.py`. This bundles `main.py`, `index.html`, and the
   `assets/` folder (including the Jarvis icon) into `dist/Jarvis/`.
4. Test it: double-click `dist/Jarvis/Jarvis.exe`. It should start the
   server and open the UI, with the Jarvis icon in the taskbar/title bar.
5. Zip the whole `dist/Jarvis` folder (not just the `.exe` — it needs its
   bundled files alongside it) — e.g. `Jarvis-v2.7-windows.zip`.
6. Attach that zip to a GitHub Release (see below) so others can download
   and run it without installing Python at all.

## Uploading to GitHub, step by step

1. Create a new repository at [github.com/new](https://github.com/new) —
   name it (e.g. `JarvisP1`), and **don't** initialize it with a README
   (you already have one).
2. From inside this project folder:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: Jarvis AI assistant"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/JarvisP1.git
   git push -u origin main
   ```
3. **Before pushing**, double-check `jarvis_config.json` isn't present in
   your folder (it can hold your GitHub username) — `.gitignore` already
   excludes it, but it's worth a glance.
4. Add topics on the repo page (`ai-assistant`, `jarvis`, `voice-assistant`,
   `fastapi`) so it's discoverable.
5. **Optional — attach the .exe:** on the repo page, go to *Releases* →
   *Create a new release* → upload the zipped `dist/Jarvis` folder from the
   packaging steps above. Tag it (e.g. `v2.7`) and publish.

## REST API

| Method | Endpoint     | Description |
|--------|--------------|-------------|
| `GET`  | `/`          | Serves the UI (no-cache headers, so updates always show) |
| `GET`  | `/health`    | Health check, indexed apps/games count, active fuzzy-match engine |
| `POST` | `/launch`    | `{"command": "..."}` — multi-intent, fuzzy-matched, handles opening, closing, system actions, media, and chitchat |
| `POST` | `/speak`     | `{"text": "Hello"}` — server-side TTS trigger (optional; the browser speaks by default) |
| `GET`  | `/apps`      | Lists all known apps / games / protocols / websites / folders |
| `POST` | `/reindex`   | Force a re-scan of installed apps, shortcuts, and Steam games without restarting |
| `GET`  | `/config`    | Current settings (name, GitHub username) |
| `POST` | `/config`    | `{"user_name": "...", "github_username": "..."}` — persisted to `jarvis_config.json` |
| `GET`  | `/autostart` | Whether auto-start-on-boot is enabled, and whether the user has been asked yet |
| `POST` | `/autostart` | `{"enable": true/false}` — registers/removes the Windows Startup entry |

## Testing

Two test suites are included, covering 58 cases:
```powershell
python test_engine.py   # fuzzy matching, command parsing, system-command safety gating
python test_api.py      # full HTTP endpoint behavior via FastAPI's TestClient (in-process, no server needed)
```
Both should print `RESULTS: N passed, 0 failed`. Run them after any change to `main.py` before committing.

## Safety notes

- **Shutdown/restart/log-off require spoken confirmation.** These commands
  reply asking you to say "confirm" within 20 seconds rather than executing
  immediately — a misheard "shut down" should never actually shut down your PC.
- **Closing apps uses the real process list**, not guesswork — it reads
  `tasklist` output and fuzzy-matches against what's actually running, so it
  won't try to kill something that isn't open.
- **LAN mode (`JARVIS_HOST=0.0.0.0`) is opt-in, not default**, precisely
  because it exposes these controls to your whole network. See the Mobile
  section above.

## Known limitations

- The app/game launcher, folder opening, closing apps, and system/media
  commands are Windows-only; on macOS/Linux, app launching falls back to
  `open -a` / `xdg-open`, and website opening / the UI work everywhere.
- Speech recognition uses the browser's built-in Web Speech API (Chrome/Edge
  support it well; Firefox support is limited).
- Auto-start-on-boot is currently Windows-only (`/autostart` reports
  `"supported": false` elsewhere).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome — this is
meant to be a real community project, not a one-off script.

## License

MIT — see [LICENSE](LICENSE).
