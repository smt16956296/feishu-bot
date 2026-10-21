"""消息流水存储：按天归档到 data/ 目录下的 JSON 文件。

结构：
  data/messages/YYYY-MM-DD.json  -> [ {msg}, {msg}, ... ]
  data/summary/YYYY-MM-DD.json   -> 当天的汇总结果
"""
import json
import os
from datetime import datetime
from config import DATA_DIR

MESSAGES_DIR = os.path.join(DATA_DIR, "messages")
SUMMARY_DIR = os.path.join(DATA_DIR, "summary")


def _ensure_dirs():
    os.makedirs(MESSAGES_DIR, exist_ok=True)
    os.makedirs(SUMMARY_DIR, exist_ok=True)


def _day_file(dirs: str, day: str) -> str:
    _ensure_dirs()
    return os.path.join(dirs, f"{day}.json")


def _load(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save(path: str, data: list):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_message(msg: dict) -> None:
    """追加一条消息到当天流水。"""
    day = datetime.now().strftime("%Y-%m-%d")
    path = _day_file(MESSAGES_DIR, day)
    records = _load(path)
    records.append(msg)
    _save(path, records)


def get_messages(day: str) -> list:
    """读取某天的全部消息。"""
    return _load(_day_file(MESSAGES_DIR, day))


def save_summary(day: str, summary: dict) -> None:
    """保存某天的汇总结果。"""
    path = _day_file(SUMMARY_DIR, day)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def get_summary(day: str) -> dict:
    """读取某天的汇总结果。"""
    path = _day_file(SUMMARY_DIR, day)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
