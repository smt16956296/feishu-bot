# -*- coding: utf-8 -*-
"""第 11 条：调试传感器开报错存图后服务端未存 DLP 全量图片"""
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


ts = int(datetime(2026, 11, 19, 19, 20).timestamp() * 1000)
fields = {
    "问题描述": ("调试传感器：开启「报错存图」后，服务端没有存 DLP 传感器的全量图片"
                "（调试模式下应落全量图到 debug 目录）"),
    "版本": "2.3.13",
    "提出人": "沈梦婷",
    "处理人": [{"id": XJ}],
    "状态": "待处理",
    "提出日期": ts,
    "备注": "11-19 群内提出；与第 6 条（调试模式与报错存图开关冗余）相关",
}
d = call("POST", B + "/records?user_id_type=open_id", {"fields": fields})
print("入表:", d.get("code"), d.get("msg"))

r = call("GET", B + "/records?page_size=50&user_id_type=open_id")
print("total =", r.get("data", {}).get("total"))
for it in r.get("data", {}).get("items", []):
    fl = it["fields"]
    who = (fl.get("处理人") or [{}])[0].get("name", "-")
    print(" ", str(fl.get("问题描述"))[:22].replace("\n", " "), "|", fl.get("状态"), "|", who)
