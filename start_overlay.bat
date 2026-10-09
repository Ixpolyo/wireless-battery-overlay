@echo off
rem Starts the battery overlay without a console window.
cd /d "%~dp0"
start "" pythonw "battery_overlay.pyw"
