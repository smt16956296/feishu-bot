# 飞书现场待办机器人

基于个人飞书自建应用 + 长连接(WebSocket) 的消息统计机器人。

## 功能（第一版）

1. 接收**与机器人的单聊消息**（你在现场群看到待办/遗漏，转发或粘贴到机器人单聊）
2. 按关键词识别待办事项，存到 `data/messages/`
3. 每天定时推送**消息统计日报**到你的个人会话

## 目录结构

```
E:\feishu-bot\
├── .env                # 敏感配置（App ID/Secret），不进 git
├── .env.example        # 配置模板
├── requirements.txt    # Python 依赖
├── config.py           # 配置加载
├── classifier.py       # 待办关键词识别
├── storage.py          # 消息流水存储
├── reporter.py         # 日报生成
├── bot.py              # 主程序（长连接收消息）
├── data\               # 运行时数据（消息流水/汇总）
└── logs\               # 运行日志
```

## 安装与运行

```bat
rem 1. 准备 .env（从 .env.example 复制并填写）
copy .env.example .env

rem 2. 安装依赖（用 Python3，本机 py -3）
py -3 -m pip install -r requirements.txt

rem 3. 启动机器人
py -3 bot.py
```

## .env 配置说明

```ini
FEISHU_APP_ID=cli_xxxx              # 飞书开放平台 -> 应用 -> 凭证与基础信息
FEISHU_APP_SECRET=xxxx              # 应用凭证
FEISHU_BOT_NAME=现场待办助手        # 机器人名称（日志用）
TODO_KEYWORDS=待办,记得,需要,遗漏   # 待办关键词（逗号分隔）
DAILY_REPORT_TIME=18:00             # 日报推送时间（24小时制）
```

## 飞书开放平台需完成

1. 创建企业自建应用，**开启机器人能力**
2. 申请权限：`im:message`（读消息）、`im:message:send_as_bot`（发消息）、`contact:user.base:readonly`（查用户姓名，可选）
3. **发布上线**，并创建应用版本
4. 把机器人**添加到你的单聊**（或需要监听的会话）

> 本机 `python` 默认指向 2.7，务必用 `py -3` 运行。

## 群聊日报（软算群自动总结）⭐

每天定时汇总指定飞书群的聊天记录，生成智能日报并私聊推送给管理员。

**配置**（`data/summary_targets.json`，缺省已配软算群）：
```json
[{"chat_id": "oc_90da6b0826ebe9967c62c5a8769e9453", "name": "BF2.0 - 软算算法沟通"}]
```

**推送时间**：`.env` 的 `GROUP_SUMMARY_TIME`（缺省 `18:30`）

**手动执行**：
```bat
py -3 daily_summary.py                    rem 总结今天并推送
py -3 daily_summary.py --day 2026-10-19   rem 指定日期
py -3 daily_summary.py --dry-run          rem 只打印不推送
```

**总结内容**：三段式 ——【今日要点】【待办与跟进】【风险与阻塞】，由 DSH LLM 生成。
LLM 失败时该群跳过并记日志（本地规则摘要降级已于 2026-10-22 按用户要求停用，
收割超时同日从 240 秒提到 600 秒）。

**关键设计**：
- 用**独立的 DSH 总结会话**（`data/summary_session_id.txt`），不占用交互会话，
  否则会与用户对话抢占导致等待超时。
- 姓名解析走 `name_map.py`：从群消息的 @提及 中自动积累 open_id→姓名映射
  （通讯录 API 需要 contact 权限，当前未开通），映射存 `data/name_map.json`。
  从未被 @ 过的人显示为 `成员_xxxxxx`。

## 待办（后续）

- [ ] 日报推送目标（管理员 open_id）配置
- [ ] 支持图片/文件消息
- [ ] 现场问题上报登记结构
- [ ] 关键词规则调优

## 后台运行与开机自启

### 方式一：立即后台运行（无窗口）

双击 `start_hidden.vbs`，机器人会在后台静默启动，**不会出现黑色控制台窗口**。

### 方式二：设置开机自启

双击运行 `install_autostart.bat`，它会把启动快捷方式放进 Windows 启动目录。
之后每次开机，机器人都会自动在后台运行。

### 关闭机器人

后台运行时没有窗口，需通过任务管理器结束 `pythonw.exe` 进程，
或在 CMD 中执行：

```bat
taskkill /F /IM pythonw.exe
```

### 查看运行状态

无窗口运行时日志仍在写，查看方式：

```bat
type E:\feishu-bot\logs\bot.log
```

或实时跟踪最后 20 行：

```bat
powershell -Command "Get-Content E:\feishu-bot\logs\bot.log -Tail 20 -Wait"
```
