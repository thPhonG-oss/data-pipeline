@echo off
echo [Real-time Pipeline] Starting MQTT Subscriber...
cd /d "%~dp0"
venv\Scripts\python.exe -m realtime.subscriber
pause
