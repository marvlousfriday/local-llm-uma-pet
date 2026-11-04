@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\pythonw.exe" (
    echo [x] 找不到 venv，先按 README 建环境
    pause
    exit /b 1
)

if not exist "models\MeishoDoto\G_latest.pth" (
    echo [x] 找不到模型 models\MeishoDoto\G_latest.pth
    pause
    exit /b 1
)

echo 启动 TTS 服务（后台，无窗口）...
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0tts_server.py" --port 9880 --idle 600
timeout /t 3 >nul
curl -s --noproxy "*" http://127.0.0.1:9880/health
echo.
echo 若上面显示 ok:true 就是启动成功了。关掉服务请用任务管理器结束 pythonw.exe
pause
