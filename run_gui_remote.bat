@echo off
rem Serve the RC Engine GUI over Tailscale/LAN (no auth of its own —
rem only run this on trusted networks). Local-only launcher: run_gui.bat
cd /d %~dp0
set RC_GUI_HOST=0.0.0.0
python -m gui
