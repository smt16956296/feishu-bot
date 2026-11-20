# -*- coding: utf-8 -*-
"""重启 bot.py：杀掉现有进程，让 watchdog 自动拉起（或直接 start_bot.ps1）。

用法：py -3 -X utf8 restart_bot.py
"""
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(r"E:\feishu-bot")
sys.path.insert(0, str(BASE_DIR))
PID_FILE = BASE_DIR / "data" / "bot_pid.txt"
HEARTBEAT = BASE_DIR / "data" / "bot_heartbeat.txt"


def log(msg):
    print(msg, flush=True)


def read_pids():
    """读 PID 文件；拿不到就靠 wmic 兜底。"""
    pids = []
    if PID_FILE.exists():
        try:
            pids = [int(x) for x in PID_FILE.read_text(encoding="utf-8").split() if x.strip()]
        except Exception:
            pids = []
    return pids


def find_bot_pids():
    """用 wmic 查命令行含 bot.py 的 python 进程。"""
    found = []
    try:
        r = subprocess.run(
            ["wmic", "process", "where", "name like '%python%' or name like 'py%'",
             "get", "ProcessId,CommandLine", "/format:csv"],
            capture_output=True, text=True, timeout=30)
        for line in r.stdout.splitlines():
            if "bot.py" in line and "restart_bot" not in line:
                for tok in line.split(","):
                    tok = tok.strip()
                    if tok.isdigit():
                        found.append(int(tok))
    except Exception as e:
        log("[WARN] wmic 查询失败: %s" % e)
    return found


def kill(pid):
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=20)
        return True
    except Exception:
        return False


def start():
    ps1 = BASE_DIR / "start_bot.ps1"
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=60, cwd=str(BASE_DIR))
    return r.returncode == 0


if __name__ == "__main__":
    pids = set(read_pids()) | set(find_bot_pids())
    log("找到 bot 进程: %s" % (sorted(pids) or "无"))
    for pid in pids:
        if pid == os.getpid():
            continue
        log("  杀 %d -> %s" % (pid, "OK" if kill(pid) else "FAIL"))
    time.sleep(2)
    log("启动: %s" % ("OK" if start() else "FAIL"))
    time.sleep(6)
    new_pids = find_bot_pids()
    log("新进程: %s" % (new_pids or "无"))
    if HEARTBEAT.exists():
        log("心跳文件 %.1f 秒前更新" % (time.time() - HEARTBEAT.stat().st_mtime))
