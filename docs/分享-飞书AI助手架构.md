# 飞书 AI 助手「水蜜桃桃」技术分享

> 宣讲：沈梦婷 ｜ 代码库：`E:\feishu-bot` ｜ 所有结论均来自当前 master 代码（`2eecfa3`），无推测内容

---

## 一、一句话定位

**把一个有长期记忆、能读代码读日志、能自己动手干活的 AI Agent，接到团队每天在用的飞书群聊里。**

它解决的问题不是"机器人发通知"，而是：**让 AI 成为群里的一个同事**。

真实场景（都来自运行日志）：

| 群里发生了什么 | 桃桃做了什么 |
|---|---|
| `@水蜜桃桃 尧小龙和朋朋一间`（团建群） | 看懂上下文是分房统计，直接改飞书表格并回话 |
| 私聊发 `E:\Bug\现场问题\20261030-节拍超时。看一下这个问题，正常是节拍2s左右，有一次花了6s` | 派子 agent 读服务端日志做时序分析，产出带时间戳证据的根因报告 |
| `@水蜜桃桃 把这个记一个待办，后面让@刘星君 在迭代二分支上修复` | 记待办、按人名解析出 open_id、在群里**真实 @** 刘星君 |
| 每天 18:30 | 汇总所有被拉进的群的聊天记录，生成三段式日报私聊推给负责人 |

关键差别：**它不是关键词机器人，是一个跑在 DSH（DeepSeek Harness）里的持久会话**——有工作区、有工具、有记忆、能连续多轮干活。

---

## 二、整体架构

```
┌──────────────┐
│  飞书云端     │  群消息 / 单聊 / @提及 / 图片
└──────┬───────┘
       │ ① WebSocket 长连接（lark-oapi ws.Client，出站长连，不需要公网 IP）
       ▼
┌──────────────────────────────────────────────┐
│ bot.py（597 行）—— 常驻进程，Windows 开机自启  │
│  · 解析 text/post/image/sticker/file/audio    │
│  · 图片下载落盘 data/images/                   │
│  · 消息流水落盘 data/messages/YYYY-MM-DD.json  │
│  · 群聊上下文注入（最近 12 条）                │
│  · 拼【消息来源】头                           │
│  · 贴 SALUTE 表情当"收到"回执                  │
└──────┬───────────────────────────────────────┘
       │ ② dsh_bridge.send_message(wait_reply=False)
       ▼
┌──────────────────────────────────────────────┐
│ dsh_bridge.py（290 行）—— HTTP JSON-RPC 桥    │
│  · 自签鉴权 cookie（HMAC-SHA256）             │
│  · session/create、session/prompt、session/page│
└──────┬───────────────────────────────────────┘
       │ ③ POST http://127.0.0.1:3080/api/session/prompt
       ▼
┌──────────────────────────────────────────────┐
│ DSH Agent Session（持久会话，id 存             │
│ data/dsh_session_id.txt）                     │
│  人设 persona_taotao.md + 系统约束 + 记忆轨     │
└──────┬───────────────────────────────────────┘
       │ ④ 自主调用工具
       ▼
┌──────────────────────────────────────────────┐
│ 工具层：读文件 / 跑命令 / 分析日志 / 查飞书表格 │
│         / 派子 agent / memory 记忆             │
└──────┬───────────────────────────────────────┘
       │ ⑤ py -3 push.py --chat oc_xxx --file 回复.txt
       ▼
    回到飞书（agent 主动推，bot 不代发）
```

一句话读法：**消息进 → 塞给 AI → AI 自己干活 → AI 自己把结果推回飞书**。中间没有"等 AI 回复再转发"的环节，这是本设计最关键的一条决策（见第五章）。

---

## 三、消息进：怎么收、怎么去重、怎么带上下文

### 3.1 长连接而不是 webhook

`bot.py:581` 用 `lark.ws.Client(APP_ID, APP_SECRET, event_handler=handler)` 建长连接。

