"""群聊日报定时任务：汇总软算群当天聊天记录，私聊推送给管理员。

用法：
    py -3 daily_summary.py                # 总结今天并推送
    py -3 daily_summary.py --day 2026-10-19   # 指定日期
    py -3 daily_summary.py --dry-run      # 只打印不推送
    py -3 daily_summary.py --no-llm       # 用本地规则摘要（不调 LLM）
    py -3 daily_summary.py --force        # 忽略去重，强制推送
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from config import DATA_DIR, REPORT_TARGET_OPEN_ID  # noqa: E402
import group_summary  # noqa: E402
import push  # noqa: E402

# 已推送记录：{"2026-10-19": "2026-10-20 15:40:00"}，防止同一天重复推送
SENT_FILE = os.path.join(DATA_DIR, "summary_sent.json")


def _load_sent() -> dict:
    if not os.path.exists(SENT_FILE):
        return {}
    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _mark_sent(day: str) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    sent = _load_sent()
    sent[day] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(sent, f, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成并推送群聊日报")
    parser.add_argument("--day", default="", help="日期 YYYY-MM-DD，缺省今天")
    parser.add_argument("--dry-run", action="store_true", help="只打印不推送")
    parser.add_argument("--no-llm", action="store_true", help="用本地规则摘要")
    parser.add_argument("--force", action="store_true", help="忽略去重强制推送")
    args = parser.parse_args()

    day = args.day or datetime.now().strftime("%Y-%m-%d")

    # 去重：同一天已推送过则跳过（--force 可强制）
    if not args.dry_run and not args.force:
        sent = _load_sent()
        if day in sent:
            print("[SKIP] %s 的日报已于 %s 推送过，跳过。如需重推请加 --force"
                  % (day, sent[day]), file=sys.stderr)
            return 0

    targets = group_summary.load_targets()
    if not targets:
        print("[ERROR] 未发现任何群（机器人尚未被拉入群或群内无消息）", file=sys.stderr)
        return 1

    print("[INFO] 待总结群数: %d" % len(targets), file=sys.stderr)
    for t in targets:
        print("[INFO]   - %s (%s)" % (t.get("name", ""), t.get("chat_id", "")), file=sys.stderr)

    body = group_summary.build_all_summaries(day, use_llm=not args.no_llm)

    if not body:
        print("[INFO] 今日所有群均无消息，无需推送", file=sys.stderr)
        return 0

    if args.dry_run:
        print(body)
        return 0

    ok = push.send_rich("群聊日报 · %s" % day, body, REPORT_TARGET_OPEN_ID)
    if ok:
        _mark_sent(day)
        print("OK")
        return 0
    print("FAILED", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
