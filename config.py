"""配置加载：从 .env 读取应用凭证与规则参数。

使用 python-dotenv 加载本地 .env 文件，不进入任何 git 仓库。
"""
import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
BOT_NAME = os.getenv("FEISHU_BOT_NAME", "现场待办助手")

# 待办关键词列表
TODO_KEYWORDS = [
    k.strip()
    for k in os.getenv(
        "TODO_KEYWORDS",
        "待办,记得,需要,遗漏,未处理,别忘了,提醒,跟进,确认,验收",
    ).split(",")
    if k.strip()
]

# 日报推送时间（HH:MM）
DAILY_REPORT_TIME = os.getenv("DAILY_REPORT_TIME", "18:00")

# 群聊总结推送时间（HH:MM）
GROUP_SUMMARY_TIME = os.getenv("GROUP_SUMMARY_TIME", "18:30")

# 机器人自己的 open_id（用于判断群里是否 @ 了机器人）
# 留空时程序启动会自动查询并写入 .env
BOT_OPEN_ID = os.getenv("FEISHU_BOT_OPEN_ID", "")

# 日报推送目标 open_id（缺省用 BOT_ADMIN_OPEN_ID）
REPORT_TARGET_OPEN_ID = os.getenv("FEISHU_REPORT_TARGET", "")

DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
