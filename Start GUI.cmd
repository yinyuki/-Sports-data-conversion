@echo off
setlocal
cd /d "%~dp0"
if exist "HuaweiHealthToFIT.exe" (
  start "" "%~dp0HuaweiHealthToFIT.exe"
  exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
  start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py"
  exit /b
)
where py >nul 2>&1
if not errorlevel 1 (
  py -3 app.py
  if errorlevel 1 pause
  exit /b
)
python app.py
if errorlevel 1 (
  echo Run setup.ps1 first. See README.md for setup instructions.
  pause
)
