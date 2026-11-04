@echo off
chcp 65001 >nul
title Ollama 参数自查
echo.
echo ============================================
echo   Ollama 运行参数自查
echo ============================================
echo.
echo [1] 用户环境变量（持久化配置）
powershell -NoProfile -Command "foreach($n in 'OLLAMA_FLASH_ATTENTION','OLLAMA_KV_CACHE_TYPE','OLLAMA_NUM_PARALLEL','OLLAMA_MAX_LOADED_MODELS'){ '{0} = {1}' -f $n, [Environment]::GetEnvironmentVariable($n,'User') }"
echo.
echo [2] 服务状态
curl -s -m 4 http://127.0.0.1:11434/api/version
if errorlevel 1 echo    服务未响应（没启动，或被别的进程占了端口）
echo.
echo [3] 已加载模型
curl -s -m 4 http://127.0.0.1:11434/api/ps
echo.
echo [4] 模型进程实际参数
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'llama-server.exe' }; if($p){ if($p.CommandLine -match '--cache-type-k q8_0'){ '  KV cache      : q8_0 已生效' } else { '  KV cache      : 未量化（f16，比 q8_0 多占约一倍 KV 显存）' }; if($p.CommandLine -match '--flash-attn on'){ '  FlashAttention: 开启' } else { '  FlashAttention: 关闭' }; if($p.CommandLine -match ' -c (\d+)'){ '  上下文长度    : ' + $Matches[1] }; if($p.CommandLine -match '-ngl (\d+)'){ '  GPU 层数      : ' + $Matches[1] } } else { '  模型未加载，先执行 ollama run qwen9b' }"
echo.
echo ============================================
pause
