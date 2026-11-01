@echo off
rem Know Signal - out of range, never out of answers. Double-click to start the quiz server and open the host screen.
title Know Signal
cd /d "%~dp0..\src"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.9+ from python.org and tick "Add to PATH".
  pause
  exit /b 1
)
python server.py %*
pause
