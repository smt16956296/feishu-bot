' 飞书机器人后台启动脚本（无窗口）
' 双击即可在后台运行，不显示黑色控制台窗口
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "E:\feishu-bot"
WshShell.Run """C:\Users\shenmengting\AppData\Local\Programs\Python\Python312\pythonw.exe"" bot.py", 0, False
Set WshShell = Nothing
