@echo off
echo [Real-time Pipeline] Starting Stream Processor...
cd /d "%~dp0"
venv\Scripts\python.exe -m realtime.processor
pause
