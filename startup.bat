@echo off
:: ═══════════════════════════════════════════════════════════════════
::  JARVIS DESKTOP COMPANION — Silent Startup Launcher
::  Launches ONLY the desktop companion widget (jarvis_widget.py).
::  Uses pythonw.exe so NO console window appears.
::  The main JARVIS UI is launched on demand when the user clicks
::  the companion reactor widget.
:: ═══════════════════════════════════════════════════════════════════

SET JARVIS_DIR=%~dp0

:: Determine the pythonw.exe path (same folder as python.exe)
FOR /F "delims=" %%P IN ('python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))" 2^>nul') DO SET PYTHONW_EXE=%%P

IF NOT EXIST "%PYTHONW_EXE%" (
    :: Fallback: try plain pythonw on PATH
    SET PYTHONW_EXE=pythonw
)

:: Launch ONLY the desktop companion widget — windowlessly, no console
start "" /B "%PYTHONW_EXE%" "%JARVIS_DIR%jarvis_widget.py"

:: Exit this bat window immediately so nothing is visible
exit
