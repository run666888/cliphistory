@echo off
cd /d "%~dp0"
python -c "import tkinter, cliphistory" 1>nul 2>"%TEMP%\cliphistory-check.txt"
if errorlevel 1 (
  echo ClipHistory failed to start.
  type "%TEMP%\cliphistory-check.txt"
  pause
  exit /b 1
)
where pythonw >nul 2>&1
if errorlevel 1 (
  start "ClipHistory" python -m cliphistory
) else (
  start "ClipHistory" pythonw -m cliphistory
)
