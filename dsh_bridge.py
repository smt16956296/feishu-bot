"""DSH 桥接模块：让飞书机器人驱动 DSH 持久 agent 会话。

通过 DSH web 的 /api 接口（127.0.0.1:3080）向一个持久会话发消息并获取回复。
会话有完整上下文，agent 具备读代码、跑命令、用 skill 的能力。
"""
import json
import time
import urllib.error
import urllib.request

DSH_BASE = "http://127.0.0.1:3080/api"
SESSION_ID_FILE = "data/dsh_session_id.txt"

DEFAULT_CWD = "E:/feishu-bot"
AGENT_PRESET = "feishu-bot"

# 连接类错误（DSH 短暂忙/重启时会出现），需要重试
_RETRYABLE = (urllib.error.URLError, ConnectionError, TimeoutError, OSError)
_MAX_RETRY = 3
_RETRY_DELAY = 1.5  # 秒，逐次递增


def _call(method, payload, timeout=30, retry=None):
    """调用 DSH API。连接失败自动重试（DSH 处理长任务时可能短暂拒绝连接）。

    retry: 重试次数，缺省 _MAX_RETRY。传 0 表示不重试。
    """
    attempts = _MAX_RETRY if retry is None else retry
    last_err = None
    for i in range(attempts + 1):
        req = urllib.request.Request(
            DSH_BASE + "/" + method,
            data=json.dumps({
                "type": "client-request",
                "rpcId": "fb-" + str(int(time.time() * 1000)),
                "method": method,
                "payload": payload,
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
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


def get_latest_seq(sid):
    r = _call("session.history", {"sessionId": sid, "maxMessages": 5})
    events = r.get("result", {}).get("value", {}).get("events", [])
    if events:
        return events[-1].get("event", {}).get("seq", 0)
    return 0


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
)



QUESTION_MARK = "【请问】"

def send_message(text, timeout=180):
    sid = get_or_create_session()
    if not sid:
        return False, "无法创建/获取 DSH 会话"

    before_seq = get_latest_seq(sid)

    r = _call("session.prompt", {
        "sessionId": sid,
        "mode": "queue",
        "content": [{"type": "text", "text": text}],
    }, timeout=30)
    if not r.get("result", {}).get("ok"):
        return False, "消息发送失败: %s" % json.dumps(r.get("result", {}), ensure_ascii=False)[:200]

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        r = _call("session.history", {"sessionId": sid, "maxMessages": 50})
        events = r.get("result", {}).get("value", {}).get("events", [])
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