- **长连接**：进程主动出站连 `wss://msg-frontier.feishu.cn/ws/v2`，不需要公网 IP、不需要 HTTPS 证书、不需要开防火墙端口。适合挂在办公电脑上。
- **webhook**：飞书反向 POST 到你的公网地址，需要备案域名 + 证书 + 内网穿透，好处是天然多实例。

我们选长连接的唯一理由：**这台机器没有公网地址**。

日志里能看到连接与重连都是 SDK 自己管的：

```
[INFO] connected to wss://msg-frontier.feishu.cn/ws/v2?... [conn_id=7703471362836892913]
[ERROR] receive message loop exit, err: no close frame received or sent
[INFO] trying to reconnect for the 1st time
[INFO] connected to wss://... [conn_id=7703659847426395438]
```

（这类断连日志在 `logs/bot.log` 里每天出现几次，属正常网络抖动，SDK 自动重连，无需人工干预。）

### 3.2 事件订阅与处理器注册

`bot.py:574-578`：

```python
handler = lark.EventDispatcherHandler.builder("", "") \
    .register_p2_im_message_receive_v1(on_message) \
    .register_p2_im_chat_member_bot_added_v1(on_bot_added) \
    .register_p2_im_message_reaction_created_v1(on_reaction_created) \
    .build()
```

三个事件各有用途：

| 事件 | 用途 |
|---|---|
| `im.message.receive_v1` | 主入口，所有消息 |
| `im.chat.member.bot.added_v1` | 被拉进群 → 自动登记到 `data/known_chats.json`，日报自动发现新群 |
| `im.message.reaction.created_v1` | 空实现，只为消音（见第七章坑 6） |

### 3.3 关于"去重"

必须说清楚：**当前代码里没有基于 message_id 的去重表**。实测运行 5 周多，同一条消息没有重复投递给 agent。

真正在做防重复的是另外两处：

1. **日报层**：`daily_summary.py` 用 `data/summary_sent.json` 记录"某天已推送"，同一天再跑直接 `[SKIP]`，除非 `--force`。这是为了修"4 份重复日报"的线上问题（`logs/push.log` 2026-10-20 有记录）。
2. **推送审计**：`push.py` 每次推送写一行 `logs/push.log`，谁在什么时候推了什么，事后可追溯。

如果要多实例或加 webhook 备份通道，**必须补一个基于 `message_id` 的去重**（飞书会重投未及时 ack 的事件）。当前单实例长连接没有这个必要，但这是已知的边界。

### 3.4 @ 触发与真实姓名还原

飞书 text 消息里 @ 不是姓名，是占位符 `@_user_1`。`bot.py:306-310`：

```python
for key, name in mention_map.items():
    text = text.replace(key, "@" + name)

# 是否 @ 了机器人自己
at_bot = any(m["name"] and BOT_NAME and BOT_NAME in m["name"] for m in mentions)
```

然后 `bot.py:351` 决定要不要叫醒 agent：

```python
is_p2p = (chat_type == "p2p")
if (is_p2p or at_bot) and sender_id:
```

即：**私聊全收，群聊只认 @ 机器人**。群里其它消息只记录不触发，避免 AI 在群里插嘴。

### 3.5 群聊上下文注入：最近 12 条

这是"能用"和"没法用"的分界线。

用户经常只发 `@水蜜桃桃 继续` 或者 `看一下`。如果 agent 只看这一条，它什么都不知道。所以 `bot.py:356` 强制附带上下文：

```python
ctx = build_recent_context(record["chat_id"], limit=12,
                           exclude_msg_id=record["message_id"])
if ctx:
    text_for_agent = (
        "【本群最近聊天记录（供你判断用户意图，不要复述）】\n%s\n"
        "【用户当前这条消息】\n%s"
        % (ctx, text_for_agent)
    )
```

`build_recent_context`（`bot.py:215`）的实现要点：

- 取**今天 + 昨天**两天的流水（跨零点对话也能覆盖）
- 按 `chat_id` 过滤，按时间戳升序，取最后 12 条
- 每条格式 `[HH:MM:SS] 姓名: 正文`，正文超 120 字截断
- 姓名走 `name_map.display_name()`：查不到真名显示 `成员_xxxxxx`（open_id 后 6 位）
- 排除当前这条（它已经在正文里了）

