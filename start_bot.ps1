# Feishu bot launcher (guard against double-start + logging)
# Called by start_hidden.vbs; can also be run manually.
$log = "E:\feishu-bot\logs\start_bot.log"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$existing = Get-CimInstance Win32_Process -Filter "Name LIKE 'py%' OR Name LIKE 'python%'" |
    Where-Object { $_.CommandLine -match 'bot\.py' }
if ($existing) {
    Add-Content -Path $log -Value "$stamp [SKIP] bot.py already running (PID $($existing.ProcessId -join ','))"
    exit 0
}
Start-Process py -ArgumentList "-3","-X","utf8","bot.py" -WorkingDirectory "E:\feishu-bot" `
    -RedirectStandardOutput "E:\feishu-bot\logs\bot_out.log" `
    -RedirectStandardError "E:\feishu-bot\logs\bot_err.log" -WindowStyle Hidden
Add-Content -Path $log -Value "$stamp [START] bot.py started"
