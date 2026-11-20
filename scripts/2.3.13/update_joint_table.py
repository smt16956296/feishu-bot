# -*- coding: utf-8 -*-
"""联调测试进展表：加「测试中/修改中」选项 + 「测试人」列"""
import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

APP = "<APP_TOKEN_JOINT>"
TID = "<TABLE_ID_JOINT>"   # 联调测试进展表
B = "/bitable/v1/apps/%s/tables/%s" % (APP, TID)

NEW_OPTS = [{"name": "待测试"}, {"name": "测试中"}, {"name": "未通过"},
            {"name": "修改中"}, {"name": "通过"}]


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


# 1. 现有字段 + 记录（改选项前先存旧值，改完回填）
f = call("GET", B + "/fields?page_size=50")
fmap = {it["field_name"]: it["field_id"] for it in f.get("data", {}).get("items", [])}
print("现有字段:", list(fmap))

recs = []
token = None
while True:
    d = call("GET", B + "/records?page_size=100" + (("&page_token=" + token) if token else ""))
    data = d.get("data", {})
    recs.extend(data.get("items", []))
    if not data.get("has_more"):
        break
    token = data.get("page_token")
print("记录数:", len(recs))

old_vals = [(it["record_id"], it["fields"].get("客户端界面"), it["fields"].get("服务端调用"))
            for it in recs]

# 2. 改两个单选字段的选项（加测试中/修改中）
for fname in ("客户端界面", "服务端调用"):
    d = call("PUT", B + "/fields/" + fmap[fname],
             {"field_name": fname, "type": 3, "property": {"options": NEW_OPTS}})
    print("%s 选项更新:" % fname, d.get("code"), d.get("msg"))

# 3. 回填旧值（改选项会重建选项导致值丢失）
ups = []
for rid, cli, srv in old_vals:
    fields = {}
    if cli:
        fields["客户端界面"] = cli
    if srv:
        fields["服务端调用"] = srv
    if not fields:
        continue
    # 旧值若是「待测试」等仍存在则保留；不存在则置待测试
    valid = {o["name"] for o in NEW_OPTS}
    fields = {k: (v if v in valid else "待测试") for k, v in fields.items()}
    ups.append({"record_id": rid, "fields": fields})
if ups:
    d = call("POST", B + "/records/batch_update", {"records": ups})
    print("回填状态:", d.get("code"), len(ups), "条")

# 4. 新增「测试人」列（人员类型）
d = call("POST", B + "/fields", {
    "field_name": "测试人", "type": 11,
    "description": {"text": "谁做的这项测试就填谁（人员字段，可搜索选择）"}})
print("测试人字段:", d.get("code"), d.get("msg"))

# 5. 验证
f = call("GET", B + "/fields?page_size=50")
print("最终字段:", [it["field_name"] for it in f.get("data", {}).get("items", [])])
r = call("GET", B + "/records?page_size=100&user_id_type=open_id")
print("记录数:", r.get("data", {}).get("total"))
for it in r.get("data", {}).get("items", [])[:3]:
    fl = it["fields"]
    print("  ", str(fl.get("功能点"))[:24], "| 客户端:", fl.get("客户端界面"),
          "| 服务端:", fl.get("服务端调用"))