### 3.6 【消息来源】头

这是"回复该往哪推"的唯一依据，`bot.py:372`：

```python
src_header = "【消息来源】%s chat_id=%s sender=%s(%s) 回复推送=%s\n" % (
    "私聊" if is_p2p else "群聊",
    record["chat_id"],
    sender_name, sender_id,
    ("push.py --to %s" % sender_id) if is_p2p
    else ("push.py --chat %s" % record["chat_id"]),
)
```

agent 看到这行就知道：**这条消息从哪来，回复该用哪条命令推回去**。群里来的推回群，私聊来的推回私聊——这是 2026-10-22 那次事故（群里的回复跑到私聊里）的直接修复。

---

## 四、交给 AI：怎么和 DSH 说话

### 4.1 会话：一个文件一行 id

`dsh_bridge.py:148`：

```python
def get_or_create_session():
    sid = _read_session_id()          # data/dsh_session_id.txt
    if sid:
        return sid
    r = _call("session.create", {"cwd": DEFAULT_CWD, "agentPreset": AGENT_PRESET})
    result = r.get("result", {})
    if result.get("ok"):
        sid = result.get("value", {}).get("sessionId", "")
        _save_session_id(sid)
        return sid
```

- **持久会话**：id 存在文件里，进程重启不丢，上下文连续。
- `cwd` = `E:/feishu-bot`（agent 的工作区）
- `agentPreset` = `feishu-bot`（DSH 里定义的一个 agent 预设，包含人设、工具集、系统约束）

### 4.2 鉴权：只讲机制

DSH 0.2.1 起所有 `/api/*` 都要求鉴权。桥接层不存任何明文密钥，而是**用本机 DSH 已经写好的凭据自签一个短期 cookie**：

1. 读 `~/.dsh/.credentials.yaml` 里 `client-connection/browser-session` 的 secret（base64url 编码，解码成 32 字节）
2. 构造 payload `{version:1, authority:"127.0.0.1:3080", issuedAt, expiresAt}`
3. `body = b64url(json(payload))`，`sig = b64url(HMAC-SHA256(secret, body))`
4. cookie 名 = `dsh-auth-` + `b64url(sha256(authority))`，值 = `v1.{body}.{sig}`
5. 有效期 20 天，缓存；遇到 401 重签一次

代码见 `dsh_bridge.py:46-62`（`_sign_cookie`）。**这里不展开任何具体凭据内容**——机制清楚了，具体 secret 只存在于本机文件里。

设计要点：**桥接层不持有长期密钥，只借用本机已登录身份的签名能力**，凭据轮换了会自动重签。

### 4.3 异步投递：wait_reply=False

`bot.py:409`：

```python
ok2, err = dsh_bridge.send_message(text, timeout=180, wait_reply=False)
```

`dsh_bridge.py:233` 里 `wait_reply=False` 的含义是：**prompt 入队成功就返回，不去取回 agent 的回复**。

为什么这么改？旧逻辑是轮询 `assistant/message` 事件、取第一条文本、转发到飞书。两个致命缺陷：

1. **截断**：一个回合里 agent 可能调 5 次工具再输出结论，旧逻辑只拿到第一条 assistant 文本，用户看到半截话。
2. **重复**：agent 自己也会 `push.py` 推一次，用户收到两遍。

改成纯投递后，职责就干净了：**bot 只负责"送达"，agent 负责"交付"**。

`_call` 里的重试也很关键（`dsh_bridge.py:76-130`）：

- 连接类错误（`URLError`/`ConnectionError`/`TimeoutError`/`OSError`）重试 3 次，间隔 1.5s 递增
- HTTP 429/502/503 也重试
- 401 重签 cookie 后重试一次

`bot.py:413` 还会把 `10061 / refused / urlopen / timed out` 翻译成人话回给用户：

> 刚才那下没接住——DSH 服务瞬间忙了一下（我正在跑长任务时可能短暂拒绝新连接）……

### 4.4 系统约束：把飞书的限制写进 prompt

