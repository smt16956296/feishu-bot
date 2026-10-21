"""日报生成：把当天的消息汇总成待办清单与遗漏项。

输出为飞书富文本/文本消息内容。
"""
import re
from datetime import datetime

from classifier import extract_todo
from storage import get_messages, save_summary

# 需要从文本中清洗掉的噪音前缀（@机器人 等）
_NOISE_PATTERNS = [
    re.compile(r"@\S+\s*"),          # @某人 及后续空白
]

# 显示为"我"的发送者 open_id（自己的 open_id）
SELF_OPEN_IDS = {"ou_b52b28fd91c32dba5517ac425a8476fc"}


def clean_text(text: str) -> str:
    """清洗文本：去掉 @机器人 等噪音前缀，压缩空白。"""
    if not text:
        return ""
    result = text
    for pat in _NOISE_PATTERNS:
        result = pat.sub("", result)
    return result.strip()


def display_name(msg: dict) -> str:
    """发送者显示名：查不到姓名且是自己时显示"我"。"""
    name = msg.get("sender_name", "") or ""
    sid = msg.get("sender_id", "") or ""
    # 姓名就是 open_id 形式（ou_ 开头）说明没查到真实姓名
    if name.startswith("ou_") or not name:
        if sid in SELF_OPEN_IDS or name in SELF_OPEN_IDS:
            return "我"
        return name or "未知"
    return name


def build_daily_report(day=None):
    if day is None:
        day = datetime.now().strftime("%Y-%m-%d")

    messages = get_messages(day)
    todos = []
    for msg in messages:
        t = extract_todo(msg)
        if t:
            todos.append(t)

    total = len(messages)
    todo_count = len(todos)
    senders = {}
    for msg in messages:
        name = display_name(msg)
        senders[name] = senders.get(name, 0) + 1

    lines = []
    lines.append("【消息统计日报 · %s】" % day)
    lines.append("共收到消息 %d 条，其中疑似待办 %d 条。" % (total, todo_count))
    lines.append("")
    lines.append("一、疑似待办事项：")
    if todos:
        for i, t in enumerate(todos, 1):
            sender = display_name(t)
            content = clean_text(t.get("text", ""))
            lines.append("%d. [%s] %s" % (i, sender, content))
    else:
        lines.append("（今日未识别到待办）")
    lines.append("")
    lines.append("二、消息来源分布：")
    for name, cnt in sorted(senders.items(), key=lambda x: -x[1]):
        lines.append("- %s: %d 条" % (name, cnt))

    report = "\n".join(lines)
    save_summary(day, {
        "day": day,
        "total": total,
        "todo_count": todo_count,
        "senders": senders,
        "todos": todos,
    })
    return report
