"""群聊日报：汇总机器人所在的所有飞书群当天聊天记录，生成结构化总结。

群发现机制（三路合并，自动感知被拉入的新群）：
  1. data/known_chats.json —— 机器人被拉进群时由 bot.py 自动记录（最权威）
  2. data/messages/*.json —— 历史消息里出现过的群（兜底）
  3. data/summary_targets.json —— 手工配置（可选，用于排除/改名）

总结策略：
  1. 优先用 DSH 的 LLM 做智能总结（理解语义、提炼待办与结论）
  2. LLM 不可用时降级为本地规则摘要，保证功能不中断
"""
import json
import os
import re
from datetime import datetime

from config import DATA_DIR
from name_map import learn_from_messages, display_name
from storage import get_messages

KNOWN_CHATS_FILE = os.path.join(DATA_DIR, "known_chats.json")
GROUP_CONFIG_FILE = os.path.join(DATA_DIR, "summary_targets.json")

# 软算群（兼容旧配置的默认值）
DEFAULT_GROUP_ID = "oc_90da6b0826ebe9967c62c5a8769e9453"

# 待办/结论类关键词，用于本地降级摘要
_TODO_HINTS = ("需要", "待", "跟进", "确认", "安排", "解决", "修复", "处理",
               "抓紧", "急", "截止", "发布", "提供", "同步", "评审", "复现")
_DONE_HINTS = ("已", "完成", "修复了", "发布了", "搞定", "好了", "没问题")


# ---------------- 群发现 ----------------