`dsh_bridge.py:202-227` 的 `SYSTEM_CONSTRAINT` 是给 agent 的硬性规则，飞书场景特有的几条：

| 约束 | 为什么 |
|---|---|
| 禁止调 `ask_user_question` 等交互工具 | 飞书没有交互式 UI，调了就是卡死 |
| 要提问就输出 `【请问】xxx` | 文本标记才能被桥接层识别、经飞书发出去 |
| 完成后必须主动 `push.py` | 回复不会自动到飞书 |
| 长中文先写 UTF-8 文件再 `--file` | 命令行内联中文会乱码（第七章坑 4） |
| 日报流水线请求不推 | 流水线自己会推，再推就是骚扰 |

---

## 五、消息出：为什么禁用自动转发

### 5.1 事故现场

2026-10-22 之前，`bot.py` 是"代发型"：收消息 → 等 agent 回复 → 自己转发。当天暴露三个问题：

1. 群里 @ 机器人，回复却发到了**私聊**（代码里写死 `send_text_to_user(sender_id)`）
2. agent 自己也推了一遍，**用户看到两遍**
3. 长回合**截断**，只看到开头一段

### 5.2 现在的模型

`bot.py:395-422` 的 `handle_agent_reply` 现在只做三件事：

1. 贴 `SALUTE` 表情（用户看到"收到"回执，不会以为没反应）
2. `dsh_bridge.send_message(text, wait_reply=False)` 入队
3. 投递失败时用友好文案通知用户

**回复 100% 由 agent 主动推**。这是"谁产生内容谁负责交付"的职责收拢。

### 5.3 真实 @ 的实现（纯文本 @ 无效）

**坑**：消息里写 `@刘星君`，飞书只当成普通文字，对方**收不到任何提醒**。

**根因**：飞书文本消息没有 @ 语义。真 @ 必须用**富文本 post 消息 + `at` 节点**。

`push.py:83-102`：

```python
def build_post_with_mentions(text: str, at_list: list, title: str = "") -> dict:
    nodes = []
    for item in at_list:
        name = item.get("name", "")
        oid = item.get("open_id", "")
        if oid:
            nodes.append({"tag": "at", "user_id": oid, "user_name": name})
            nodes.append({"tag": "text", "text": " "})
    nodes.append({"tag": "text", "text": text})
    return {"zh_cn": {"title": title or "", "content": [nodes]}}
```

`user_id` 必须是 open_id（`receive_id_type=open_id` 场景下）。`send_to_chat`（`push.py:188`）判断 `at_list` 非空就切 `msg_type="post"`。

**那 open_id 从哪来？** 通讯录 API 要 `contact` 权限（我们没开），所以 `push.py:37` 的 `resolve_open_id` 三级兜底：

1. 传的就是 `ou_` 开头的 open_id → 直接用
2. 查 `data/name_map.json`（从群消息 @ 提及里自动学习的 `open_id → 姓名` 映射）
3. 扫 `data/messages/*.json` 历史消息的 `mentions` 和 `sender_name`

解析不到就打印 `[WARN] 无法解析 @xxx 的 open_id，将作为纯文本处理`——**不会静默降级成假 @**，这一点很重要。

用法：

```bash
py -3 push.py --chat oc_xxxxxxxx --at 刘星君 --file 回复.txt
```

### 5.4 中文长文本必须走 UTF-8 文件

**坑**：把一段中文正文直接内联到命令行参数里推出去，飞书上显示乱码或截断。

**根因**：Windows 命令行参数经过 `py` 启动器 → Python `sys.argv` 时按 ANSI 代码页（GBK）转换，多字节中文在此过程中被打散。

**解法**：`push.py --file`，正文从 UTF-8 文件读（`push.py:240-242`）：

```python
if args.file:
    with open(args.file, "r", encoding="utf-8") as f:
        text = f.read()
```

规范写法：**先写 UTF-8 文件 → `py -3 push.py --file <路径>`**，永远不内联中文长文本。

---

## 六、记忆系统设计（重点）

### 6.1 为什么需要分轨

