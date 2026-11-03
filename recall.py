"""撤回飞书消息：列出最近消息、按 id 撤回、撤错补发。

用法（Windows 终端中文要加 -X utf8，否则输出乱码）：
    py -3 -X utf8 recall.py --chat oc_xxx --list      # 列出最近 10 条（序号/时间/发送者/正文）
    py -3 -X utf8 recall.py --id om_xxx --dry-run     # 只看要撤哪条，不真撤
    py -3 -X utf8 recall.py --id om_xxx               # 按 message_id 撤回
    py -3 -X utf8 recall.py --chat oc_xxx --last      # 撤最近一条（会先打印正文供核对）
    py -3 -X utf8 recall.py --chat oc_xxx --last --yes    # 跳过核对提示（脚本用）
    py -3 -X utf8 recall.py --id om_xxx --restore     # 撤回并把原文重新发一遍（撤错补救）

设计原则（2026-11-03 撤错过一次后加）：
    **不核对就撤的入口不存在**。--last 也会先打印要撤那条的正文，
    因为机器人连续推送多条时，只看时间戳容易撤错对象。
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from config import APP_ID, APP_SECRET  # noqa: E402

PUSH_LOG = BASE_DIR / "logs" / "push.log"
PUSH_LOG.parent.mkdir(parents=True, exist_ok=True)

API = "https://open.feishu.cn/open-apis"


# ---------------------------------------------------------------- 基础调用

def _token() -> str:
    """取 tenant_access_token。"""
    import urllib.request

    if not APP_ID or not APP_SECRET:
        raise RuntimeError("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET，请检查 .env")
    req = urllib.request.Request(
        API + "/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    tok = d.get("tenant_access_token", "")
    if not tok:
        raise RuntimeError("取 tenant_access_token 失败: %s" % d)
    return tok


def _request(method: str, path: str, token: str):
    """发请求，返回 (ok, data_or_errmsg)。"""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        API + path, method=method, headers={"Authorization": "Bearer " + token}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            d = json.loads(e.read())
        except Exception:
            return False, "HTTP %s" % e.code
        return False, "code=%s msg=%s" % (d.get("code"), d.get("msg"))
    except Exception as e:
        return False, str(e)
    if d.get("code") != 0:
        return False, "code=%s msg=%s" % (d.get("code"), d.get("msg"))
    return True, d.get("data") or {}


# ---------------------------------------------------------------- 消息读取

def _plain_text(msg: dict) -> str:
    """从消息 body 里提取可读正文。"""
    raw = (msg.get("body") or {}).get("content") or ""
    try:
        d = json.loads(raw)
    except Exception:
        return raw[:120]
    if "text" in d:
        return str(d["text"])
    # post 富文本：拼所有 text 节点
    if "content" in d and isinstance(d["content"], list):
        parts = []
        for line in d["content"]:
            for node in line if isinstance(line, list) else [line]:
                if isinstance(node, dict):
                    if node.get("tag") == "text":
                        parts.append(node.get("text", ""))
                    elif node.get("tag") == "at":
                        parts.append("@" + node.get("user_name", ""))
        return "".join(parts) or raw[:120]
    return raw[:120]


def list_messages(chat_id: str, limit: int = 10) -> list:
    """拉最近 limit 条消息（倒序）。"""
    token = _token()
    ok, data = _request(
        "GET",
        "/im/v1/messages?container_id_type=chat&container_id=%s"
        "&sort_type=ByCreateTimeDesc&page_size=%d" % (chat_id, limit),
        token,
    )
    if not ok:
        raise RuntimeError("拉取消息失败: %s" % data)
    items = data.get("items") or []
    out = []
    for it in items:
        ct = it.get("create_time") or "0"
        try:
            ts = datetime.fromtimestamp(int(ct) / 1000).strftime("%m-%d %H:%M:%S")
        except Exception:
            ts = ct
        out.append({
            "message_id": it.get("message_id", ""),
            "sender_id": (it.get("sender") or {}).get("id", ""),
            "sender_type": (it.get("sender") or {}).get("sender_type", ""),
            "msg_type": it.get("msg_type", ""),
            "create_time": ts,
            "text": _plain_text(it),
        })
    return out


# ---------------------------------------------------------------- 撤回

def recall(message_id: str, dry_run: bool = False) -> bool:
    """撤回指定消息。dry_run 只打印不撤。"""
    if dry_run:
        print("[DRY-RUN] 将撤回 %s" % message_id)
        return True
    token = _token()
    ok, data = _request("DELETE", "/im/v1/messages/%s" % message_id, token)
    _audit("recall", message_id, ok, "" if ok else str(data))
    if ok:
        print("OK 已撤回 %s" % message_id)
    else:
        print("FAILED 撤回失败: %s" % data, file=sys.stderr)
    return ok


def _audit(kind: str, target: str, ok: bool, preview: str) -> None:
    line = "%s | %s | target=%s | ok=%s | %s\n" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), kind, target, ok, preview[:100]
    )
    try:
        with open(PUSH_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="撤回飞书消息")
    ap.add_argument("--chat", help="群 chat_id（oc_ 开头），用于 --list / --last")
    ap.add_argument("--id", help="要撤回的 message_id（om_ 开头）")
    ap.add_argument("--list", action="store_true", help="列出最近消息")
    ap.add_argument("--last", action="store_true", help="撤回最近一条")
    ap.add_argument("--limit", type=int, default=10, help="--list 显示条数，默认 10")
    ap.add_argument("--dry-run", action="store_true", help="只显示不撤回")
    ap.add_argument("--yes", action="store_true", help="跳过 --last 的正文核对提示")
    ap.add_argument("--restore", action="store_true", help="撤回后把原文重新发一遍")
    args = ap.parse_args()

    # --list：列出最近消息
    if args.list:
        if not args.chat:
            print("[ERROR] --list 需要 --chat", file=sys.stderr)
            return 1
        msgs = list_messages(args.chat, args.limit)
        if not msgs:
            print("（没有消息）")
            return 0
        for i, m in enumerate(msgs, 1):
            who = "BOT" if m["sender_type"] == "app" else m["sender_id"][:12]
            print("%2d. %s | %-14s | %s | %s" % (
                i, m["create_time"], who, m["message_id"], m["text"][:50].replace("\n", " ")
            ))
        return 0

    # --last：撤最近一条（必须先打印正文核对）
    if args.last:
        if not args.chat:
            print("[ERROR] --last 需要 --chat", file=sys.stderr)
            return 1
        msgs = list_messages(args.chat, 1)
        if not msgs:
            print("[ERROR] 没有消息", file=sys.stderr)
            return 1
        m = msgs[0]
        print("将撤回：")
        print("  时间: %s" % m["create_time"])
        print("  发送: %s" % ("机器人" if m["sender_type"] == "app" else m["sender_id"]))
        print("  ID  : %s" % m["message_id"])
        print("  正文: %s" % m["text"][:200].replace("\n", " "))
        if not args.yes and not args.dry_run:
            print("\n[提示] 确认是这一条再撤。要跳过此提示加 --yes", file=sys.stderr)
            return 0
        ok = recall(m["message_id"], args.dry_run)
        if ok and args.restore and not args.dry_run:
            _restore(m)
        return 0 if ok else 1

    # --id：按 id 撤回
    if args.id:
        if not args.id.startswith("om_"):
            print("[WARN] message_id 一般以 om_ 开头，确认一下: %s" % args.id, file=sys.stderr)
        if args.dry_run:
            print("[DRY-RUN] 将撤回 %s" % args.id)
            return 0
        ok = recall(args.id, dry_run=False)
        return 0 if ok else 1

    ap.print_help()
    return 1


def _restore(msg: dict) -> None:
    """撤错补救：把原文重新发一遍。"""
    print("[RESTORE] 重新发送原文...")
    text = msg.get("text") or ""
    if not text:
        print("[WARN] 原文为空，跳过重发", file=sys.stderr)
        return
    tmp = BASE_DIR / "data" / "_restore.txt"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(text, encoding="utf-8")
    chat = os.environ.get("RECALL_RESTORE_CHAT", "")
    if not chat:
        print("[WARN] 未设置 RECALL_RESTORE_CHAT 环境变量，无法重发。"
              "手动执行: py -3 push.py --file data/_restore.txt --chat oc_xxx", file=sys.stderr)
        return
    import subprocess
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(BASE_DIR / "push.py"),
         "--file", str(tmp), "--chat", chat],
        cwd=str(BASE_DIR),
    )
    print("[RESTORE] %s" % ("成功" if r.returncode == 0 else "失败"))


if __name__ == "__main__":
    sys.exit(main())
