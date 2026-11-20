# -*- coding: utf-8 -*-
"""补录 21:06 和 21:07 两条消息"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

B = "/bitable/v1/apps/<APP_TOKEN_ISSUES>/tables/<TABLE_ID_ISSUES>"
XJ = "ou_<OPEN_ID>"
SMT = "ou_<OPEN_ID>"


def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Authorization": "Bearer " + _token()})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"code": -1, "msg": "HTTP %s" % e.code}


# 第 13 条：OFFSET 补偿值计算传值问题（刘星君 21:06）
ts1 = int(datetime(2026, 11, 19, 21, 6).timestamp() * 1000)
d = call("POST", B + "/records?user_id_type=open_id", {"fields": {
    "问题描述": ("OFFSET 固定补偿值：界面上点击计算时，传给后端的值应该是界面上的补偿值"
                "（即使没有应用/保存），而不是算法配置中的值"),
    "版本": "2.3.13",
    "提出人": "刘星君",
    "处理人": [{"id": XJ}],
    "状态": "待处理",
    "提出日期": ts1,
    "备注": "11-19 21:06 群内提出",
}})
print("第13条:", d.get("code"), d.get("msg"))

# 第 14 条：OFFSET 计算完点击应用后应关闭弹窗并 TIP 提示（刘星君 21:06 续）
ts2 = int(datetime(2026, 11, 19, 21, 6).timestamp() * 1000) + 60000
d = call("POST", B + "/records?user_id_type=open_id", {"fields": {
    "问题描述": ("OFFSET 固定补偿值：计算完点击「应用」后，应该关闭弹窗并 TIP 提示"
                "「OFFSET 固定补偿值」已更新"),
    "版本": "2.3.13",
    "提出人": "刘星君",
    "处理人": [{"id": XJ}],
    "状态": "待处理",
    "提出日期": ts2,
    "备注": "11-19 21:06 群内提出（与上一条同一功能的交互问题）",
}})
print("第14条:", d.get("code"), d.get("msg"))

r = call("GET", B + "/records?page_size=50&user_id_type=open_id")
print("total =", r.get("data", {}).get("total"))
for it in r.get("data", {}).get("items", [])[-3:]:
    fl = it["fields"]
    who = (fl.get("处理人") or [{}])[0].get("name", "-")
    print(" ", str(fl.get("问题描述"))[:26].replace("\n", " "), "|", fl.get("状态"), "|", who)