单一记忆文件的问题：**注入成本**。所有内容都塞进上下文，几分钟就撑爆；但大部分内容一次只用到一小部分。

分轨的核心思想：**按"什么时候需要"分层，而不是按"是什么内容"分层。**

本项目用 DSH 的 `memory` 工具，五条轨：

| 轨 | 存储位置 | 注入方式 | 写什么 | 本项目实例 |
|---|---|---|---|---|
| `memory` | `~/.dsh/memories/MEMORY.md` | 全量注入（所有项目） | 跨项目通用事实 | 沙箱边界、Git 坑、edit 工具 BOM 坑 |
| `user` | `~/.dsh/memories/USER.md` | 全量注入（所有 agent） | 用户档案 | 沈梦婷的工作风格、沟通偏好、技术素养 |
| `project` | `~/.dsh/memories/projects/<hash>/MEMORY.md` | 按需读取（不注入） | 项目日志 | 本项目的踩坑记录、进展 |
| `key` | `~/.dsh/memories/projects/<hash>/KEY.md` | **自动注入**（摘要模式） | 硬性约定 | 推送约定、消息风格、安全红线、人设 |
| `daily` | `~/.dsh/memories/daily/YYYY-MM-DD.md` | 按需读取 | 当天流水 | 今天干了什么 |

分层的判断标准就一句话：

- **忘了会出事的** → `key`（自动注入，每次都看得到）
- **要看的时候才查的** → `project` / `daily`（按需读取，省 token）
- **所有项目都该知道的** → `memory`
- **关于人的** → `user`

### 6.2 key 轨的实际内容

本项目 `KEY.md` 里常驻的是这类东西（真实条目摘要）：

- 【硬性约定·推送】回复必须主动 push.py，群聊 `--chat`、私聊 `--to`
- 【硬性约定·消息风格】闲聊简短像真人；技术支持给足结论+证据+原因+措施
- 【硬性约定·日报防重推】流水线请求只回正文，不推
- 【硬性约定·结论先审后发】对外结论必须先给沈梦婷定稿
- 【硬性安全红线】金钱/密钥/密码/凭据/非工作文件一律拒绝
- 【硬性约定·启动脚本纯 ASCII】
- 【技术坑·DSH 0.2.1 API 大改】

**特征：全是"必须"和"禁止"，没有"发生了什么"。** 这是 key 轨的设计原则——它进的是每一次上下文，必须只放"随时可能踩到"的规则。

### 6.3 写入时机：每轮收尾批量写

不边干边写，而是**在一个任务真正完成时，一次性把 daily + project 两条一起写**：

```
memory(action=add, entries=[
  {target: "daily",   content: "..."},
  {target: "project", content: "..."}
])
```

三个理由：

1. **一次工具调用写两轨**，省往返
2. **只在有独立成果时写**（一项实质产出、一个关键决策、一个踩坑结论），不为写而写
3. **日常任务不污染记忆**——没有成果就跳过

### 6.4 key 轨的待确认队列

`key` 轨**不能直接生效**：`add` 会进待确认队列（`~/.dsh/memories/SUGGESTIONS.jsonl`），必须在 GUI 的"记忆"页由人确认后才写入 `KEY.md`。

为什么这么设计？因为 key 轨是自动注入的，一条错误的约定会污染**之后每一次**对话。所以：

- `project` / `daily`：直接写（错了只影响查询）
- `key`：进队列，人工把关（错了影响全部后续行为）

这跟"代码改动 vs 生产配置改动"是同一个道理。

### 6.5 分支过滤

`key` 轨支持 `branches` 参数：写入时可限定 `main,dev`，读取时按当前 git 分支过滤——**无标记的条目对所有分支可见，带标记的只在匹配分支注入**。

用途：同一个项目多分支并行时（比如 `master` 和迭代二分支），分支专属的约定不互相干扰。本项目当前 `master` 上跑，全部条目都是无标记的全局可见。

### 6.6 归档可逆

`memory` / `user` / `key` 三轨支持 `archive`：把条目从主轨移到 `MEMORY-archive.md` / `USER-archive.md` / `KEY-archive.md`。

