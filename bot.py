"""飞书机器人主程序：通过长连接(WebSocket)接收消息。

功能（第一版）：
  1. 接收与机器人的单聊消息（含你转发/粘贴的内容）
  2. 按关键词识别待办事项，存到 data/messages
  3. 每天定时推送消息统计日报到你的个人会话

运行：
  py -3 bot.py
"""
import json
import logging
import os
import threading
import time
from datetime import datetime

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    CreateMessageReactionRequest,
    CreateMessageReactionRequestBody,
    Emoji,
    P2ImMessageReceiveV1,
)

from config import (
    APP_ID,
    APP_SECRET,
    BOT_NAME,
    DAILY_REPORT_TIME,
    DATA_DIR,
    GROUP_SUMMARY_TIME,
    REPORT_TARGET_OPEN_ID,
)
from storage import append_message
from reporter import build_daily_report
import dsh_bridge

# 图片落盘目录（供 agent 分析，也便于事后取证）
IMAGE_DIR = os.path.join(DATA_DIR, "images")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("feishu-bot")

# 记录"等待用户回答"状态：{open_id: True}
# 当 agent 向用户提问（输出【请问】标记）时置 True，用户回复后送回 agent 并清除。
_pending_questions = {}
_pending_lock = threading.Lock()

_client = None


def get_client():
    """构建并复用 API 客户端。"""
    global _client
    if _client is None:
        _client = lark.Client.builder() \
            .app_id(APP_ID) \
            .app_secret(APP_SECRET) \
            .log_level(lark.LogLevel.INFO) \
            .build()
    return _client


def on_bot_added(data) -> None:
    """机器人被拉进群时记录，方便确认已入群。"""
    try:
        chat_id = data.event.chat_id
        logger.info("机器人被添加到群: chat_id=%s", chat_id)
        # 自动登记到 known_chats，供群聊日报自动发现
        import group_summary
        group_summary.register_chat(chat_id)
    except Exception as e:
        logger.exception("处理入群事件出错: %s", e)


def on_reaction_created(data) -> None:
    """消息表情事件（含机器人自己贴的表情）。

    飞书后台订阅了 im.message.reaction.created_v1，若不注册处理器，
    lark-oapi 会为每条表情事件打印 "processor not found" ERROR 刷屏。
    这里静默忽略——表情反馈本身由 add_reaction() 主动发起，无需回调处理。
    """
    return


def parse_message_content(msg_type: str, raw: str) -> tuple:
    """解析各种消息类型，返回 (可读文本, 附件信息列表)。

    支持：
      text    -> 纯文本
      post    -> 富文本（文字+图片混排，飞书里"发图片带文字"就是这种）
      image   -> 图片（下载到本地，文本标记为 [图片]）
      sticker -> 表情包
      file    -> 文件
      audio   -> 语音
      media   -> 视频
    其他类型返回 "[<类型>]" 占位，保证至少能记录"收到过这条消息"。
    """
    attachments = []
    try:
        payload = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        return (raw or "", attachments)

    if msg_type == "text":
        return (payload.get("text", "") or "", attachments)

    if msg_type == "post":
        # 富文本：content = {"title": "...", "content": [[{tag,text/href/image_key},...],...]}
        # 兼容 {"zh_cn": {...}} 包装
        body = payload
        if "content" not in body and "zh_cn" in payload:
            body = payload.get("zh_cn") or {}
        title = body.get("title", "") or ""
        parts = []
        for line in (body.get("content") or []):
            for node in (line or []):
                tag = node.get("tag")
                if tag == "text":
                    parts.append(node.get("text", "") or "")
                elif tag == "a":
                    parts.append(node.get("text", "") or node.get("href", "") or "")
                elif tag == "at":
                    parts.append("@" + (node.get("user_name", "") or node.get("user_id", "")))
                elif tag == "img":
                    key = node.get("image_key", "") or ""
                    parts.append("[图片]")
                    if key:
                        attachments.append({"type": "image", "key": key})
                elif tag == "media":
                    parts.append("[视频]")
                    if node.get("file_key"):
                        attachments.append({"type": "media", "key": node["file_key"]})
                elif tag == "emotion":
                    parts.append("[表情]")
            parts.append("\n")
        text = (title + "\n" if title else "") + "".join(parts).strip()
        return (text, attachments)

    if msg_type == "image":
        key = payload.get("image_key", "") or ""
        if key:
            attachments.append({"type": "image", "key": key})
        return ("[图片]", attachments)

    if msg_type == "sticker":
        # 表情包：飞书返回 {"file_key": "..."} 或 {"image_key": "..."}
        key = payload.get("file_key") or payload.get("image_key") or ""
        if key:
            attachments.append({"type": "sticker", "key": key})
        return ("[表情包]", attachments)

    if msg_type == "file":
        name = payload.get("file_name", "") or ""
        key = payload.get("file_key", "") or ""
        if key:
            attachments.append({"type": "file", "key": key, "name": name})
        return ("[文件] %s" % name, attachments)

    if msg_type == "audio":
        return ("[语音]", attachments)

    if msg_type == "media":
        key = payload.get("file_key", "") or ""
        if key:
            attachments.append({"type": "media", "key": key})
        return ("[视频]", attachments)

    return ("[%s]" % msg_type, attachments)


