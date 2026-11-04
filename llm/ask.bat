@echo off
chcp 65001 >nul
title 本地提问 - qwen9b
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ask.ps1" %*
echo.
pause
