Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "py -3 -X utf8 E:\feishu-bot\watchdog.py --once --quiet", 0, False
Set WshShell = Nothing
