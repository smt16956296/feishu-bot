' Feishu bot background launcher (hidden window, via start_bot.ps1 with guard+log)
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File E:\feishu-bot\start_bot.ps1", 0, False
Set WshShell = Nothing