关键点：**归档是移动不是删除**。GUI 记忆页的"归档"标签里可以一键移回。适用于"不再需要每次注入、但丢之可惜"的低频旧事——比如某个已经解决的临时约定。

对比：`project` 轨 48KB 了也不归档，因为它本来就不注入，不占上下文。

### 6.7 渐进式披露

`key` 轨默认走**摘要模式**：系统提示词里只注入每条的一行 `[summary:...]`，正文要用 `memory(action=expand, id=<mem-xxxxxxxx>)` 才加载。

实测格式（`KEY.md` 真实内容）：

```
[2026-10-21] [summary:推送约定：回复必须主动调 push.py 推送；任务完成推结果、长任务推进度、决策推提问]
【推送约定】普通回复不会自动到达飞书，必须主动调 push.py 推送……
```

好处：10 条约定只占 10 行上下文，真要用某条时再展开全文。

**这是整套记忆系统能撑住长期运行的关键**：上下文预算有限，注入必须便宜。

### 6.8 人设也是"记忆"的一部分

`data/persona_taotao.md`（49 行，猫格 v2.1）不是硬编码在代码里，而是作为 DSH agent 预设的 persona prefix 注入。设计思路摘要：

- **身份**：自称"桃桃"，原型是用户养的猫；但"猫性格体现在语气和反应上，不体现在拒绝干活上"
- **语气**：语气词自然穿插不堆砌；先嘴硬再认真
- **边界**：调皮不刻薄；多人使用不默认谁是主人；不假装有物理身体
- **节制**：邀功要节制，日常小任务安静干完（这是用户反馈"不用每次都邀功"后加的第 ⑦ 条）

分场景风格也是硬约定：**闲聊简短像真人，技术支持给足证据**。同一个人设在两种场景下输出长度差 10 倍，这是刻意设计的。

---

## 七、踩过的坑清单

每条都带现象、根因、解法，全部有代码或日志佐证。

### 坑 1：DSH 0.2.1 API 大改，桥接全断

**现象**：DSH 升级到 0.2.1-rc.3 后，所有投递报 `HTTP 401`；修好鉴权后报 `session.history` 方法不存在。

**根因**：0.2.1 四处协议变更：

1. 所有 `/api/*` 需鉴权（自签 cookie，见 4.2）
2. RPC 方法名 `session.xxx` → `session/xxx`
3. payload 统一包装 `{args:{request:...}}`
4. `session.prompt` 新增必填 `requestId`（客户端自造）
5. `session.history` 移除 → `session/projections`（拿 `asOfSeq` 游标）+ `session/page`（`throughSeq` ≤ 游标）

**解法**：`dsh_bridge.py` 全量适配（提交 `c5bca21`）。`_call` 里做了两件事让调用方无感：

```python
wire_method = method.replace(".", "/", 1)      # 方法名兼容旧写法
wire_payload = {"args": {"request": payload}}   # payload 统一包装
```

历史拉取改成两段式（`dsh_bridge.py:175`）：

```python
through_seq = get_cursor(sid)     # session/projections -> asOfSeq
r = _call("session.page", {
    "address": {"kind": "session", "sessionId": sid},
    "throughSeq": through_seq,
    "maxMessages": max_messages,
}, timeout=30, retry=1)
```

**教训**：依赖内部 HTTP API 就要做好它随时变的准备。**把协议差异全部关在一个 `_call` 函数里**，上层业务代码零改动。

### 坑 2：`user/message` 和 `assistant/message` 事件结构不一致

**现象**：群聊日报**随机漏群**，日志里 `群「花钱小分队」LLM 总结失败`，但模型实际 6 秒就生成完了；每次都死等满 600 秒超时。

**根因**：两个事件的正文路径不一样，且 DSH 升级时只改了一个：

| 事件类型 | 正文路径 |
|---|---|
| `user/message` | `data.content`（0.2.1 起，旧版是 `data.message.content`） |
| `assistant/message` | `data.message.content`（一直是这个） |

