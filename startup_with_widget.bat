@echo off
cd /d "%~dp0"
echo Starting JARVIS Desktop Companion Widget...
start "JARVIS Reactor" python desktop_companion.py
echo Starting Main JARVIS System...
python companion.py
pause
