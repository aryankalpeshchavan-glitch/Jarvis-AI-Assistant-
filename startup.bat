@echo off
:: ═══════════════════════════════════════════════════════════════════
::  JARVIS AI ASSISTANT — Clean Desktop Automation Startup
:: ═══════════════════════════════════════════════════════════════════
TITLE Jarvis AI Engine

SET JARVIS_DIR=%~dp0
SET PYTHON_EXE=python

echo.
echo  ===========================================
echo   J.A.R.V.I.S — DESKTOP AUTOMATION ENGINE
echo  ===========================================
echo.

:: ── 1. Start Jarvis Companion Lifecycle ─────────────────────────────
echo [*] Starting Jarvis Companion (Tray, Backend, UI)...
start "Jarvis Companion" /MIN cmd /c "%PYTHON_EXE% companion.py"

echo [+] Jarvis initialized. It will appear in your System Tray shortly.
