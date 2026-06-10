@echo off
chcp 65001 >nul
echo Starting Claude Buddy Web Mode...
echo.
echo HTTP:  http://0.0.0.0:9876
echo WS:    ws://0.0.0.0:9877
echo.
cd /d "C:\Users\HONOR\m5-paper-buddy"
python tools\claude_code_bridge.py --web --budget 200000 --host 0.0.0.0
