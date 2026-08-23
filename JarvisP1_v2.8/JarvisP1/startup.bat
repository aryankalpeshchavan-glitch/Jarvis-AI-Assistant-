@echo off
:: ═══════════════════════════════════════════════════════════════════
::  JARVIS AI ASSISTANT — Clean Desktop Automation Startup
:: ═══════════════════════════════════════════════════════════════════
TITLE Jarvis AI Engine

SET JARVIS_DIR=%~dp0
SET PYTHON_EXE=python
SET PORT=8000
SET URL=http://127.0.0.1:%PORT%

SET CHROME1=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe
SET CHROME2=C:\Program Files\Google\Chrome\Application\chrome.exe
SET CHROME3=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
SET EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe

echo.
echo  ===========================================
echo   J.A.R.V.I.S — DESKTOP AUTOMATION ENGINE
echo  ===========================================
echo.

:: ── 1. Start FastAPI backend ───────────────────────────────────────
echo [*] Starting Jarvis Core Server on port %PORT%...
start "Jarvis Core Engine" /MIN cmd /c "%PYTHON_EXE% main.py"

:: ── 2. Wait for health check ──────────────────────────────────────
echo [*] Waiting for core server to initialize...
SET RETRY_COUNT=0
:WAIT_LOOP
SET /A RETRY_COUNT+=1
if %RETRY_COUNT% GTR 20 (
  echo.
  echo [!] Jarvis server did not respond after 20 seconds.
  echo [!] Common causes: Python isn't installed / isn't on PATH, or a dependency
  echo [!] is missing. Try running "pip install -r requirements.txt" then
  echo [!] "python main.py" directly in this folder to see the actual error.
  echo.
  pause
  exit /b 1
)
timeout /t 1 /nobreak >nul
curl -s -o nul -w "%%{http_code}" %URL%/health | findstr "200" >nul 2>&1
if errorlevel 1 goto WAIT_LOOP
echo [+] Server online!

:: ── 3. Open UI in browser app mode ────────────────────────────────
echo [*] Launching Jarvis Interface...

if exist "%CHROME1%" (
  start "" "%CHROME1%" --app=%URL% --window-size=1080,720 --disable-extensions --no-default-browser-check
  goto DONE
)
if exist "%CHROME2%" (
  start "" "%CHROME2%" --app=%URL% --window-size=1080,720 --disable-extensions --no-default-browser-check
  goto DONE
)
if exist "%CHROME3%" (
  start "" "%CHROME3%" --app=%URL% --window-size=1080,720 --disable-extensions --no-default-browser-check
  goto DONE
)
if exist "%EDGE%" (
  start "" "%EDGE%" --app=%URL% --window-size=1080,720
  goto DONE
)

start %URL%

:DONE
echo [+] Jarvis is active.
