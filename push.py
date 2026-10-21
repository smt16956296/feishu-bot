"""主动推送入口：让外部（DSH agent / 计划任务 / 脚本）主动发飞书消息。

用法：
    py -3 push.py "消息内容"
    py -3 push.py "消息内容" --to ou_xxxx          # 指定接收人
    echo "多行内容" | py -3 push.py -              # 从 stdin 读
    py -3 push.py --title "标题" "正文"             # 带标题的富文本
    py -3 push.py --chat oc_xxx --file 内容.txt     # 发到群
    py -3 push.py --chat oc_xxx --at 王立 --file 内容.txt   # 发到群并真正 @ 王立

@ 说明：纯文本里写 @张三 飞书不会识别成真 @，对方收不到提醒。
必须用富文本(post)消息 + at 标签。本脚本的 --at 参数自动处理：
    --at 王立            # 按姓名查 open_id（从 name_map + 历史消息学习）
    --at ou_xxxx         # 直接给 open_id
    --at 王立,刘星君      # 多个，逗号分隔
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# 允许从任意工作目录调用
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from config import DATA_DIR, REPORT_TARGET_OPEN_ID  # noqa: E402
import bot  # noqa: E402

# 推送审计日志：记录每一次主动推送，便于排查重复发送
PUSH_LOG = BASE_DIR / "logs" / "push.log"
PUSH_LOG.parent.mkdir(parents=True, exist_ok=True)


def resolve_open_id(name_or_id: str) -> str:
    """把姓名或 open_id 解析成 open_id。解析不到返回空串。

    数据来源（优先级从高到低）：
      1. 直接传的就是 open_id（ou_ 开头）
      2. data/name_map.json（从 @ 消息自动学习）
      3. data/messages/*.json 历史消息里的 mentions 和 sender
    """
    s = (name_or_id or "").strip()
    if not s:
        return ""
    if s.startswith("ou_"):
        return s

    # name_map.json
    nm_path = os.path.join(DATA_DIR, "name_map.json")
    if os.path.exists(nm_path):
        try:
            with open(nm_path, "r", encoding="utf-8") as f:
                nm = json.load(f)
            for oid, n in nm.items():
                if n == s:
                    return oid
        except (ValueError, OSError):
            pass

    # 历史消息兜底
    try:
        import glob
        for fp in glob.glob(os.path.join(DATA_DIR, "messages", "*.json")):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    msgs = json.load(f)
            except (ValueError, OSError):
                continue
            for m in msgs:
                for mt in (m.get("mentions") or []):
                    if mt.get("name") == s and mt.get("open_id"):
                        return mt["open_id"]
                if m.get("sender_name") == s and (m.get("sender_id") or "").startswith("ou_"):
                    return m["sender_id"]
    except Exception:
        pass
    return ""


def build_post_with_mentions(text: str, at_list: list, title: str = "") -> dict:
    """构造带真实 @ 的富文本(post)消息体。

    飞书 post 的 at 节点格式：{"tag": "at", "user_id": "ou_xxx", "user_name": "张三"}
    其中 user_id 必须是 open_id（receive_id_type=open_id 场景下）。
    """
    nodes = []
    for item in at_list:
        name = item.get("name", "")
        oid = item.get("open_id", "")
        if oid:
            nodes.append({"tag": "at", "user_id": oid, "user_name": name})
            nodes.append({"tag": "text", "text": " "})
    nodes.append({"tag": "text", "text": text})
    return {
        "zh_cn": {
            "title": title or "",
            "content": [nodes],
        }
    }


def _audit(kind: str, target: str, ok: bool, preview: str) -> None:
    """写审计日志：谁在什么时候推了什么。"""
    line = "%s | %s | to=%s | ok=%s | %s\n" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        kind,
        target,
        ok,
        preview.replace("\n", " ")[:120],
    )
    try:
        with open(PUSH_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def send(text: str, target: str = "") -> bool:
    """发送文本消息。target 为空时用 .env 里的默认目标。"""
    to = target or REPORT_TARGET_OPEN_ID
    if not to:
        print("[ERROR] 未指定接收人，且 .env 未配置 FEISHU_REPORT_TARGET", file=sys.stderr)
        return False
    if not text or not text.strip():
        print("[ERROR] 消息内容为空", file=sys.stderr)
        return False
    ok = bot.send_text_to_user(to, text)
    _audit("text", to, ok, text)
    return ok


def send_rich(title: str, text: str, target: str = "") -> bool:
    """发送带标题的富文本（post）消息；失败则回退为纯文本。"""
    to = target or REPORT_TARGET_OPEN_ID
    if not to:
        print("[ERROR] 未指定接收人，且 .env 未配置 FEISHU_REPORT_TARGET", file=sys.stderr)
        return False
    content = {
        "zh_cn": {
            "title": title,
            "content": [[{"tag": "text", "text": text}]],
        }
    }
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        body = (
            CreateMessageRequestBody.builder()
            .receive_id(to)
            .msg_type("post")
            .content(json.dumps(content, ensure_ascii=False))
            .build()
        )
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(body)
            .build()
        )
        resp = bot.get_client().im.v1.message.create(req)
        if resp.success():
            _audit("post", to, True, "%s | %s" % (title, text))
            return True
        print("[WARN] 富文本发送失败 code=%s msg=%s，回退纯文本" % (resp.code, resp.msg), file=sys.stderr)
    except Exception as e:
        print("[WARN] 富文本发送异常 %s，回退纯文本" % e, file=sys.stderr)
    # 回退：纯文本
    ok = bot.send_text_to_user(to, "%s\n%s" % (title, text) if title else text)
    _audit("post-fallback-text", to, ok, "%s | %s" % (title, text))
    return ok


def send_to_chat(chat_id: str, text: str, title: str = "", at_list: list = None) -> bool:
    """发送消息到群（chat_id 以 oc_ 开头）。

    at_list 非空时用富文本(post)发真实 @；否则纯文本。
    """
    if not chat_id or not text.strip():
        print("[ERROR] chat_id 或内容为空", file=sys.stderr)
        return False

    at_list = at_list or []

    if at_list:
        # 真实 @ 必须用 post 消息
        payload = build_post_with_mentions(text, at_list, title)
        msg_type = "post"
    elif title:
        payload = {
            "zh_cn": {
                "title": title,
                "content": [[{"tag": "text", "text": text}]],
            }
        }
        msg_type = "post"
    else:
        msg_type = "text"
        payload = {"text": text}

    try:
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        body = (CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type(msg_type)
                .content(json.dumps(payload, ensure_ascii=False))
                .build())
        req = (CreateMessageRequest.builder()
               .receive_id_type("chat_id")
               .request_body(body)
               .build())
        resp = bot.get_client().im.v1.message.create(req)
        ok = bool(resp.success())
        if not ok:
            print("[WARN] 群消息发送失败 code=%s msg=%s" % (resp.code, resp.msg), file=sys.stderr)
            # 富文本失败回退纯文本
            if title:
                return send_to_chat(chat_id, "%s\n%s" % (title, text), "")
        _audit("group-" + msg_type, chat_id, ok, "%s | %s" % (title, text))
        return ok
    except Exception as e:
        print("[ERROR] 群消息发送异常: %s" % e, file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="主动推送消息到飞书")
    parser.add_argument("text", nargs="?", default="", help="消息内容；传 - 表示从 stdin 读取")
    parser.add_argument("--to", default="", help="接收人 open_id（缺省用 .env 的 FEISHU_REPORT_TARGET）")
    parser.add_argument("--chat", default="", help="发送到群（chat_id，oc_ 开头）")
    parser.add_argument("--title", default="", help="标题（提供则发富文本）")
    parser.add_argument("--file", default="", help="从 UTF-8 文件读正文（避免中文编码问题）")
    parser.add_argument("--at", default="", help="要 @ 的人，姓名或 open_id，逗号分隔（自动转真实 @）")
    args = parser.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = args.text
        if text == "-" or (not text and not sys.stdin.isatty()):
            text = sys.stdin.read()

    if not text.strip():
        parser.print_help()
        return 1

    # 解析 --at
    at_list = []
    if args.at:
        for raw in args.at.split(","):
            raw = raw.strip()
            if not raw:
                continue
            oid = resolve_open_id(raw)
            if oid:
                at_list.append({"name": raw, "open_id": oid})
                print("[INFO] @ %s -> %s" % (raw, oid), file=sys.stderr)
            else:
                print("[WARN] 无法解析 @%s 的 open_id，将作为纯文本处理" % raw, file=sys.stderr)

    if args.chat:
        ok = send_to_chat(args.chat, text, args.title, at_list)
    elif args.title:
        ok = send_rich(args.title, text, args.to)
    else:
        ok = send(text, args.to)

    if ok:
        print("OK")
        return 0
    print("FAILED", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
