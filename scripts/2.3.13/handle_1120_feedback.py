# -*- coding: utf-8 -*-
"""处理刘星君 11-20 反馈：撤销第13条、第14条标已解决"""
import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

B = "/bitable/v1/apps/<APP_TOKEN_ISSUES>/tables/<TABLE_ID_ISSUES>"


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


r = call("GET", B + "/records?page_size=50&user_id_type=open_id")
del_id, fix_id = None, None
for it in r.get("data", {}).get("items", []):
    desc = str(it["fields"].get("问题描述", ""))
    if "传给后端的值应该是界面上的补偿值" in desc:
        del_id = it["record_id"]
    if "计算完点击「应用」后" in desc:
        fix_id = it["record_id"]

# 第13条：撤销需求（维持按应用后的补偿值计算），删除记录
if del_id:
    d = call("POST", B + "/records/batch_delete", {"records": [del_id]})
    print("第13条删除:", d.get("code"), d.get("msg"))
else:
    print("第13条未找到")

# 第14条：标已解决 + 备注
if fix_id:
    d = call("PUT", B + "/records/" + fix_id, {"fields": {
        "状态": "已解决",
        "备注": ("11-20 刘星君修复：所有测点期望变化量均为 0 时，Tip 提示"
                "「所有测点的期望变化量均为0，无需计算调整」且不进行实际计算")}})
    print("第14条已解决:", d.get("code"), d.get("msg"))

r = call("GET", B + "/records?page_size=50&user_id_type=open_id")
print("total =", r.get("data", {}).get("total"))
for it in r.get("data", {}).get("items", []):
    fl = it["fields"]
    who = (fl.get("处理人") or [{}])[0].get("name", "-")
    print(" ", str(fl.get("问题描述"))[:22].replace("\n", " "), "|", fl.get("状态"), "|", who)
