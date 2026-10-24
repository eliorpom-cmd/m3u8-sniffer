@echo off
rem Double-click: runs the PowerShell setup without changing the execution policy
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\install.ps1"
pause
