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


def split_bubbles(text: str) -> list:
    """把一段长回复拆成多个气泡（模拟真人分条发消息）。

    拆分规则（2026-11-16 沈梦婷要求"分多个气泡、简明扼要"）：
      1. 优先用显式分隔符 ---气泡--- / ---SPLIT---（整行匹配）
      2. 否则按空行（连续两个换行）切块
      3. 每个气泡超过 MAX_BUBBLE 字时，按句子边界再切，避免单条太长
      4. 最多 MAX_BUBBLES 条，超出的合并到最后一个气泡
    """
    import re as _re

    MAX_BUBBLE = 260
    MAX_BUBBLES = 6

    raw = text.replace("\r\n", "\n")
    # 1) 显式分隔符
    if _re.search(r"^\s*-{2,}\s*(气泡|SPLIT|split)\s*-{2,}\s*$", raw, _re.M):
        parts = _re.split(r"^\s*-{2,}\s*(?:气泡|SPLIT|split)\s*-{2,}\s*$", raw, flags=_re.M)
    else:
        # 2) 空行分块
        parts = _re.split(r"\n\s*\n", raw)

    bubbles = []
    for p in parts:
        p = p.strip("\n").strip()
        if not p:
            continue
        # 3) 过长再按句子切
        if len(p) <= MAX_BUBBLE:
            bubbles.append(p)
            continue
        sents = _re.split(r"(?<=[。！？!?；;\n])", p)
        cur = ""
        for s in sents:
            if not s:
                continue
            if cur and len(cur) + len(s) > MAX_BUBBLE:
                bubbles.append(cur.strip())
                cur = s
            else:
                cur += s
        if cur.strip():
            bubbles.append(cur.strip())

    # 4) 合并超额
    if len(bubbles) > MAX_BUBBLES:
        head = bubbles[:MAX_BUBBLES - 1]
        tail = "\n\n".join(bubbles[MAX_BUBBLES - 1:])
        bubbles = head + [tail]

    return bubbles or [text.strip()]


def _looks_multi(text: str) -> bool:
    """正文是否适合拆成多个气泡：含显式分隔符，或含空行且整体不算太短。"""
    import re as _re

    t = (text or "").replace("\r\n", "\n")
    if _re.search(r"^\s*-{2,}\s*(?:气泡|SPLIT|split)\s*-{2,}\s*$", t, _re.M):
        return True
    # 至少一个空行分块，且正文超过 60 字（太短的问候不拆）
    return bool(_re.search(r"\n\s*\n", t)) and len(t.strip()) > 60


def send(text: str, target: str = "", reply_to: str = "") -> bool:
    """发送文本消息。target 为空时用 .env 里的默认目标。

    reply_to 非空时作为"引用回复"发出去（飞书会显示被引用的原消息）。
    """
    to = target or REPORT_TARGET_OPEN_ID
    if not to:
        print("[ERROR] 未指定接收人，且 .env 未配置 FEISHU_REPORT_TARGET", file=sys.stderr)
        return False
    if not text or not text.strip():
        print("[ERROR] 消息内容为空", file=sys.stderr)
        return False
    if reply_to:
        ok = _send_reply(to, text, reply_to, is_chat=False)
        _audit("text-reply", to, ok, text)
        return ok
    ok = bot.send_text_to_user(to, text)
    _audit("text", to, ok, text)
    return ok


