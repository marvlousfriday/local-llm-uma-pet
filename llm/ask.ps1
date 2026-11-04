param([string]$Question)

$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:11434"

if (-not $Question) {
    $Question = Read-Host "请输入问题"
}
if (-not $Question) { exit }

$today = Get-Date -Format "yyyy-MM-dd dddd"
$sys = "当前日期是 $today（本机系统时间）。涉及日期、时间、星期的问题一律以此为准，不要声称自己无法获取当前日期。"

$body = @{
    model    = "qwen9b"
    stream   = $false
    think    = $false
    messages = @(
        @{ role = "system"; content = $sys },
        @{ role = "user"; content = $Question }
    )
    options  = @{ num_predict = 1024 }
} | ConvertTo-Json -Depth 6

try {
    $wc = New-Object System.Net.WebClient
    $wc.Encoding = [System.Text.Encoding]::UTF8
    $wc.Headers.Add("Content-Type", "application/json")
    $resp = $wc.UploadString("$base/api/chat", "POST", $body)
}
catch {
    Write-Host ""
    Write-Host "调用失败：$($_.Exception.Message)" -ForegroundColor Red
    Write-Host "检查 Ollama 服务：curl http://127.0.0.1:11434/api/version" -ForegroundColor DarkGray
    exit 1
}

$obj = $resp | ConvertFrom-Json
$content = $obj.message.content
if (-not $content) {
    Write-Host ""
    Write-Host "（模型没有给出回答，可能被 token 上限截断）" -ForegroundColor Yellow
    exit 2
}

Write-Host ""
Write-Host $content
Write-Host ""
$speed = if ($obj.eval_duration -gt 0) { [math]::Round($obj.eval_count / $obj.eval_duration * 1e9) } else { 0 }
Write-Host ("[{0} tokens · {1} tok/s]" -f $obj.eval_count, $speed) -ForegroundColor DarkGray
