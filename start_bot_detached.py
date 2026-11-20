# -*- coding: utf-8 -*-
"""彻底脱离父进程拉起 bot.py（用 Windows 的 start 语义）。

关键：subprocess.Popen + DETACHED_PROCESS 仍可能随 DSH 会话结束被回收，
这里改用 CreateProcess 走 cmd start /b，或者直接用 wmic/pythonw 常驻。
实测最稳的是 pythonw.exe（无控制台窗口的 python）。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(r"E:\feishu-bot")
PIDF = BASE / "data" / "bot_pid.txt"
HB = BASE / "data" / "bot_heartbeat.txt"


def log(m):
    print(m, flush=True)


# 1. 杀旧
if PIDF.exists():
    try:
        old = int(PIDF.read_text(encoding="utf-8").strip())
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x0001, False, old)
        if h:
            ctypes.windll.kernel32.TerminateProcess(h, 1)
            log("杀掉旧进程 %d" % old)
    except Exception as e:
        log("杀旧进程跳过: %s" % e)
time.sleep(2)

# 2. 找 pythonw.exe（无控制台，最不容易被回收）
py_dir = Path(sys.executable).parent
pythonw = py_dir / "pythonw.exe"
exe = str(pythonw) if pythonw.exists() else sys.executable
log("使用解释器: %s" % exe)

# 3. 用 cmd start 真正脱离（/b 不开新窗口，但进程独立）
cmd = 'start "" /b "%s" -X utf8 "E:\\feishu-bot\\bot.py"' % exe
r = subprocess.run(cmd, shell=True, cwd=str(BASE),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
log("start 返回: %s" % r.returncode)

# 4. 等待并验证
for i in range(15):
    time.sleep(1)
    if HB.exists() and (time.time() - HB.stat().st_mtime) < 10:
        log("心跳已更新（%d 秒内），启动成功" % (i + 1))
        break
else:
    log("[WARN] 心跳未更新，检查 bot_err.log")

if PIDF.exists():
    log("PID 文件: %s" % PIDF.read_text(encoding="utf-8").strip())
