# -*- coding: utf-8 -*-
"""第 15 条：算法计算失败错误码解决措施提示词细化"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

B = "/bitable/v1/apps/<APP_TOKEN_ISSUES>/tables/<TABLE_ID_ISSUES>"
XJ = "ou_<OPEN_ID>"


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


ts = int(datetime(2026, 11, 20, 10, 5).timestamp() * 1000)
d = call("POST", B + "/records?user_id_type=open_id", {"fields": {
    "问题描述": ("客户端提示词细化：「算法计算失败」错误码对应的解决措施提示词需要细化修改"
                "（当前提示对用户定位/解决问题帮助不足）"),
    "版本": "2.3.13",
    "提出人": "刘星君",
    "处理人": [{"id": XJ}],
    "状态": "待处理",
    "提出日期": ts,
    "备注": "11-20 群内提出；与第 10 条（零位计算失败双警告，算法计算失败提示）相关",
}})
print("入表:", d.get("code"), d.get("msg"))

# DONE 表情
req = urllib.request.Request(
    API + "/im/v1/messages/om_x100b60cef9057ca4b374e1e11c75f9a/reactions",
    data=json.dumps({"reaction_type": {"emoji_type": "DONE"}}).encode(), method="POST",
    headers={"Content-Type": "application/json; charset=utf-8",
             "Authorization": "Bearer " + _token()})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        print("reaction:", json.loads(r.read()).get("code"))
except urllib.error.HTTPError as e:
    print("reaction HTTP", e.code)

r = call("GET", B + "/records?page_size=50&user_id_type=open_id")
print("total =", r.get("data", {}).get("total"))
