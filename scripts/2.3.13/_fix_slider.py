# -*- coding: utf-8 -*-
"""滑动条问题也修复了：状态→已解决"""
import json
import sys
import urllib.request

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

B = "/bitable/v1/apps/<APP_TOKEN_ISSUES>/tables/<TABLE_ID_ISSUES>"

req = urllib.request.Request(API + B + "/records?page_size=20",
                             headers={"Authorization": "Bearer " + _token()})
with urllib.request.urlopen(req, timeout=30) as r:
    d = json.loads(r.read())

for it in d.get("data", {}).get("items", []):
    fl = it.get("fields", {})
    if fl.get("状态") == "待处理" and "滑动条" in str(fl.get("问题描述", "")):
        req = urllib.request.Request(
            API + B + "/records/" + it["record_id"],
            data=json.dumps({"fields": {"状态": "已解决",
                                        "备注": "11-19 群内刘星君反馈已修复（含滑动条）"}}).encode(),
            method="PUT",
            headers={"Content-Type": "application/json; charset=utf-8",
                     "Authorization": "Bearer " + _token()})
        with urllib.request.urlopen(req, timeout=30) as r:
            print("滑动条→已解决:", json.loads(r.read()).get("code"))

# 验证
req = urllib.request.Request(API + B + "/records?page_size=20",
                             headers={"Authorization": "Bearer " + _token()})
with urllib.request.urlopen(req, timeout=30) as r:
    d = json.loads(r.read())
for it in d.get("data", {}).get("items", []):
    fl = it.get("fields", {})
    print("  -", str(fl.get("问题描述"))[:22].replace("\n", " "), "|", fl.get("状态"))