def download_image(message_id: str, file_key: str, tag: str = "image") -> str:
    """下载消息里的图片到 data/images/，返回本地路径（失败返回空串）。

    飞书图片必须用 message_resource 接口下载，且需要 message_id。
    """
    if not file_key or not message_id:
        return ""
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import GetMessageResourceRequest

        os.makedirs(IMAGE_DIR, exist_ok=True)
        req = (GetMessageResourceRequest.builder()
               .message_id(message_id)
               .file_key(file_key)
               .type("image")
               .build())
        resp = get_client().im.v1.message_resource.get(req)
        if not resp or not resp.file:
            logger.warning("下载图片失败 file_key=%s", file_key)
            return ""
        # 按 file_key 命名，避免重复下载
        safe = "".join(c for c in file_key if c.isalnum() or c in "-_")[:80]
        path = os.path.join(IMAGE_DIR, "%s_%s.img" % (tag, safe))
        with open(path, "wb") as f:
            f.write(resp.file.read())
        logger.info("图片已保存: %s (%d 字节)", path, os.path.getsize(path))
        return path
    except Exception as e:
        logger.warning("下载图片异常 file_key=%s: %s", file_key, e)
        return ""


def build_recent_context(chat_id: str, limit: int = 12, exclude_msg_id: str = "") -> str:
    """取该会话最近若干条消息，拼成给 agent 的上下文块。

    目的：用户只说「@水蜜桃桃」「看一下」这种短消息时，agent 必须能看到
    前文才知道要干什么。之前靠 agent 自己主动去读，容易忘；这里强制附带。
    """
    try:
        from storage import get_messages
        import group_summary

        # 取最近两天的消息（跨天对话也能覆盖）
        today = datetime.now()
        days = [today.strftime("%Y-%m-%d")]
        yest = (today - __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d")
        days.append(yest)

        msgs = []
        for d in days:
            for m in get_messages(d):
                if (m.get("chat_id") or "") == chat_id:
                    msgs.append(m)

        # 排除当前这条（它已经在正文里了）
        if exclude_msg_id:
            msgs = [m for m in msgs if m.get("message_id") != exclude_msg_id]

        if not msgs:
            return ""

        msgs.sort(key=lambda x: int(x.get("ts") or 0))
        msgs = msgs[-limit:]

        from name_map import display_name
        lines = []
        for m in msgs:
            try:
                t = datetime.fromtimestamp(int(m["ts"]) / 1000).strftime("%H:%M:%S")
            except (ValueError, TypeError, OSError, KeyError):
                t = "??:??:??"
            who = display_name(m.get("sender_id", ""), m.get("sender_name", ""))
            txt = (m.get("text") or "").strip().replace("\n", " ")
            if len(txt) > 120:
                txt = txt[:120] + "…"
            lines.append("[%s] %s: %s" % (t, who, txt))

        return "\n".join(lines)
    except Exception as e:
        logger.warning("构建上下文失败: %s", e)
        return ""


def on_message(data: P2ImMessageReceiveV1) -> None:
    """处理接收到的消息（单聊 + 群聊@机器人）。支持文本/富文本/图片/表情包等。"""
    try:
        event = data.event
        message = event.message
        msg_type = message.message_type if message else None

        raw = message.content or ""
        text, attachments = parse_message_content(msg_type, raw)

        # 下载图片类附件（表情包除外，表情包只是回应氛围，不需要理解内容）
        local_images = []
        for att in attachments:
            if att.get("type") in ("image", "sticker"):
                p = download_image(message.message_id if message else "",
                                   att.get("key", ""), att.get("type", "image"))
                if p:
                    local_images.append(p)
                    att["local_path"] = p

        # 空内容兜底：保证"收到过"这件事被记录
        if not text:
            text = "[%s]" % (msg_type or "unknown")

        # 解析 @ 提及：把 @_user_N 占位符还原成真实姓名
        mentions = []
        mention_map = {}
        for m in (message.mentions or []):
            key = getattr(m, "key", "") or ""
            name = getattr(m, "name", "") or ""
            mid = getattr(m, "id", None)
            m_open_id = (mid.open_id if mid else "") or ""
            if key:
                mention_map[key] = name or m_open_id
            mentions.append({
                "key": key,
                "name": name,
                "open_id": m_open_id,
            })

        for key, name in mention_map.items():
            text = text.replace(key, "@" + name)

        # 是否 @ 了机器人自己
        at_bot = any(m["name"] and BOT_NAME and BOT_NAME in m["name"] for m in mentions)

        sender_id = ""
        sender_name = "未知"
        sender = event.sender
        if sender:
            sid = sender.sender_id
            if sid:
                sender_id = sid.open_id or sid.user_id or sid.union_id or ""
            if sender.sender_type == "user":
                sender_name = resolve_user_name(sender_id)

        chat_type = getattr(message, "chat_type", "") or ""
        record = {
            "message_id": message.message_id if message else "",
            "text": text,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "ts": message.create_time if message else 0,
            "chat_id": (message.chat_id if message else "") or "",
            "chat_name": "群聊" if chat_type == "group" else "单聊",
            "chat_type": chat_type,
            "mentions": mentions,
            "at_bot": at_bot,
            "msg_type": msg_type,
            "images": local_images,
        }
        append_message(record)
        logger.info("记录消息: [%s] sender=%s at_bot=%s text=%s",
                    record["chat_name"], sender_name, at_bot, text[:80])

        # 群消息：自动登记该群，供群聊日报自动发现（无需手工配置）
        if chat_type == "group" and record["chat_id"]:
            try:
                import group_summary
                group_summary.register_chat(record["chat_id"])
            except Exception as e:
                logger.warning("登记群失败: %s", e)

        # 触发 agent：私聊 或 群里 @机器人 时走 agent 对话
        is_p2p = (chat_type == "p2p")
        if (is_p2p or at_bot) and sender_id:
            text_for_agent = text.strip()

            # 强制附带最近上下文：用户说「@我」「看一下」这种短消息时，
            # agent 必须靠前文才知道要干什么
            ctx = build_recent_context(record["chat_id"], limit=12,
                                       exclude_msg_id=record["message_id"])
            if ctx:
                text_for_agent = (
                    "【本群最近聊天记录（供你判断用户意图，不要复述）】\n%s\n"
                    "【用户当前这条消息】\n%s"
                    % (ctx, text_for_agent)
                )

            # 有图片时，把本地路径附在消息里，让 agent 知道可以看图
            if local_images:
                text_for_agent = (text_for_agent + "\n\n[用户附带了 %d 张图片，本地路径：\n%s\n可用 describe_image 或 read_image 工具查看]"
                                  % (len(local_images), "\n".join(local_images))).strip()
            if text_for_agent:
                # 2026-10-22：消息来源头——bot 已不代发回复，agent 处理完
                # 必须用 push.py 把完整回复推回来源（群 --chat / 私聊 --to）
                src_header = "【消息来源】%s chat_id=%s sender=%s(%s) 回复推送=%s\n" % (
                    "私聊" if is_p2p else "群聊",
                    record["chat_id"],
                    sender_name, sender_id,
                    ("push.py --to %s" % sender_id) if is_p2p
                    else ("push.py --chat %s" % record["chat_id"]),
                )
                text_for_agent = src_header + text_for_agent
                # 在独立线程处理，避免阻塞消息接收
                import threading as _th
                msg_id = record["message_id"]
                is_replying = False
                with _pending_lock:
                    is_replying = _pending_questions.get(sender_id, False)
                t = _th.Thread(target=handle_agent_reply,
                               args=(record['chat_id'], chat_type, sender_id, text_for_agent, msg_id, is_replying),
                               daemon=True)
                t.start()
    except Exception as e:
        logger.exception("处理消息出错: %s", e)



def handle_agent_reply(chat_id, chat_type, sender_id, text, message_id, is_replying=False):
    """把消息投递给 DSH agent（在独立线程中运行）。

    2026-10-22 改版：不再等待/转发 agent 回复。旧逻辑有两大缺陷：
    1) 只取回合第一条 assistant/message，多轮工具调用的回合只发开头一段（截断）；
    2) 回复固定私聊发给 sender，群消息的回复群里看不到、私聊却收到，
       与 agent 自己的 push 推送重复（用户看到两遍）。
    现在只负责：贴"收到"表情 → 消息入队 → 投递失败时通知用户。
    agent 处理完成后自行用 push.py 把完整回复推送到消息来源（群 --chat / 私聊 --to）。
    """
    try:
        add_reaction(message_id, "SALUTE")
        logger.info("已贴收到表情")

        ok2, err = dsh_bridge.send_message(text, timeout=180, wait_reply=False)
        if not ok2:
            # 连接类错误给友好提示，避免用户看到技术堆栈
            low = (err or "").lower()
            if "10061" in low or "refused" in low or "urlopen" in low or "timed out" in low:
                send_text_to_user(
                    sender_id,
                    "刚才那下没接住——DSH 服务瞬间忙了一下（我正在跑长任务时可能短暂拒绝新连接），"
                    "现在已经恢复了。麻烦再发一次，或者直接说「继续」。"
                )
            else:
                send_text_to_user(sender_id, "消息投递失败: %s" % err)
            return
        logger.info("消息已投递给 agent，等待 agent 自行推送回复")
    except Exception as e:
        logger.exception("agent 处理出错: %s", e)
        try:
            msg = str(e)
            if "10061" in msg or "refused" in msg.lower() or "urlopen" in msg.lower():
                send_text_to_user(
                    sender_id,
                    "刚才那下没接住——DSH 服务瞬间忙了一下（我在跑长任务时可能短暂拒绝新连接），"
                    "现在已经恢复。麻烦再发一次。"
                )
            else:
                send_text_to_user(sender_id, "处理时出错: %s" % msg)
        except Exception:
            pass


def resolve_user_name(open_id: str) -> str:
    """根据 open_id 查询用户姓名，失败返回原 id。

    注意：lark_oapi 的 contact 模块只有 v3（没有 v1），早期用 contact.v1
    会抛 AttributeError 被 except 吞掉，导致姓名永远显示 open_id。
    """
    if not open_id:
        return "未知"
    try:
        req = lark.contact.v3.GetUserRequest.builder() \
            .user_id_type("open_id") \
            .user_id(open_id) \
            .build()
        resp = get_client().contact.v3.user.get(req)
        if resp.success() and resp.data and resp.data.user:
            return resp.data.user.name or open_id
    except Exception as e:
        logger.debug("查询用户姓名失败 %s: %s", open_id, e)
    return open_id


def send_text_to_user(open_id: str, text: str) -> bool:
    """向指定用户发送文本消息。"""
    try:
        body = CreateMessageRequestBody.builder() \
            .receive_id(open_id) \
            .msg_type("text") \
            .content(json.dumps({"text": text}, ensure_ascii=False)) \
            .build()
        req = CreateMessageRequest.builder() \
            .receive_id_type("open_id") \
            .request_body(body) \
            .build()
        resp = get_client().im.v1.message.create(req)
        if not resp.success():
            logger.error("发送失败: code=%s msg=%s", resp.code, resp.msg)
            return False
        return True
    except Exception as e:
        logger.exception("发送消息出错: %s", e)
        return False


def add_reaction(message_id: str, emoji_type: str) -> bool:
    """给指定消息添加 emoji 反应（贴表情）。"""
    if not message_id:
        return False
    try:
        body = CreateMessageReactionRequestBody.builder()             .reaction_type(Emoji.builder().emoji_type(emoji_type).build())             .build()
        req = CreateMessageReactionRequest.builder()             .message_id(message_id)             .request_body(body)             .build()
        resp = get_client().im.v1.message_reaction.create(req)
        if not resp.success():
            logger.info("贴表情失败: %s %s", resp.code, resp.msg)
            return False
        return True
    except Exception as e:
        logger.exception("贴表情出错: %s", e)
        return False


def daily_report_job() -> None:
    """定时生成并推送日报。"""
    try:
        report = build_daily_report()
        logger.info("日报已生成:\n%s", report)
        if not REPORT_TARGET_OPEN_ID:
            logger.warning("未配置 FEISHU_REPORT_TARGET，日报仅写日志未推送")
            return
        if send_text_to_user(REPORT_TARGET_OPEN_ID, report):
            logger.info("日报已推送给 %s", REPORT_TARGET_OPEN_ID)
        else:
            logger.error("日报推送失败")
    except Exception as e:
        logger.exception("生成日报出错: %s", e)


def group_summary_job() -> None:
    """定时生成并推送所有群的聊天总结。"""
    try:
        import group_summary

        day = datetime.now().strftime("%Y-%m-%d")
        logger.info("开始生成群聊日报 %s", day)
        body = group_summary.build_all_summaries(day)

        if not body:
            # 2026-10-26 按用户要求：无消息也发一条简短提示，而不是静默跳过
            if REPORT_TARGET_OPEN_ID:
                send_text_to_user(
                    REPORT_TARGET_OPEN_ID,
                    "【群聊日报】%s\n今日各群无消息，安静的一天喵～" % day,
                )
            logger.info("今日所有群均无消息，已推送安静提示")
            return

        if not REPORT_TARGET_OPEN_ID:
            logger.warning("未配置 FEISHU_REPORT_TARGET，群总结仅写日志")
            logger.info("群总结:\n%s", body)
            return
        if send_text_to_user(REPORT_TARGET_OPEN_ID, body):
            logger.info("群总结已推送")
        else:
            logger.error("群总结推送失败")
    except Exception as e:
        logger.exception("生成群总结出错: %s", e)


def scheduler_loop() -> None:
    """简单定时器线程：到点触发群聊总结。

    消息统计日报（daily_report_job）已按用户要求停用，函数保留备查，
    如需恢复在循环里重新调用即可。
    """
    last_summary = ""
    while True:
        now = datetime.now()
        hm = now.strftime("%H:%M")
        day = now.strftime("%Y-%m-%d")

        # 群聊总结（时间由 .env 的 GROUP_SUMMARY_TIME 控制，缺省 18:30）
        stamp2 = "summary %s %s" % (day, hm)
        if hm == GROUP_SUMMARY_TIME and stamp2 != last_summary:
            last_summary = stamp2
            group_summary_job()

        time.sleep(20)


def main() -> None:
    if not APP_ID or not APP_SECRET:
        logger.error("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET，请检查 .env")
        return

    threading.Thread(target=scheduler_loop, daemon=True).start()

    handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(on_message) \
        .register_p2_im_chat_member_bot_added_v1(on_bot_added) \
        .register_p2_im_message_reaction_created_v1(on_reaction_created) \
        .build()

    # lark-oapi 1.x 长连接客户端（WebSocket）
    ws_client = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    logger.info("机器人 %s 启动，等待消息...", BOT_NAME)
    try:
        ws_client.start()
    except KeyboardInterrupt:
        logger.info("收到退出信号，机器人已停止")
    except Exception as e:
        logger.exception("机器人异常退出: %s", e)


if __name__ == "__main__":
    main()
