"""DSH 桥接模块：让飞书机器人驱动 DSH 持久 agent 会话。

通过 DSH web 的 /api 接口（127.0.0.1:3080）向一个持久会话发消息并获取回复。
会话有完整上下文，agent 具备读代码、跑命令、用 skill 的能力。

2026-10-26 适配 DSH 0.2.1-rc.3（重大协议变更）：
- API 全部要求鉴权：用 ~/.dsh/.credentials.yaml 的 browser-session secret
  自签 cookie（v1.payload.hmac，payload 无 id 字段走共享 browserPeer 身份）。
- RPC 方法名 session.xxx → session/xxx，payload 统一包装 {args:{request:...}}。
- session.history 移除：拉历史改用 session/projections（拿 asOfSeq 游标）
  + session/page（throughSeq=游标，返回 {event:{type,seq,data}} 壳结构不变）。
- session.prompt 新增必填 requestId（客户端自造）。
"""
import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
import uuid

DSH_BASE = "http://127.0.0.1:3080/api"
SESSION_ID_FILE = "data/dsh_session_id.txt"
CREDENTIALS_FILE = r"C:\Users\shenmengting\.dsh\.credentials.yaml"
AUTHORITY = "127.0.0.1:3080"

DEFAULT_CWD = "E:/feishu-bot"
AGENT_PRESET = "feishu-bot"

# 连接类错误（DSH 短暂忙/重启时会出现），需要重试
_RETRYABLE = (urllib.error.URLError, ConnectionError, TimeoutError, OSError)
_MAX_RETRY = 3
_RETRY_DELAY = 1.5  # 秒，逐次递增


# ---------------- 鉴权（0.2.1 browser-session cookie 自签） ----------------

_cookie_cache = {"value": "", "expiresAt": 0}


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _sign_cookie() -> str:
    """读 browser-session secret 自签 API cookie（共享 browserPeer 身份）。"""
    import yaml
    with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
        stored = yaml.safe_load(f)["records"][
            "client-connection/browser-session"]["payload"]["secret"]
    secret = base64.urlsafe_b64decode(stored + "=" * (-len(stored) % 4))
    now = int(time.time() * 1000)
    expires = now + 20 * 24 * 3600 * 1000  # 20 天，服务端默认 30 天
    payload = {"version": 1, "authority": AUTHORITY, "issuedAt": now,
               "expiresAt": expires}
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())
    name = "dsh-auth-" + _b64url(hashlib.sha256(AUTHORITY.encode()).digest())
    _cookie_cache["value"] = "%s=v1.%s.%s" % (name, body, sig)
    _cookie_cache["expiresAt"] = expires
    return _cookie_cache["value"]


def _auth_cookie() -> str:
    if not _cookie_cache["value"] or time.time() * 1000 > _cookie_cache["expiresAt"] - 3600_000:
        try:
            return _sign_cookie()
        except Exception:
            return _cookie_cache["value"]  # 签不了就用旧的（可能仍有效）
    return _cookie_cache["value"]


# ---------------- RPC ----------------

