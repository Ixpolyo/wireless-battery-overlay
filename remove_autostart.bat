@echo off
rem Retire le demarrage automatique de l'overlay avec Windows.
cd /d "%~dp0"
python "battery_overlay.pyw" --remove-autostart
pause
