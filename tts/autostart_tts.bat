@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 已经有服务在跑就直接退出，避免端口冲突起第二个实例
curl -s --noproxy "*" -m 2 http://127.0.0.1:9880/health >nul 2>&1
if %errorlevel%==0 (
    echo TTS 服务已在运行，跳过
    exit /b 0
)

start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0tts_server.py" --port 9880 --idle 600