def send_bubbles(parts: list, target: str = "", is_chat: bool = False,
                 reply_to: str = "", delay: float = 0.45) -> bool:
    """把多个气泡依次发出，模拟真人分条发消息。

    第一条带 --reply 引用（群里只引用一次，后续不重复引用）；
    每条之间 delay 秒间隔，避免飞书合并或限流。
    """
    import time

    if not parts:
        return False
    # 修复 2026-11-16：私聊时 send() 的 target 参数此前漏传，导致每条气泡都用
    # .env 的默认目标；默认目标为空时飞书报错、个别情况下会把 open_id 当正文发出。
    to = target or REPORT_TARGET_OPEN_ID
    if not to:
        print("[ERROR] 未指定接收人，且 .env 未配置 FEISHU_REPORT_TARGET", file=sys.stderr)
        return False
    all_ok = True
    for i, p in enumerate(parts):
        if i > 0 and delay:
            time.sleep(delay)
        if is_chat:
            ok = send_to_chat(target, p, "", [], reply_to=reply_to if i == 0 else "")
        else:
            ok = send(p, to, reply_to=reply_to if i == 0 else "")
        if not ok:
            all_ok = False
            print("[WARN] 第 %d/%d 个气泡发送失败" % (i + 1, len(parts)), file=sys.stderr)
    return all_ok



def _send_reply(receive_id: str, text: str, reply_to: str, is_chat: bool) -> bool:
    """发引用回复（私聊/群通用）。

    关键坑（2026-11-03 实测）：
      ❌ POST /im/v1/messages 里带 reply_message_id —— 飞书会静默忽略，
         消息正常发出但 parent_id 为 None，客户端不显示引用效果。
      ✅ 必须用专门的回复接口：POST /im/v1/messages/:message_id/reply
         这个接口不需要 receive_id（目标由被回复消息决定），
         发出的消息 parent_id 会被自动设置，客户端才显示引用。

    另一个坑：lark-oapi 1.7.3 的 CreateMessageRequestBodyBuilder 没有
    reply_message_id 方法，SDK 不支持引用回复，所以这里直接调 HTTP。
    """
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=json.dumps({"app_id": bot.APP_ID, "app_secret": bot.APP_SECRET}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            tok = json.loads(r.read()).get("tenant_access_token", "")
        if not tok:
            print("[WARN] 取 token 失败，回退普通消息", file=sys.stderr)
            return bot.send_text_to_user(receive_id, text)

        # 正确的回复接口：/im/v1/messages/<被回复的 message_id>/reply
        url = "https://open.feishu.cn/open-apis/im/v1/messages/%s/reply" % reply_to
        payload = {
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        req2 = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req2, timeout=20) as r:
            d = json.loads(r.read())
        if d.get("code") != 0:
            print("[WARN] 引用回复失败 code=%s msg=%s，回退普通消息"
                  % (d.get("code"), d.get("msg")), file=sys.stderr)
            return bot.send_text_to_user(receive_id, text)
        return True
    except urllib.error.HTTPError as e:
        print("[WARN] 引用回复 HTTP %s，回退普通消息: %s"
              % (e.code, e.read().decode()[:150]), file=sys.stderr)
        return bot.send_text_to_user(receive_id, text)
    except Exception as e:
        print("[ERROR] 引用回复异常: %s，回退普通消息" % e, file=sys.stderr)
        return bot.send_text_to_user(receive_id, text)


def md_to_post_nodes(md: str) -> list:
    """把 markdown 文本转成飞书 post（富文本）的节点数组。

    飞书 post 支持的节点（官方 im/v1/messages msg_type=post）：
        {"tag":"text","text":"..."}                      纯文本
        {"tag":"a","text":"链接文字","href":"..."}        超链接
        {"tag":"at","user_id":"ou_xxx","user_name":"名字"} @人
        {"tag":"img","image_key":"img_xxx"}              图片
        {"tag":"media","file_key":"..."}                 视频
        {"tag":"emotion","emoji_type":"SMILE"}           表情
        {"tag":"code_block","language":"PYTHON","text":"..."}  代码块
    每个段落是一个节点数组，content = [段落1, 段落2, ...]。
    **注意：post 不支持表格，也不支持 <font> 等 HTML 标签。**

    这里解析的子集（够日常用）：
        **加粗** / __加粗__     -> 用 text 节点原样保留标记会很难看，改为纯文本（见下）
        [文字](url)            -> a 节点
        @姓名                  -> 保持纯文本（真 @ 需要 open_id，见 push.py --at）
        `代码`                 -> 保持纯文本
    段落：按 \n 切分，空行保留为 {"tag":"text","text":""} 以维持间距。
    """
    import re

    def _inline(seg: str) -> list:
        nodes = []
        pos = 0
        # 只识别 [文字](url)；加粗在 post 里没有对应节点，去掉标记直接显示文字
        for m in re.finditer(r"\[([^\]]+)\]\((https?://[^)]+)\)", seg):
            if m.start() > pos:
                nodes.extend(_plain(seg[pos:m.start()]))
            nodes.append({"tag": "a", "text": m.group(1), "href": m.group(2)})
            pos = m.end()
        if pos < len(seg):
            nodes.extend(_plain(seg[pos:]))
        return nodes

    def _plain(s: str) -> list:
        if not s:
            return []
        # 去掉 markdown 加粗标记（post 无加粗节点，留着会显示成星号）
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"__(.+?)__", r"\1", s)
        s = re.sub(r"^#{1,6}\s*", "", s)
        s = re.sub(r"^-\s+", "· ", s)
        return [{"tag": "text", "text": s}]

    paragraphs = []
    for line in md.split("\n"):
        if line.strip() == "":
            paragraphs.append([{"tag": "text", "text": ""}])
        else:
            paragraphs.append(_inline(line) or [{"tag": "text", "text": line}])
    return paragraphs


