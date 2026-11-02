$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Run setup.ps1 -BuildTools first.'
}
& $taskPython -m PyInstaller --noconfirm --clean --onefile --windowed --name HuaweiHealthToFIT --collect-all garmin_fit_sdk --collect-all customtkinter app.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed. Install requirements-build.txt and retry.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'dist/HuaweiHealthToFIT.exe') -Destination (Join-Path $PSScriptRoot 'HuaweiHealthToFIT.exe') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'GARMIN_FIT_SDK_LICENSE.txt') -Destination (Join-Path $PSScriptRoot 'dist/GARMIN_FIT_SDK_LICENSE.txt') -Force
Write-Host 'Ready: HuaweiHealthToFIT.exe (also available in dist/).'
