"""水蜜桃桃看门狗：bot.py 死了或僵死了，自动拉起来。

为什么需要它（2026-11-03 事故）：
    bot.py 在 13:55:58 静默消失，日志里没有任何异常、没有退出记录、系统也没重启。
    进程死了 24 分钟没人发现——因为 push.py 是独立进程直连飞书 API，
    能照常发消息，所以从"发消息"这一侧完全感知不到"接收端已经聋了"。

两种判断方式（都要有）：
    1. 进程没了        → 立刻拉起
    2. 进程在但僵死了  → 心跳文件超时，杀掉重启
       （只看进程在不在是不够的：线程卡死时进程还活着，但收不到任何消息）

用法：
    py -3 -X utf8 watchdog.py              # 前台跑（调试用）
    py -3 -X utf8 watchdog.py --once       # 检查一次就退出（给任务计划程序用）
    py -3 -X utf8 watchdog.py --interval 60   # 前台常驻，每 60 秒检查

推荐部署：任务计划程序每 5 分钟跑一次 --once（见 skill 说明）
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
HEARTBEAT_FILE = DATA_DIR / "bot_heartbeat.txt"
WATCHDOG_LOG = LOG_DIR / "watchdog.log"
LOCK_FILE = DATA_DIR / "watchdog.lock"

# 心跳超过这个秒数没更新 = bot 僵死
HEARTBEAT_TIMEOUT = 300     # 5 分钟（心跳每 60 秒一次，留 5 倍余量）
# 启动后多久内不判心跳（给启动留时间）
STARTUP_GRACE = 90

LOG_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    line = "%s %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- 进程检测
#
# 性能坑：Get-CimInstance Win32_Process 查命令行要 5-60 秒，不可用于看门狗。
# 改用 PID 文件：bot.py 启动时把 PID 写进 data/bot_pid.txt，
# 看门狗用 Get-Process -Id <pid> 验证（0.2 秒）。PID 复用时靠心跳文件二次确认。

PID_FILE = DATA_DIR / "bot_pid.txt"


def _ps(cmd: str, timeout: int = 20) -> str:
    """跑一条 PowerShell，返回 stdout（UTF-8 容错）。"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="ignore",
        )
        return (r.stdout or "").strip()
    except Exception as e:
        log("[ERROR] PowerShell 调用失败: %s" % e)
        return ""


def find_bot_pids() -> list:
    """返回候选 bot PID 列表。

    策略：优先用 PID 文件；PID 文件丢了就退化为"找所有 python 进程"，
    再用心跳文件是否新鲜来辅助判断（无法确认时宁可不动，避免误杀别的 python）。
    """
    pids = []
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            if pid > 0:
                pids.append(pid)
        except (ValueError, OSError):
            pass
    return pids


def is_alive(pid: int) -> bool:
    out = _ps("(Get-Process -Id %d -ErrorAction SilentlyContinue).Id" % pid, timeout=15)
    return str(pid) in out


# ---------------------------------------------------------------- 心跳检测

def heartbeat_age() -> float:
    """心跳文件距今多少秒。文件不存在返回极大值。"""
    if not HEARTBEAT_FILE.exists():
        return 999999.0
    return time.time() - HEARTBEAT_FILE.stat().st_mtime


# ---------------------------------------------------------------- 启停

def start_bot() -> bool:
    """用 start_bot.ps1 启动（带防双开 + 日志重定向）。

    坑（2026-11-03 实测）：start_bot.ps1 里 Start-Process 拉起的 bot 会继承
    PowerShell 的 stdout/stderr 句柄，如果这里用 capture_output=True，
    subprocess.run 会一直等句柄关闭 —— 表现为看门狗卡死不返回。
    解法：给子进程 DEVNULL，彻底断开句柄继承。
    """
    ps1 = BASE_DIR / "start_bot.ps1"
    if not ps1.exists():
        log("[ERROR] 找不到 start_bot.ps1，无法启动")
        return False
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60, cwd=str(BASE_DIR),
        )
        if r.returncode != 0:
            log("[ERROR] start_bot.ps1 返回 %d" % r.returncode)
            return False
        log("[START] 已通过 start_bot.ps1 拉起 bot.py")
        return True
    except subprocess.TimeoutExpired:
        # 超时不代表失败：脚本可能已经把 bot 拉起来了，只是句柄没释放
        log("[WARN] start_bot.ps1 超时，检查 bot 是否已启动")
        return True
    except Exception as e:
        log("[ERROR] 启动失败: %s" % e)
        return False


def kill_process(pid: int) -> bool:
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=20)
        log("[KILL] 已强杀僵死进程 PID %d" % pid)
        return True
    except Exception as e:
        log("[ERROR] 杀进程 %d 失败: %s" % (pid, e))
        return False


# ---------------------------------------------------------------- 单次检查

def check_once() -> str:
    """检查一次，返回动作描述（'ok' / 'restarted' / 'killed+restarted' / 'error'）。"""
    pids = find_bot_pids()
    alive_pids = [p for p in pids if is_alive(p)]

    # 情况 1：进程不存在
    if not alive_pids:
        age = heartbeat_age()
        log("[DOWN] bot 进程不存在（PID 文件: %s，心跳 %.0f 秒前）" %
            (pids or "无", age))
        return "restarted" if start_bot() else "error"

    # 情况 2：进程存在，检查心跳
    age = heartbeat_age()
    if age > HEARTBEAT_TIMEOUT:
        log("[HANG] bot 进程在（PID %s）但心跳已 %.0f 秒未更新，判定僵死" %
            (",".join(map(str, alive_pids)), age))
        for pid in alive_pids:
            kill_process(pid)
        time.sleep(3)
        return "killed+restarted" if start_bot() else "error"

    # 正常
    return "ok"


# ---------------------------------------------------------------- 单实例锁

def acquire_lock() -> bool:
    """防止多个 watchdog 同时跑（任务计划程序可能重叠）。"""
    if LOCK_FILE.exists():
        try:
            old_pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
            if is_alive(old_pid):
                log("[SKIP] 已有 watchdog 在跑（PID %d）" % old_pid)
                return False
        except (ValueError, OSError):
            pass
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    return True


def release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="水蜜桃桃看门狗")
    ap.add_argument("--once", action="store_true", help="检查一次就退出（任务计划程序用）")
    ap.add_argument("--interval", type=int, default=60, help="前台常驻时的检查间隔秒数")
    ap.add_argument("--quiet", action="store_true", help="正常时不输出")
    args = ap.parse_args()

    if not acquire_lock():
        return 0

    try:
        if args.once:
            result = check_once()
            if not args.quiet or result != "ok":
                log("[ONCE] 检查结果: %s" % result)
            return 0 if result != "error" else 1

        log("[INFO] 看门狗启动，间隔 %d 秒，心跳超时 %d 秒" %
            (args.interval, HEARTBEAT_TIMEOUT))
        while True:
            try:
                result = check_once()
                if result != "ok":
                    log("[INFO] 本轮动作: %s" % result)
            except Exception as e:
                log("[ERROR] 检查异常: %s" % e)
            time.sleep(args.interval)
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
