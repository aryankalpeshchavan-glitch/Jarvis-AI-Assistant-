# Creates a Desktop shortcut for J.A.R.V.I.S that launches it reliably.
#
# Why this exists: if your system's .bat file association has ever been
# changed (e.g. accidentally set to "always open with VS Code"), double-
# clicking startup.bat directly will open it as a text file instead of
# running it — which can look like nothing happened, or like some other
# app/project grabbed focus instead.
#
# This shortcut sidesteps that entirely: its target is cmd.exe itself
# (never ambiguous, always executes), with startup.bat passed as an
# argument — so it works regardless of what .bat is currently associated
# with on your system.
#
# Usage: right-click this file -> Run with PowerShell (once).
# Creates: a "Jarvis" shortcut on your Desktop, using the Jarvis icon.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartupBat = Join-Path $ScriptDir "startup.bat"
$IconPath = Join-Path $ScriptDir "assets\jarvis_icon.ico"
$ShortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Jarvis.lnk"

if (-not (Test-Path $StartupBat)) {
    Write-Host "ERROR: startup.bat not found next to this script. Run this from inside the JarvisP1 folder." -ForegroundColor Red
    exit 1
}

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "$env:SystemRoot\System32\cmd.exe"
$Shortcut.Arguments = "/c `"$StartupBat`""
$Shortcut.WorkingDirectory = $ScriptDir
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = $IconPath
}
$Shortcut.Description = "Launch J.A.R.V.I.S"
$Shortcut.Save()

Write-Host "Desktop shortcut created: $ShortcutPath" -ForegroundColor Green
Write-Host "Double-click it from your Desktop to launch Jarvis reliably." -ForegroundColor Green