def register_chat(chat_id: str, name: str = "") -> None:
    """记录一个群（bot.py 在入群事件/收到群消息时调用）。"""
    if not chat_id:
        return
    chats = _load_known_chats()
    entry = chats.get(chat_id, {})
    entry["chat_id"] = chat_id
    if name:
        entry["name"] = name
    entry.setdefault("name", name or "群聊_%s" % chat_id[-6:])
    entry["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    chats[chat_id] = entry
    _save_known_chats(chats)


def _load_known_chats() -> dict:
    if not os.path.exists(KNOWN_CHATS_FILE):
        return {}
    try:
        with open(KNOWN_CHATS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_known_chats(chats: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(KNOWN_CHATS_FILE, "w", encoding="utf-8") as f:
        json.dump(chats, f, ensure_ascii=False, indent=2, sort_keys=True)


def load_targets() -> list:
    """返回要总结的群列表 [{"chat_id","name"}]。

    优先级：summary_targets.json 手工配置 > known_chats.json 自动发现。
    known_chats 里标记 enabled=false 的群会被排除。
    """
    # 1) 手工配置优先（允许用户精确控制）
    if os.path.exists(GROUP_CONFIG_FILE):
        try:
            with open(GROUP_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return data
        except (json.JSONDecodeError, OSError):
            pass

    # 2) 自动发现：known_chats + 历史消息兜底
    known = _load_known_chats()
    out = []
    seen = set()
    for cid, info in known.items():
        if info.get("enabled", True) is False:
            continue
        out.append({"chat_id": cid, "name": info.get("name") or cid})
        seen.add(cid)

    # 3) 历史消息里出现但 known_chats 没记录的群，补上
    for cid in _discover_from_messages():
        if cid not in seen:
            out.append({"chat_id": cid, "name": "群聊_%s" % cid[-6:]})

    return out


def _discover_from_messages() -> set:
    """从历史消息文件里发现群 chat_id。"""
    out = set()
    msg_dir = os.path.join(DATA_DIR, "messages")
    if not os.path.isdir(msg_dir):
        return out
    for fn in os.listdir(msg_dir):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(msg_dir, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, list):
            continue
        for m in data:
            if m.get("chat_type") == "group" and m.get("chat_id"):
                out.add(m["chat_id"])
    return out


def save_targets(targets: list) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(GROUP_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(targets, f, ensure_ascii=False, indent=2)


# ---------------- 总结生成 ----------------

def collect_group_messages(chat_id: str, day: str) -> list:
    """取某天某群的全部消息，并把发送者转成姓名。"""
    msgs = get_messages(day)
    group_msgs = [m for m in msgs if (m.get("chat_id") or "") == chat_id]
    if not group_msgs:
        return []
    learn_from_messages(group_msgs)
    out = []
    for m in group_msgs:
        ts = m.get("ts")
        try:
            dt = datetime.fromtimestamp(int(ts) / 1000)
            tstr = dt.strftime("%H:%M")
        except (ValueError, TypeError, OSError):
            tstr = ""
        out.append({
            "time": tstr,
            "sender": display_name(m.get("sender_id", ""), m.get("sender_name", "")),
            "text": (m.get("text") or "").strip(),
        })
    out.sort(key=lambda x: x["time"])
    return out


def _rule_based_summary(msgs: list, group_name: str, day: str) -> str:
    """本地规则摘要（LLM 不可用时的降级方案）。"""
    if not msgs:
        return ""

    senders = {}
    for m in msgs:
        senders[m["sender"]] = senders.get(m["sender"], 0) + 1

    todos, dones = [], []
    for m in msgs:
        text = m["text"]
        if any(h in text for h in _TODO_HINTS):
            todos.append(m)
        elif any(h in text for h in _DONE_HINTS):
            dones.append(m)

    lines = []
    lines.append("【%s · 聊天总结】%s" % (group_name, day))
    lines.append("共 %d 条消息，%d 人参与。" % (len(msgs), len(senders)))
    lines.append("")
    lines.append("一、参与人：")
    for name, cnt in sorted(senders.items(), key=lambda x: -x[1]):
        lines.append("  · %s：%d 条" % (name, cnt))

    if todos:
        lines.append("")
        lines.append("二、待办 / 需跟进：")
        for m in todos[:15]:
            t = m["text"]
            if len(t) > 60:
                t = t[:60] + "…"
            lines.append("  · [%s] %s：%s" % (m["time"], m["sender"], t))

    if dones:
        lines.append("")
        lines.append("三、已完成 / 已确认：")
        for m in dones[:10]:
            t = m["text"]
            if len(t) > 60:
                t = t[:60] + "…"
            lines.append("  · [%s] %s：%s" % (m["time"], m["sender"], t))

    return "\n".join(lines)


def _llm_summary(msgs: list, group_name: str, day: str) -> str:
    """调用 DSH LLM 做智能总结。失败返回空串。

    关键：用**独立的总结会话**，不能占用交互会话。
    """
    try:
        convo = "\n".join(
            "[%s] %s: %s" % (m["time"], m["sender"], m["text"]) for m in msgs
        )
        prompt = (
            "你是团队沟通总结助手。下面是飞书群「%s」在 %s 的全部聊天记录，"
            "请总结成一份简洁的日报，供团队成员快速了解当天进展。\n\n"
            "要求：\n"
            "1. 分三段：【今日要点】用 3-6 条概括主要讨论内容和结论；"
            "【待办与跟进】列出需要有人跟进的事项，注明谁提的、涉及谁；"
            "【风险与阻塞】列出提到的问题、崩溃、延期等风险，没有就写“无”。\n"
            "2. 只基于记录内容，不要编造。人名照抄。\n"
            "3. 全文控制在 500 字内，用纯文本，不要 markdown 表格。\n"
            "4. 只输出三段正文本身。禁止输出任何开场白、结尾语、"
            "对任务的说明、对自身行为的解释（例如“以上为”“本轮先”“我会”等一律不要）。\n\n"
            "聊天记录：\n%s" % (group_name, day, convo)
        )
        reply = _call_summary_session(prompt, timeout=240)
        if reply and len(reply.strip()) > 20:
            return reply.strip()
    except Exception:
        pass
    return ""


_SUMMARY_SESSION_FILE = os.path.join(DATA_DIR, "summary_session_id.txt")


def _call_summary_session(prompt: str, timeout: int = 240) -> str:
    """用独立的 DSH 会话做总结，避免占用交互会话。"""
    import time
    import dsh_bridge

    sid = ""
    if os.path.exists(_SUMMARY_SESSION_FILE):
        with open(_SUMMARY_SESSION_FILE, "r", encoding="utf-8") as f:
            sid = f.read().strip()

    if not sid:
        r = dsh_bridge._call("session.create", {
            "cwd": dsh_bridge.DEFAULT_CWD,
            "agentPreset": dsh_bridge.AGENT_PRESET,
        })
        res = r.get("result", {})
        if not res.get("ok"):
            return ""
        sid = res.get("value", {}).get("sessionId", "")
        if not sid:
            return ""
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_SUMMARY_SESSION_FILE, "w", encoding="utf-8") as f:
            f.write(sid)

    before_seq = dsh_bridge.get_latest_seq(sid)

    r = dsh_bridge._call("session.prompt", {
        "sessionId": sid,
        "mode": "queue",
        "content": [{"type": "text", "text": prompt}],
    }, timeout=30)
    if not r.get("result", {}).get("ok"):
        return ""

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        r = dsh_bridge._call("session.history", {"sessionId": sid, "maxMessages": 50})
        events = r.get("result", {}).get("value", {}).get("events", [])
        for item in events:
            ev = item.get("event", {})
            if ev.get("type") == "assistant/message" and ev.get("seq", 0) > before_seq:
                msg = ev.get("data", {}).get("message", {})
                content = msg.get("content", [])
                texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                reply = "".join(texts).strip()
                if reply:
                    return reply
    return ""


def build_group_summary(chat_id: str, group_name: str, day: str = None,
                        use_llm: bool = True) -> str:
    """生成某群某天的聊天总结；当天无消息返回空串（不占篇幅）。"""
    if day is None:
        day = datetime.now().strftime("%Y-%m-%d")
    msgs = collect_group_messages(chat_id, day)
    if not msgs:
        return ""

    if use_llm:
        s = _llm_summary(msgs, group_name, day)
        if s:
            header = "【%s】%d 条消息\n\n" % (group_name, len(msgs))
            return header + s

    return _rule_based_summary(msgs, group_name, day)


def build_all_summaries(day: str = None, use_llm: bool = True) -> str:
    """生成所有群的当日总结，返回可直接推送的完整文本。"""
    if day is None:
        day = datetime.now().strftime("%Y-%m-%d")

    targets = load_targets()
    sections = []
    for t in targets:
        cid = t.get("chat_id", "")
        name = t.get("name") or cid
        if not cid:
            continue
        s = build_group_summary(cid, name, day, use_llm=use_llm)
        if s:
            sections.append(s)

    if not sections:
        return ""

    header = "【群聊日报】%s\n共 %d 个群有讨论\n" % (day, len(sections))
    body = "\n\n" + ("\n\n" + "-" * 30 + "\n\n").join(sections)
    return header + body
