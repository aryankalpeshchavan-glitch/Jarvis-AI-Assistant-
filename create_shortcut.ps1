# Creates a Desktop shortcut for J.A.R.V.I.S that launches the companion widget silently.
#
# The shortcut launches startup.bat via cmd /c so no .bat association issues apply.
# startup.bat uses pythonw.exe internally, so NO console window appears after launch.
#
# Usage: right-click this file -> Run with PowerShell (once).
# Creates: a "Jarvis" shortcut on your Desktop.

$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartupBat   = Join-Path $ScriptDir "startup.bat"
$IconPath     = Join-Path $ScriptDir "assets\jarvis_icon.ico"
$ShortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Jarvis.lnk"

if (-not (Test-Path $StartupBat)) {
    Write-Host "ERROR: startup.bat not found next to this script. Run this from inside the JarvisP1 folder." -ForegroundColor Red
    exit 1
}

$WshShell             = New-Object -ComObject WScript.Shell
$Shortcut             = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath  = "$env:SystemRoot\System32\cmd.exe"
$Shortcut.Arguments   = "/c `"$StartupBat`""
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.WindowStyle = 0   # 0 = hidden, so cmd window doesn't flash
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = $IconPath
}
$Shortcut.Description = "Launch J.A.R.V.I.S Companion"
$Shortcut.Save()

Write-Host "Desktop shortcut created: $ShortcutPath" -ForegroundColor Green
Write-Host "Double-click it from your Desktop to launch the JARVIS companion widget silently." -ForegroundColor Green