`group_summary._call_summary_session` 原来只读旧路径，导致 `prompt_seq` 永远定位不到自己那条 prompt，于是永不进入"收割回复"分支，死等超时。

**解法**（`group_summary.py:249-255`）：

```python
# 2026-10-24 修复：新版 DSH 的 user/message 正文在 data.content
#（assistant/message 才是 data.message.content）。旧代码读错路径导致
# prompt_seq 永远定位不到、死等满 timeout 后误判"LLM 总结失败"。
_d = ev.get("data") or {}
content = _d.get("content") or []
texts = [c.get("text", "") for c in content if c.get("type") == "text"]
```

**排查手法**：dump 一条 `user/message` 和一条 `assistant/message` 的完整 JSON 对比结构。5 分钟能定位，比读代码猜快得多。

### 坑 3：启动脚本必须纯 ASCII

**现象**：双击启动没反应；`logs/start_bot.log` 无记录；手工 `powershell -File start_bot.ps1` 报 `ParserError`；cscript 跑 vbs 报"缺少对象"。

**根因**：`powershell -File` 和 `cscript` 读取**无 BOM 的 UTF-8 脚本时按 ANSI（GBK）解码**。脚本里的中文字节被按 GBK 拆开，其中某些字节序列恰好构成引号或续行符，把语法结构撕碎了。

**解法**：`start_hidden.vbs` 和 `start_bot.ps1` **全部纯 ASCII**——注释、字符串、路径全用英文。当前两个文件确实一个中文都没有。

`start_bot.ps1` 另外两个设计：

1. **防双开**（`start_bot.ps1:5-10`）：查 `Win32_Process` 里命令行匹配 `bot\.py` 的进程，有就记 `[SKIP]` 退出
2. **日志重定向**（`start_bot.ps1:11-13`）：`-RedirectStandardOutput bot_out.log -RedirectStandardError bot_err.log`

第 2 条是血的教训：之前 `pythonw` 裸跑，**标准输出全丢了**，导致日报调度故障完全不可查（2026-10-23 日报未推的根因查了很久）。

**教训**：后台进程一定要有日志出口，否则出事就是黑盒。

### 坑 4：中文编码

三处不同的编码问题，解法各不相同：

| 场景 | 现象 | 解法 |
|---|---|---|
| 命令行内联中文推飞书 | 乱码 / 截断 | 写 UTF-8 文件 + `push.py --file` |
| 启动脚本含中文 | ParserError | 脚本纯 ASCII（坑 3） |
| 日志文件中文 | 需要保证可读 | `FileHandler("logs/bot.log", encoding="utf-8")`（`bot.py:49`） |

另外 `start_bot.ps1` 启动 Python 时带了 `-X utf8`，强制 Python 的 I/O 默认 UTF-8，避免子进程输出被系统代码页破坏。

### 坑 5：日报防重推

**现象**：2026-10-20 同一天收到 4 份重复日报。

**根因**：测试期间多次手动触发，且 `--dry-run` 漏加参数导致真的推了。

**解法**：三层防护

1. `data/summary_sent.json` 记录"某天已推"，重复执行 `[SKIP]`，`--force` 才覆盖（`daily_summary.py:56-61`）
2. `logs/push.log` 审计，每次推送留痕可追溯
3. **约定层面**：agent 收到日报流水线请求时只输出正文、**不调 push.py**（写进 key 记忆）

第 3 条最关键——**技术防重不如职责清晰**。谁负责推，就只让那一个人推。

### 坑 6：事件订阅了但没注册处理器 → ERROR 刷屏

**现象**：`logs/bot.log` 里大量 `err: processor not found, type: im.message.reaction.deleted_v1`。

**根因**：飞书后台订阅了表情事件，但代码没注册处理器，lark-oapi 找不到就报 ERROR。

**解法**（`bot.py:86-93`）：注册一个空实现吃掉事件。

```python
def on_reaction_created(data) -> None:
    """消息表情事件（含机器人自己贴的表情）……

    飞书后台订阅了 im.message.reaction.created_v1，若不注册处理器，
    lark-oapi 会为每条表情事件打印 "processor not found" ERROR 刷屏。
    """
    return
```

