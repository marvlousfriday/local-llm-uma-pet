@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Qwen3.5-9B 本地部署 (RTX 3060 Ti 8GB)
cd /d "%~dp0"

echo.
echo ==================================================
echo   Qwen3.5-9B 一键部署  ^|  8GB 显存安全配置
echo ==================================================
echo.

set "OLLAMA=ollama"
where ollama >nul 2>nul
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
        set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    ) else (
        set "OLLAMA="
    )
)

echo [1/4] 检查 Ollama 运行环境...
if "%OLLAMA%"=="" (
    echo   未检测到 Ollama，开始安装...
    winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    if errorlevel 1 (
        echo.
        echo   winget 安装失败。请手动下载安装：
        echo   https://ollama.com/download/OllamaSetup.exe
        echo   安装完成后【重新打开】本脚本。
        pause
        exit /b 1
    )
    if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
)
echo   已就绪。

echo.
echo [2/4] 写入 8GB 显存优化开关...
setx OLLAMA_FLASH_ATTENTION 1 >nul
setx OLLAMA_KV_CACHE_TYPE q8_0 >nul
setx OLLAMA_NUM_PARALLEL 1 >nul
setx OLLAMA_MAX_LOADED_MODELS 1 >nul
set OLLAMA_FLASH_ATTENTION=1
set OLLAMA_KV_CACHE_TYPE=q8_0
set OLLAMA_NUM_PARALLEL=1
set OLLAMA_MAX_LOADED_MODELS=1
echo   FLASH_ATTENTION=1  KV_CACHE_TYPE=q8_0  NUM_PARALLEL=1

echo.
echo [3/4] 下载模型 qwen3.5:9b（约 6.1GB，视网速 5-30 分钟）...
"%OLLAMA%" pull qwen3.5:9b
if errorlevel 1 (
    echo   下载失败。检查网络后重跑本脚本；已下载的分片会续传。
    pause
    exit /b 1
)

echo.
echo [4/4] 应用配置并生成 qwen9b...
if not exist "Modelfile" (
    echo   当前目录找不到 Modelfile，请把本脚本和 Modelfile 放在同一文件夹。
    pause
    exit /b 1
)
"%OLLAMA%" create qwen9b -f Modelfile
if errorlevel 1 (
    echo   创建失败。
    pause
    exit /b 1
)

echo   生成 32K 长文档变体 qwen9b32k...
powershell -NoProfile -Command "(Get-Content -Raw 'Modelfile') -replace 'num_ctx 16384','num_ctx 32768' | Set-Content -Encoding utf8 \"$env:TEMP\MF32k\""
"%OLLAMA%" create qwen9b32k -f "%TEMP%\MF32k" >nul 2>nul
if errorlevel 1 echo   [跳过] 32K 变体生成失败，不影响主模型。

echo.
echo ==================================================
echo   完成。正在启动对话（输入 /bye 退出）
echo   上下文 8K ^| KV q8_0 ^| 全层 GPU
echo ==================================================
echo.
"%OLLAMA%" run qwen9b

pause
