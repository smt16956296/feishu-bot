"""飞书卡片消息：发卡片、更新卡片、长任务进度卡片。

为什么单独一个文件（不塞进 push.py）：
    push.py 是「发一条就结束」的无状态命令行工具；
    卡片是「有状态的长事务」——要持有 message_id、跨时间多次更新、跨进程存活。
    职责不同，生命周期也不同，所以分开。

用法（命令行）：
    py -3 -X utf8 card.py --chat oc_xxx --title "任务标题" --text "内容"     # 发一张静态卡片
    py -3 -X utf8 card.py --id om_xxx --text "新内容"                        # 更新已有卡片
    py -3 -X utf8 card.py --id om_xxx --done "结论内容"                      # 标记完成（变绿）

用法（Python 代码，长任务推荐）：
    from card import ProgressCard
    card = ProgressCard("oc_xxx", "现场问题分析")
    card.update("已读取 3 份日志", "正在比对时序")
    card.done("根因：算法库入口段 2.03s")
    # 出错时：
    card.fail("日志文件不存在")

⚠️ 飞书限制：
    · 只有卡片消息（msg_type=interactive）能被 PATCH 编辑，纯文本不行（报 230001 NOT a card）
    · 每次更新都是全量替换，不是增量
    · 更新频率别太高，按里程碑更新（一次长任务 3-5 次足够），狂刷会被限流
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

# 卡片头部配色
BLUE = "blue"      # 进行中
GREEN = "green"    # 成功
RED = "red"        # 失败
ORANGE = "orange"  # 警告


# ---------------------------------------------------------------- 基础调用

def _token() -> str:
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


def _audit(kind: str, target: str, ok: bool, preview: str) -> None:
    line = "%s | %s | target=%s | ok=%s | %s\n" % (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), kind, target, ok, preview[:100]
    )
    try:
        with open(PUSH_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


# ---------------------------------------------------------------- 卡片构造

def build_card(title: str, body: str, color: str = BLUE, footer: str = "",
               emoji: str = "🔄") -> dict:
    """构造一张卡片。

    title  : 卡片标题
    body   : 正文，支持 lark_md 语法（**加粗**、\n 换行、列表等）
    color  : 头部配色 blue/green/red/orange
    footer : 底部小字（时间戳、状态说明）
    emoji  : 标题前图标
    """
    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": body}},
    ]
    if footer:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": footer}],
        })
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "%s %s" % (emoji, title)},
            "template": color,
        },
        "elements": elements,
    }


def send_card(card: dict, target: str, is_chat: bool = True) -> str:
    """发送卡片，返回 message_id（失败返回空串）。"""
    import urllib.error
    import urllib.request

    tok = _token()
    body = json.dumps({
        "receive_id": target,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }, ensure_ascii=False)
    url = API + "/im/v1/messages?receive_id_type=%s" % ("chat_id" if is_chat else "open_id")
    req = urllib.request.Request(
        url, data=body.encode(),
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        mid = (d.get("data") or {}).get("message_id", "")
        _audit("card", target, bool(mid), mid)
        if not mid:
            print("[ERROR] 卡片发送返回无 message_id: %s" % d, file=sys.stderr)
        return mid
    except urllib.error.HTTPError as e:
        print("[ERROR] 卡片发送失败: %s" % e.read().decode()[:200], file=sys.stderr)
        _audit("card", target, False, "http %s" % e.code)
        return ""
    except Exception as e:
        print("[ERROR] 卡片发送异常: %s" % e, file=sys.stderr)
        return ""


def update_card(message_id: str, card: dict) -> bool:
    """更新（PATCH）已有卡片。只能更新卡片消息，纯文本会报 230001。"""
    import urllib.error
    import urllib.request

    tok = _token()
    body = json.dumps({"content": json.dumps(card, ensure_ascii=False)}, ensure_ascii=False)
    req = urllib.request.Request(
        API + "/im/v1/messages/%s" % message_id,
        data=body.encode(),
        headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        ok = d.get("code") == 0
        _audit("card-edit", message_id, ok, "" if ok else str(d.get("msg")))
        if not ok:
            print("[ERROR] 卡片更新失败: code=%s msg=%s" % (d.get("code"), d.get("msg")),
                  file=sys.stderr)
        return ok
    except urllib.error.HTTPError as e:
        print("[ERROR] 卡片更新失败: %s" % e.read().decode()[:200], file=sys.stderr)
        _audit("card-edit", message_id, False, "http %s" % e.code)
        return False
    except Exception as e:
        print("[ERROR] 卡片更新异常: %s" % e, file=sys.stderr)
        return False


# ---------------------------------------------------------------- 进度卡片（长任务用）

class ProgressCard:
    """长任务进度卡片：一条消息原地刷新，不刷屏。

    用法：
        card = ProgressCard("oc_xxx", "现场问题分析")
        card.update("已读取 3 份日志", "正在比对时序")
        card.done("根因：算法库入口段 2.03s")

    异常安全：
        用 with 语句时，异常退出会自动把卡片标记为失败（变红），
        避免卡片永远停在"进行中"误导人：

        with ProgressCard("oc_xxx", "任务") as card:
            card.update("第一步完成")
            raise RuntimeError("炸了")     # 卡片自动变红
    """

    def __init__(self, target: str, title: str, is_chat: bool = True,
                 initial: str = "任务已开始，正在处理…"):
        self.target = target
        self.title = title
        self.is_chat = is_chat
        self.steps = []          # 已完成步骤
        self.current = initial   # 当前正在做的事
        self.started = datetime.now()
        self.message_id = ""
        self.finished = False

        card = self._render(BLUE, "🔄", initial + "\n\n⏳ 进行中…")
        self.message_id = send_card(card, target, is_chat)

    # ---- 渲染

    def _elapsed(self) -> str:
        sec = int((datetime.now() - self.started).total_seconds())
        if sec < 60:
            return "%d 秒" % sec
        return "%d 分 %d 秒" % (sec // 60, sec % 60)

    def _body(self) -> str:
        lines = []
        for s in self.steps:
            lines.append("✅ " + s)
        if self.current:
            lines.append("⏳ " + self.current)
        return "**%s**\n\n%s" % (self.title, "\n".join(lines)) if lines else "**%s**" % self.title

    def _render(self, color: str, emoji: str, footer: str) -> dict:
        return build_card(self.title, self._body(), color, footer, emoji)

    def _patch(self, card: dict) -> bool:
        if not self.message_id:
            return False
        return update_card(self.message_id, card)

    # ---- 对外方法

    def update(self, done_step: str = "", current: str = "") -> bool:
        """追加一个已完成步骤 / 更新当前进度。"""
        if self.finished:
            print("[WARN] 卡片已结束，忽略更新", file=sys.stderr)
            return False
        if done_step:
            self.steps.append(done_step)
        if current is not None:
            self.current = current
        footer = "⏳ 进行中 · 已用 %s" % self._elapsed()
        return self._patch(self._render(BLUE, "🔄", footer))

    def done(self, result: str = "") -> bool:
        """标记完成：变绿，展示结论。"""
        if self.finished:
            return False
        self.finished = True
        self.current = ""
        body = self._body()
        if result:
            body += "\n\n---\n\n**结果**\n" + result
        card = build_card(self.title, body, GREEN, "✅ 已完成 · 总耗时 %s" % self._elapsed(), "✅")
        return self._patch(card)

    def fail(self, reason: str = "") -> bool:
        """标记失败：变红，展示原因。"""
        if self.finished:
            return False
        self.finished = True
        self.current = ""
        body = self._body()
        body += "\n\n---\n\n**失败原因**\n" + (reason or "未知错误")
        card = build_card(self.title, body, RED, "❌ 失败 · 耗时 %s" % self._elapsed(), "❌")
        return self._patch(card)

    def warn(self, message: str = "") -> bool:
        """标记为警告态（变橙），但不算结束。"""
        if self.finished:
            return False
        body = self._body()
        if message:
            body += "\n\n⚠️ " + message
        card = build_card(self.title, body, ORANGE, "⚠️ 需要关注 · 已用 %s" % self._elapsed(), "⚠️")
        return self._patch(card)

    # ---- with 语句支持（异常自动标红）

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None and not self.finished:
            self.fail("%s: %s" % (exc_type.__name__, exc))
        elif not self.finished:
            # 正常退出但没显式 done/fail —— 自动标完成，避免停在"进行中"
            self.done()
        return False   # 不吞异常


# ---------------------------------------------------------------- 命令行

def main() -> int:
    ap = argparse.ArgumentParser(description="飞书卡片消息（发送/更新/进度卡片）")
    ap.add_argument("--chat", help="群 chat_id（oc_ 开头）")
    ap.add_argument("--to", help="私聊 open_id（ou_ 开头）")
    ap.add_argument("--id", help="要更新的卡片 message_id（om_ 开头）")
    ap.add_argument("--title", default="消息", help="卡片标题")
    ap.add_argument("--text", help="正文内容（支持 **加粗** 等 lark_md 语法）")
    ap.add_argument("--file", help="从 UTF-8 文件读正文（中文长文本推荐）")
    ap.add_argument("--done", help="更新已有卡片为完成态，值为结果内容")
    ap.add_argument("--fail", help="更新已有卡片为失败态，值为失败原因")
    ap.add_argument("--color", default=BLUE, choices=[BLUE, GREEN, RED, ORANGE])
    ap.add_argument("--footer", default="", help="底部小字")
    args = ap.parse_args()

    # 正文来源
    body = args.text or ""
    if args.file:
        body = Path(args.file).read_text(encoding="utf-8")

    # 更新已有卡片
    if args.id:
        if args.done is not None:
            card = build_card(args.title, body or args.done, GREEN,
                              "✅ 已完成", "✅")
            if args.done and not body:
                card["elements"][0]["text"]["content"] = "**%s**\n\n%s" % (args.title, args.done)
        elif args.fail is not None:
            card = build_card(args.title, body or args.fail, RED, "❌ 失败", "❌")
        else:
            card = build_card(args.title, body, args.color, args.footer)
        return 0 if update_card(args.id, card) else 1

    # 新发卡片
    target = args.chat or args.to
    if not target:
        print("[ERROR] 需要 --chat 或 --to", file=sys.stderr)
        return 1
    if not body:
        print("[ERROR] 需要 --text 或 --file", file=sys.stderr)
        return 1
    card = build_card(args.title, body, args.color, args.footer)
    mid = send_card(card, target, is_chat=bool(args.chat))
    if mid:
        print("OK %s" % mid)
        return 0
    print("FAILED", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
