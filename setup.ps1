param(
    [string]$PythonExe,
    [switch]$BuildTools
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    $runtimeArguments = @()
    if ($PythonExe) {
        $runtimePath = $PythonExe
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $runtimePath = (Get-Command py).Source
        $runtimeArguments = @('-3')
    } else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCommand -and $pythonCommand.Source -notmatch 'WindowsApps') {
            $runtimePath = $pythonCommand.Source
        } else {
            $installRoot = Join-Path $env:LOCALAPPDATA 'Programs/Python'
            $installed = Get-ChildItem -LiteralPath $installRoot -Directory -Filter 'Python*' -ErrorAction SilentlyContinue |
                Sort-Object Name -Descending |
                ForEach-Object { Join-Path $_.FullName 'python.exe' } |
                Where-Object { Test-Path -LiteralPath $_ } |
                Select-Object -First 1
            if (-not $installed) {
                throw 'Python not found. Run setup.ps1 -PythonExe C:/path/to/python.exe'
            }
            $runtimePath = $installed
        }
    }
    & $runtimePath @runtimeArguments -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
}

& $venvPython -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"; import tkinter'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ with Tkinter is required.' }

$requirements = if ($BuildTools) { 'requirements-build.txt' } else { 'requirements.txt' }
& $venvPython -m pip install -r (Join-Path $PSScriptRoot $requirements)
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $venvPython -c 'import customtkinter; from garmin_fit_sdk import Encoder, Decoder'
if ($LASTEXITCODE -ne 0) { throw 'FIT SDK encoding support could not be loaded.' }
Write-Host 'Setup complete. Run Start GUI.cmd or .venv/Scripts/python.exe app.py'