def send_post(target: str, md: str, title: str = "", is_chat: bool = False) -> bool:
    """发送富文本（post）消息。灰底气泡，和普通消息同一种类型（非卡片）。

    target: chat_id（is_chat=True）或 open_id
    md    : markdown 文本，内部转成 post 节点（**加粗** 会被去掉标记，post 无加粗能力）
    """
    import urllib.error
    import urllib.request

    if not md.strip():
        print("[ERROR] 富文本内容为空", file=sys.stderr)
        return False
    content = {
        "zh_cn": {
            "title": title or "",
            "content": md_to_post_nodes(md),
        }
    }
    try:
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=json.dumps({"app_id": bot.APP_ID, "app_secret": bot.APP_SECRET}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            tok = json.loads(r.read()).get("tenant_access_token", "")
        if not tok:
            print("[ERROR] 取 token 失败", file=sys.stderr)
            return False
        body = json.dumps({
            "receive_id": target,
            "msg_type": "post",
            "content": json.dumps(content, ensure_ascii=False),
        }, ensure_ascii=False)
        url = ("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=%s"
               % ("chat_id" if is_chat else "open_id"))
        req2 = urllib.request.Request(
            url, data=body.encode(),
            headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req2, timeout=20) as r:
            d = json.loads(r.read())
        if d.get("code") != 0:
            print("[WARN] 富文本发送失败 code=%s msg=%s" % (d.get("code"), d.get("msg")),
                  file=sys.stderr)
            return False
        _audit("post", target, True, md)
        return True
    except Exception as e:
        print("[ERROR] 富文本发送异常: %s" % e, file=sys.stderr)
        return False


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


def send_file(receive_id: str, path: str, is_chat: bool = False) -> bool:
    """上传文件到飞书并以文件消息发送。receive_id 为 open_id（私聊）或 chat_id（群）。

    2026-11-20 实现已拆到 file.py（文件消息与文本/卡片差异大，单独成模块，
    与 card.py / recall.py 对称）。这里保留同名包装，旧调用 push.send_file(...) 不断。
    """
    from file import send_file as _send_file
    return _send_file(receive_id, path, is_chat=is_chat)


def send_to_chat(chat_id: str, text: str, title: str = "", at_list: list = None,
                 reply_to: str = "") -> bool:
    """发送消息到群（chat_id 以 oc_ 开头）。

    at_list 非空时用富文本(post)发真实 @；否则纯文本。
    reply_to 非空时作为"引用回复"发出去（飞书会显示被引用的原消息）。
    """
    if not chat_id or not text.strip():
        print("[ERROR] chat_id 或内容为空", file=sys.stderr)
        return False

    at_list = at_list or []

    # 引用回复：走专门的 /reply 接口（见 _send_reply 注释里的坑）
    if reply_to:
        if at_list:
            print("[WARN] 引用回复暂不支持同时 @，已忽略 --at", file=sys.stderr)
        ok = _send_reply(chat_id, text, reply_to, is_chat=True)
        _audit("group-text-reply", chat_id, ok, text)
        return ok

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

        builder = (CreateMessageRequestBody.builder()
                   .receive_id(chat_id)
                   .msg_type(msg_type)
                   .content(json.dumps(payload, ensure_ascii=False)))
        body = builder.build()
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
                return send_to_chat(chat_id, "%s\n%s" % (title, text), "", reply_to=reply_to)
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
    parser.add_argument("--reply", default="", help="引用回复：被回复消息的 message_id（om_ 开头），飞书会显示原消息")
    parser.add_argument("--post", action="store_true",
                        help="以富文本(post)发送：灰底气泡、和普通消息同类，支持链接；不支持表格")
    parser.add_argument("--bubbles", action="store_true",
                        help="强制拆成多个气泡依次发送（按空行/---气泡---切分）")
    parser.add_argument("--no-bubbles", action="store_true",
                        help="强制不拆分，整段发一条")
    parser.add_argument("--delay", type=float, default=0.45,
                        help="气泡之间的间隔秒数（默认 0.45）")
    parser.add_argument("--attach", default="",
                        help="附带发送的文件路径（xlsx/pdf/zip 等）；可配合 --file 正文，先发文本再发文件")
    args = parser.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = args.text
        if text == "-" or (not text and not sys.stdin.isatty()):
            text = sys.stdin.read()

    if not text.strip() and not args.attach:
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

    # 分气泡默认关闭（2026-11-16 沈梦婷反馈：自动拆分不如原来整段发好读）
    #   需要时显式加 --bubbles 才拆
    do_bubbles = args.bubbles and not args.no_bubbles

    if args.attach:
        if not os.path.isfile(args.attach):
            print("[ERROR] --attach 文件不存在: %s" % args.attach, file=sys.stderr)
            return 1
        target = args.chat or args.to or REPORT_TARGET_OPEN_ID
        is_chat = bool(args.chat)
        ok = True
        if text.strip():
            ok = (send_to_chat(args.chat, text, args.title, at_list, reply_to=args.reply) if is_chat
                  else send(text, args.to, reply_to=args.reply))
        ok2 = send_file(target, args.attach, is_chat=is_chat)
        if ok and ok2:
            print("OK")
            return 0
        print("FAILED", file=sys.stderr)
        return 1

    if do_bubbles and not args.post and not args.title:
        target = args.chat or args.to or REPORT_TARGET_OPEN_ID
        if not target:
            print("[ERROR] 分气泡需要 --chat 或 --to", file=sys.stderr)
            return 1
        parts = split_bubbles(text)
        print("[INFO] 拆成 %d 个气泡" % len(parts), file=sys.stderr)
        ok = send_bubbles(parts, target, is_chat=bool(args.chat),
                          reply_to=args.reply, delay=args.delay)
    elif args.post:
        target = args.chat or args.to
        if not target:
            print("[ERROR] --post 需要 --chat 或 --to", file=sys.stderr)
            return 1
        ok = send_post(target, text, args.title, is_chat=bool(args.chat))
    elif args.chat:
        ok = send_to_chat(args.chat, text, args.title, at_list, reply_to=args.reply)
    elif args.title:
        ok = send_rich(args.title, text, args.to)
    else:
        ok = send(text, args.to, reply_to=args.reply)

    if ok:
        print("OK")
        return 0
    print("FAILED", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
