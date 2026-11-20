# -*- coding: utf-8 -*-
"""跨版本改造：app 改名 + 版本字段 + 回填 + 规则更新"""
import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

APP_TOKEN = "<APP_TOKEN_ISSUES>"
TABLE_ID = "<TABLE_ID_ISSUES>"
B = "/bitable/v1/apps/%s/tables/%s" % (APP_TOKEN, TABLE_ID)


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


# 1. app 改名（去版本号，变成长期问题库）
d = call("PATCH", "/bitable/v1/apps/%s" % APP_TOKEN, {"name": "BestFit 开发问题记录"})
print("app改名:", d.get("code"), d.get("msg"))

# 2. 版本字段（单选）
d = call("POST", B + "/fields", {
    "field_name": "版本", "type": 3,
    "property": {"options": [{"name": "2.3.11"}, {"name": "2.3.12"},
                             {"name": "2.3.13"}, {"name": "2.3.14"}]},
    "description": {"text": "问题所属开发版本，如 2.3.13；新版本号直接填，自动建选项"}})
print("版本字段:", d.get("code"), d.get("msg"))

# 3. 现有记录回填 2.3.13
r = call("GET", B + "/records?page_size=50")
n = 0
for it in r.get("data", {}).get("items", []):
    d = call("PUT", B + "/records/" + it["record_id"], {"fields": {"版本": "2.3.13"}})
    if d.get("code") == 0:
        n += 1
print("回填版本: %d 条" % n)

# 4. 录入规则表加「版本」规则
r = call("GET", "/bitable/v1/apps/%s/tables?page_size=20" % APP_TOKEN)
rules_tid = next((t["table_id"] for t in r.get("data", {}).get("items", [])
                  if t["name"] == "录入规则"), None)
if rules_tid:
    RB = "/bitable/v1/apps/%s/tables/%s" % (APP_TOKEN, rules_tid)
    d = call("POST", RB + "/records", {
        "fields": {"规则": "版本", "说明": "每条问题标所属版本（如 2.3.13），跨版本统计靠这列；新版本号直接填会自动建选项"}})
    print("规则+版本:", d.get("code"), d.get("msg"))

# 5. 验证
r = call("GET", B + "/records?page_size=50")
for it in r.get("data", {}).get("items", []):
    fl = it.get("fields", {})
    print("  -", str(fl.get("问题描述"))[:20].replace("\n", " "), "|", fl.get("版本"), "|", fl.get("状态"))
