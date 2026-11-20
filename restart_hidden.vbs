' 重启飞书机器人：先杀旧进程，再隐藏拉起
' 用法：双击运行
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' 1. 读 PID 文件，杀掉旧 bot
pidFile = "E:\feishu-bot\data\bot_pid.txt"
If fso.FileExists(pidFile) Then
    Set f = fso.OpenTextFile(pidFile, 1)
    pid = Trim(f.ReadAll)
    f.Close
    If pid <> "" Then
        WshShell.Run "taskkill /F /PID " & pid, 0, True
    End If
End If

' 2. 等 3 秒让端口/连接释放
WScript.Sleep 3000

' 3. 用原来的隐藏启动器拉起
WshShell.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File E:\feishu-bot\start_bot.ps1", 0, False

Set WshShell = Nothing
Set fso = Nothing