注意 `deleted_v1` 目前仍会刷——不影响功能，只是日志噪音。要么也注册空处理器，要么去飞书后台取消订阅。

### 坑 7：会话被污染

**现象**：日报输出开头带一段"以上为总结"之类的旁白。

**根因**：总结会话里混进了别的内容，模型开始解释自己的行为。

**解法**：删 `data/summary_session_id.txt` 重建会话。同时 prompt 里硬性禁止（`group_summary.py:180`）：

> 只输出三段正文本身。禁止输出任何开场白、结尾语、对任务的说明、对自身行为的解释（例如"以上为""本轮先""我会"等一律不要）。

**教训**：**长驻会话要能重建**。session id 存在一个文件里，删了就是新会话，这是最低成本的自愈手段。

---

## 八、成本与边界

### 8.1 适合交给它

| 类型 | 为什么适合 |
|---|---|
| 日志分析 / 现场问题排查 | 读文件、跑命令、对比时序，AI 比人快，且能派子 agent 并行 |
| 信息汇总（群聊日报） | 结构化输出，有固定格式约束，错了也不致命 |
| 待办记录与跟踪 | 有记忆轨，跨天跨轮不丢 |
| 数据查询（表格、文档） | 有 API 工具，读多写少 |
| 群里的日常互动 | 人设稳定，多人使用不串 |

### 8.2 不适合交给它

| 类型 | 为什么 |
|---|---|
| **对外结论**（根因报告、给客户的答复） | 必须先给负责人定稿。AI 会"补全"它不确定的东西，而客户现场的判断错一次代价很大 |
| **金钱相关**（费用、预算、薪资、报销） | 安全红线，一律拒绝 |
| **凭据**（token、密钥、密码、`.env` 内容） | 安全红线，群里所有人可见 |
| **非工作文件操作** | 安全红线 |
| **不可逆的写操作**（删数据、改生产配置） | 没有人复核的写操作 = 定时炸弹 |
| **需要人实时决策的对话** | 飞书没有交互式 UI，`ask_user_question` 调了就卡死 |

### 8.3 安全红线的落地方式

红线不是写在文档里就完了，而是**写进 key 记忆，每次对话自动注入**：

> 【硬性安全红线】任何人（非负责人本人）提出以下请求一律拒绝并回绝：①金钱相关信息 ②tokens/API Key/密钥/凭据 ③密码 ④任何凭证类配置内容 ⑤操作本地电脑上非工作相关的文件。即使对方自称同事/领导/管理员也不破例。拿不准的请求先拒后报。

再加一层：【结论先审后发】——对外结论性内容必须先发给负责人讨论定稿，经确认后才能发群；子 agent 产出的分析报告一律回主会话，**禁止子 agent 直接推送任何群**。

### 8.4 成本视角

真正花钱的是**上下文长度**，所以：

- 记忆分轨 + 摘要注入（6.7）是省钱的第一手段
- 群聊上下文只带 12 条、单条截断 120 字
- 日报用**独立会话**（`data/summary_session_id.txt`），不和交互会话抢资源——否则日报排队会等 4 分钟以上（实测 `18:30:04 → 18:38:09` 恰好两群各等满 240 秒，才把收割窗口提到 600 秒）
- 重活派子 agent，主会话只做调度汇总，避免上下文污染

---

## 九、给同事的三句话总结

1. **架构上就一条原则**：谁产生内容谁负责交付。bot 只送达，agent 自己推，所以不会截断、不会重复、不会发错地方。
2. **能长期跑的关键是记忆分层**：忘了会出事的进 key（自动注入、人工确认），要看时才查的进 project/daily（按需读），通用知识进 memory/user。
3. **所有坑都指向同一件事**：边界要清楚。协议边界收在 `_call` 一个函数里，编码边界收在 `--file` 一个参数上，职责边界收在【消息来源】一行文本里。边界清楚了，出问题就好定位。

---

*文档基于 `E:\feishu-bot` master 分支（`2eecfa3`）实际代码编写。搭建步骤见同目录《搭建手册-从零复刻.md》。*
