@echo off
rem Enregistre le demarrage automatique de l'overlay avec Windows
rem (compte utilisateur courant, aucun droit administrateur requis).
cd /d "%~dp0"
python "battery_overlay.pyw" --install-autostart
pause
