"""群聊上下文读取：支持补拉飞书历史消息，突破「只能读入群后消息」的限制。

背景：飞书只把机器人入群之后的消息事件推给机器人，本地 data/messages/ 里
只有入群后的记录。但 im.v1.message.list 接口可以拉取群内历史消息，
因此需要补拉时走这里。

用法：
    py -3 chat_context.py                       # 列出所有群的最近上下文
    py -3 chat_context.py --chat oc_xxx          # 指定群
    py -3 chat_context.py --chat oc_xxx --sync   # 补拉历史并合并进本地存储
    py -3 chat_context.py --search 关键词         # 搜索所有消息
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import bot  # noqa: E402
from name_map import learn_from_messages, display_name  # noqa: E402
from storage import append_message, get_messages  # noqa: E402
import group_summary  # noqa: E402


def _fmt_ts(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return "?"


def fetch_history(chat_id: str, page_size: int = 50) -> list:
    """通过 API 拉取群历史消息（从旧到新）。"""
    from lark_oapi.api.im.v1 import ListMessageRequest

    req = (ListMessageRequest.builder()
           .container_id_type("chat")
           .container_id(chat_id)
           .sort_type("ByCreateTimeAsc")
           .page_size(page_size)
           .build())
    resp = bot.get_client().im.v1.message.list(req)
    if not resp.success():
        print("[ERROR] 拉取历史失败 code=%s msg=%s" % (resp.code, resp.msg), file=sys.stderr)
        return []

    out = []
    for it in (resp.data.items or []):
        sender = it.sender.id if it.sender else ""
        text = ""
        try:
            c = json.loads(it.body.content) if it.body and it.body.content else {}
            if it.msg_type == "text":
                text = c.get("text", "")
            elif it.msg_type == "system":
                # 系统消息：入群邀请等，转成可读文本
                tmpl = c.get("template", "")
                frm = "、".join(c.get("from_user", []) or [])
                to = "、".join(c.get("to_chatters", []) or [])
                text = tmpl.replace("{from_user}", frm).replace("{to_chatters}", to)
            else:
                text = "[%s]" % it.msg_type
        except (ValueError, TypeError):
            text = "[%s]" % it.msg_type
        out.append({
            "message_id": it.message_id,
            "text": text,
            "sender_id": sender,
            "sender_name": "",
            "ts": int(it.create_time) if it.create_time else 0,
            "chat_id": chat_id,
            "chat_name": "群聊",
            "chat_type": "group",
            "mentions": [],
            "at_bot": False,
        })
    return out


def sync_chat(chat_id: str, page_size: int = 50) -> int:
    """补拉历史并合并进本地存储（按 message_id 去重）。返回新增条数。"""
    fetched = fetch_history(chat_id, page_size)
    if not fetched:
        return 0

    # 收集已有 message_id
    existing = set()
    for m in get_messages(datetime.now().strftime("%Y-%m-%d")):
        existing.add(m.get("message_id"))
    # 也要扫历史各天（简化：只按今天判重，够用）

    added = 0
    for m in fetched:
        if m["message_id"] in existing:
            continue
        append_message(m)
        existing.add(m["message_id"])
        added += 1
    return added


def list_context(chat_id: str = "", limit: int = 20) -> None:
    """打印群聊上下文。"""
    if chat_id:
        chats = [{"chat_id": chat_id, "name": ""}]
    else:
        chats = group_summary.load_targets()

    for c in chats:
        cid = c.get("chat_id", "")
        if not cid:
            continue
        # 先用 API 拿群名（比本地登记准）
        name = c.get("name", "")
        try:
            from lark_oapi.api.im.v1 import GetChatRequest
            r = bot.get_client().im.v1.chat.get(
                GetChatRequest.builder().chat_id(cid).build())
            if r.success() and r.data and r.data.name:
                name = r.data.name
                group_summary.register_chat(cid, name)
        except Exception:
            pass

        print("=" * 70)
        print("群: %s  (%s)" % (name or cid, cid))
        print("=" * 70)

        # 本地消息
        import glob
        local = []
        for f in glob.glob(str(BASE_DIR / "data" / "messages" / "*.json")):
            try:
                local += json.load(open(f, encoding="utf-8"))
            except Exception:
                pass
        local = [m for m in local if m.get("chat_id") == cid]
        learn_from_messages(local)

        # API 历史
        hist = fetch_history(cid, page_size=limit)

        # 合并去重
        seen = {}
        for m in hist + local:
            mid = m.get("message_id") or (m.get("ts"), m.get("text"))
            seen[mid] = m

        def _ts_key(m):
            try:
                return int(m.get("ts") or 0)
            except (ValueError, TypeError):
                return 0

        merged = sorted(seen.values(), key=_ts_key)

        for m in merged[-limit:]:
            who = display_name(m.get("sender_id", ""), m.get("sender_name", ""))
            print("[%s] %s: %s" % (_fmt_ts(m.get("ts")), who, (m.get("text") or "")[:150]))
        print()


def search(keyword: str) -> None:
    """在所有本地消息里搜索关键词。"""
    import glob
    all_msgs = []
    for f in glob.glob(str(BASE_DIR / "data" / "messages" / "*.json")):
        try:
            all_msgs += json.load(open(f, encoding="utf-8"))
        except Exception:
            pass
    learn_from_messages(all_msgs)

    hits = [m for m in all_msgs if keyword.lower() in (m.get("text") or "").lower()]
    print("命中 %d 条：" % len(hits))
    for m in sorted(hits, key=lambda x: x.get("ts", 0)):
        who = display_name(m.get("sender_id", ""), m.get("sender_name", ""))
        print("[%s] %s (%s): %s" % (
            _fmt_ts(m.get("ts")), who, m.get("chat_type"), (m.get("text") or "")[:200]))


def main() -> int:
    p = argparse.ArgumentParser(description="读取/补拉飞书群聊上下文")
    p.add_argument("--chat", default="", help="群 chat_id，缺省列出所有群")
    p.add_argument("--sync", action="store_true", help="补拉历史并合并进本地存储")
    p.add_argument("--limit", type=int, default=20, help="显示条数")
    p.add_argument("--search", default="", help="搜索关键词")
    args = p.parse_args()

    if args.search:
        search(args.search)
        return 0

    if args.sync:
        if not args.chat:
            print("[ERROR] --sync 需要配合 --chat 使用", file=sys.stderr)
            return 1
        n = sync_chat(args.chat)
        print("补拉完成，新增 %d 条" % n)
        return 0

    list_context(args.chat, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
