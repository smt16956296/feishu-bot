"""群成员姓名映射：从群消息的 @提及 中自动积累 open_id -> 姓名。

背景：飞书通讯录 API 需要 contact 读权限（当前应用未开通），
但群消息里的 mentions 字段自带真实姓名，因此可以从历史消息中反推映射表，
逐步补全发送者姓名。

映射持久化到 data/name_map.json，格式：{"ou_xxx": "张三"}
"""
import json
import os
import re

from config import DATA_DIR

NAME_MAP_FILE = os.path.join(DATA_DIR, "name_map.json")

# 匹配文本中的 @姓名（飞书 @ 提及在 text 里保留为 @名字 形式）
_AT_PATTERN = re.compile(r"@([^\s@,，。；;:：!！?？]+)")


def load_map() -> dict:
    if not os.path.exists(NAME_MAP_FILE):
        return {}
    try:
        with open(NAME_MAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_map(mapping: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(NAME_MAP_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2, sort_keys=True)


def learn_from_messages(messages: list) -> dict:
    """从消息列表的 mentions 字段学习 open_id -> 姓名映射。

    返回更新后的映射表。
    """
    mapping = load_map()
    changed = False
    for msg in messages:
        for m in (msg.get("mentions") or []):
            oid = (m.get("open_id") or "").strip()
            name = (m.get("name") or "").strip()
            # 只记录像人名的（排除空、排除 ou_ 开头的 id 形式）
            if oid and name and not name.startswith("ou_") and oid != name:
                if mapping.get(oid) != name:
                    mapping[oid] = name
                    changed = True
    if changed:
        save_map(mapping)
    return mapping


def display_name(open_id: str, fallback: str = "") -> str:
    """把 open_id 转成姓名；查不到时返回短 id 便于辨认。"""
    if not open_id:
        return fallback or "未知"
    mapping = load_map()
    if open_id in mapping:
        return mapping[open_id]
    if fallback and not fallback.startswith("ou_"):
        return fallback
    # 兜底：取 id 后 6 位，至少能区分不同人
    return "成员_%s" % open_id[-6:]


def unresolved_ids(messages: list) -> set:
    """返回消息中出现过、但映射表里查不到的 open_id 集合。

    用于在日报末尾提示"这些人的姓名未解析"，方便用户补充映射。
    """
    mapping = load_map()
    out = set()
    for msg in messages:
        sid = (msg.get("sender_id") or "").strip()
        if sid and sid not in mapping:
            out.add(sid)
    return out
