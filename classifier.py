"""待办识别：根据关键词从消息中提取待办事项。

规则（第一版，后续可优化）：
  1. 命中任一待办关键词 -> 标记为待办
  2. 记录发送人、时间、消息原文
"""
from config import TODO_KEYWORDS


def is_todo(text: str) -> bool:
    """判断文本是否命中待办关键词。"""
    if not text:
        return False
    for kw in TODO_KEYWORDS:
        if kw and kw in text:
            return True
    return False


def extract_todo(msg: dict) -> dict | None:
    """从一条消息中提取待办项；非待办返回 None。

    入参 msg 期望结构：
      {
        "message_id": str,
        "text": str,
        "sender_id": str,
        "sender_name": str,
        "ts": int (毫秒),
        "chat_id": str,
        "chat_name": str,
      }
    """
    text = (msg.get("text") or "").strip()
    if not text:
        return None
    if not is_todo(text):
        return None
    return {
        "message_id": msg.get("message_id", ""),
        "text": text,
        "sender_id": msg.get("sender_id", ""),
        "sender_name": msg.get("sender_name", "未知"),
        "ts": msg.get("ts", 0),
        "chat_id": msg.get("chat_id", ""),
        "chat_name": msg.get("chat_name", ""),
        "keywords": [kw for kw in TODO_KEYWORDS if kw and kw in text],
    }