def _call(method, payload, timeout=30, retry=None):
    """调用 DSH API。连接失败自动重试；401 时重签 cookie 再试一次。

    0.2.1：方法名点号自动转斜杠（session.create → session/create），
    payload 包装为 {args:{request:...}}，兼容旧调用方写法。
    retry: 重试次数，缺省 _MAX_RETRY。传 0 表示不重试。
    """
    attempts = _MAX_RETRY if retry is None else retry
    wire_method = method.replace(".", "/", 1)
    wire_payload = {"args": {"request": payload}}
    last_err = None
    refreshed = False
    for i in range(attempts + 1):
        req = urllib.request.Request(
            DSH_BASE + "/" + wire_method,
            data=json.dumps({
                "type": "client-request",
                "rpcId": "fb-" + uuid.uuid4().hex[:12],
                "method": wire_method,
                "payload": wire_payload,
            }).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Cookie": _auth_cookie(),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401 and not refreshed:
                # secret 可能轮换过，重签一次
                _cookie_cache["value"] = ""
                refreshed = True
                try:
                    _sign_cookie()
                except Exception:
                    pass
                continue
            if e.code in (429, 502, 503) and i < attempts:
                time.sleep(_RETRY_DELAY * (i + 1))
                continue
            raise
        except _RETRYABLE as e:
            last_err = e
            if i < attempts:
                delay = _RETRY_DELAY * (i + 1)
                print("[WARN] DSH 连接失败（第 %d/%d 次），%.1fs 后重试: %s"
                      % (i + 1, attempts + 1, delay, e), flush=True)
                time.sleep(delay)
                continue
            raise
    if last_err:
        raise last_err
    return {}


def _read_session_id():
    import os
    if os.path.exists(SESSION_ID_FILE):
        with open(SESSION_ID_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def _save_session_id(sid):
    import os
    os.makedirs(os.path.dirname(SESSION_ID_FILE), exist_ok=True)
    with open(SESSION_ID_FILE, "w", encoding="utf-8") as f:
        f.write(sid)


def get_or_create_session():
    sid = _read_session_id()
    if sid:
        return sid
    r = _call("session.create", {"cwd": DEFAULT_CWD, "agentPreset": AGENT_PRESET})
    result = r.get("result", {})
    if result.get("ok"):
        sid = result.get("value", {}).get("sessionId", "")
        _save_session_id(sid)
        return sid
    return ""


def get_cursor(sid):
    """当前事件游标（asOfSeq）。0.2.1 正路：session/projections。"""
    r = _call("session/projections", {"sessionId": sid}, timeout=15, retry=1)
    result = r.get("result", {})
    if result.get("ok"):
        return result.get("value", {}).get("asOfSeq", 0) or 0
    return 0


def get_latest_seq(sid):
    """兼容旧接口名：返回当前游标 seq。"""
    return get_cursor(sid)


def get_events(sid, max_messages=50, through_seq=None):
    """拉一段历史事件（message-aligned 倒序页）。

    0.2.1：session.history 已移除，改 projections(游标)+page。
    返回与旧版相同结构的列表：[{"event":{type,seq,data,...}}, ...]（升序）。
    """
    if through_seq is None:
        through_seq = get_cursor(sid)
        if through_seq <= 0:
            return []
    r = _call("session.page", {
        "address": {"kind": "session", "sessionId": sid},
        "throughSeq": through_seq,
        "maxMessages": max_messages,
    }, timeout=30, retry=1)
    result = r.get("result", {})
    if not result.get("ok"):
        return []
    records = result.get("value", {}).get("records", [])
    events = []
    for rec in records:
        ev = rec.get("event") or rec
        events.append(rec if rec.get("event") else {"event": rec})
    events.sort(key=lambda x: x.get("event", {}).get("seq", 0))
    return events


SYSTEM_CONSTRAINT = (
    "【系统约束】你是通过飞书机器人「水蜜桃桃」响应用户的助手，"
    "工作区在 E:/feishu-bot（机器人自己的代码目录）。"
    "你必须遵守以下规则：\n"
    "1. 绝对禁止调用 ask_user_question 或任何需要用户交互/等待用户输入的工具、"
    "提问、确认、审批请求。这些 DSH 交互式工具在飞书机器人上无法使用。\n"
    "2. 如果你需要向用户提问以获取信息，不要调用任何工具，"
    "而是在你的回复中用以下标记格式输出问题：\n"
    "   【请问】你的问题内容\n"
    "桥接层会把这个问题通过飞书消息发给用户，"
    "并在用户回复后把回复作为新消息送回给你。\n"
    "3. 除了上述提问场景外，最终必须以一段完整的文本回复用户。\n"
    "4. 如果任务需要读取文件或日志，直接使用工具读取分析，不要因此询问用户。\n"
    "5. 【推送】你的普通回复不会自动到达飞书——任务完成后必须主动调 "
    "push.py 推送结果（cd E:\\feishu-bot && py -3 push.py ...）；"
    "耗时长的任务中途推进度；要用户决策必须主动推送提问。"
    "例外：收到「你是团队沟通总结助手」开头的日报流水线请求时不推（流水线自己推）。\n"
    "6. 【风格】闲聊/群互动消息简短像真人（几行内、结论先行）；"
    "技术支持/问题解决类给足信息（结论+关键证据+原因+措施）。\n"
    "7. 【外派】需独立处理的任务（现场问题、日志分析、代码排查）开子 agent 处理，"
    "主会话只做调度汇总，避免上下文污染。\n"
    "8. 【上下文】每条 @消息前已自动附带本群最近聊天记录，"
    "用户短消息（如「继续」）先看上下文再行动，不要反问。\n"
    "9. 【中文推送】长中文文本必须先写 UTF-8 文件再 py -3 push.py --file <路径>，"
    "不要内联在命令行参数里（编码会乱）。workdir 用 E:\\feishu-bot。\n"
    "10. 【引用回复】消息头里的【引用回复】行给了本条消息的 message_id。"
    "回复时**默认加上 --reply <该 id>**，飞书会显示成引用回复，"
    "对方一眼能看出你在回哪一条。只在明确不需要关联原文时才省略。\n"
    "11. 【先判断再问·禁止把草稿发出去】任何需要用户决策的事，问之前先过三关：\n"
    "   (a) 该不该问——能自己查资料/读代码/看历史消息解决的，不要问；\n"
    "   (b) 该问谁——涉及内部技术细节、系统配置、他人隐私、可能刷屏的长内容，"
    "走私聊问负责人（push.py --to <sender open_id>），不要在群里公开问；\n"
    "   (c) 怎么问——飞书没有交互式 UI，只能纯文本问，禁止罗列「1. xxx 2. xxx 选哪个」"
    "这种选择题格式。\n"
    "   **绝对禁止把内部思考过程、自我辩论、方案对比、草稿片段直接发出去**——"
    "那是草稿不是消息。发出去的每一条都必须是「已经想清楚、准备让所有人看到」的成品。\n"
)



QUESTION_MARK = "【请问】"

def send_message(text, timeout=180, wait_reply=True):
    """把消息送进 DSH agent 会话。

    wait_reply=False：只入队立即返回（2026-10-22 新增）。bot 不再代收回复——
    旧取回逻辑只拿回合第一条 assistant/message，会截断后续内容，已弃用；
    agent 处理完自行用 push.py 把完整回复推送到消息来源。
    """
    sid = get_or_create_session()
    if not sid:
        return False, "无法创建/获取 DSH 会话"

    r = _call("session.prompt", {
        "requestId": "fb-" + uuid.uuid4().hex[:16],
        "sessionId": sid,
        "mode": "queue",
        "content": [{"type": "text", "text": text}],
    }, timeout=30)
    if not r.get("result", {}).get("ok"):
        return False, "消息发送失败: %s" % json.dumps(r.get("result", {}), ensure_ascii=False)[:200]

    if not wait_reply:
        return True, ""

    before_seq = get_cursor(sid)

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        events = get_events(sid, max_messages=50)
        for item in events:
            ev = item.get("event", {})
            if ev.get("type") == "assistant/message" and ev.get("seq", 0) > before_seq:
                msg = ev.get("data", {}).get("message", {})
                content = msg.get("content", [])
                texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                reply = "".join(texts).strip()
                if reply:
                    return True, reply
        r2 = _call("session.list", {}, timeout=30)
        for s in r2.get("result", {}).get("value", {}).get("items", []):
            if s.get("sessionId") == sid and not s.get("running"):
                return True, "（agent 已完成，但无文本回复）"

    return False, "等待 agent 回复超时（%d 秒）" % timeout



def is_question(reply):
    """判断 agent 回复是否为向用户提问（含【请问】标记）。"""
    return QUESTION_MARK in reply


def extract_question(reply):
    """提取【请问】标记后的问题文本。"""
    idx = reply.find(QUESTION_MARK)
    if idx >= 0:
        return reply[idx + len(QUESTION_MARK):].strip()
    return reply
