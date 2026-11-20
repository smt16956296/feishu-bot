# -*- coding: utf-8 -*-
"""拉全部用例，检查名称自明性"""
import json
import sys
import urllib.request

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

B = "/bitable/v1/apps/<APP_TOKEN_JOINT>/tables/<TABLE_ID_CASES>"


def call(method, path, body=None):
    import urllib.error
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


rows, token = [], None
while True:
    url = B + "/records?page_size=100" + (("&page_token=" + token) if token else "")
    d = call("GET", url)
    data = d.get("data", {})
    rows.extend(data.get("items", []))
    if not data.get("has_more"):
        break
    token = data.get("page_token")

print("共", len(rows), "条")
out = []
for it in rows:
    f = it.get("fields", {})
    out.append({"rid": it["record_id"],
                "name": f.get("测试用例", ""),
                "module": f.get("模块", ""),
                "feature": f.get("功能块", ""),
                "cat": f.get("分类", ""),
                "type": f.get("类型", ""),
                "extra": f.get("预期/补充", "")})

with open(r"E:\feishu-bot\data\cases_dump.json", "w", encoding="utf-8") as fp:
    json.dump(out, fp, ensure_ascii=False, indent=1)
print("dump 完成 data/cases_dump.json")

# 抽样打印不同类型
import itertools
for t in ("主流程", "场景"):
    print("\n== 类型=%s 抽样 ==" % t)
    n = 0
    for r in (x for x in out if x["type"] == t):
        print(" [%s|%s|%s] %s || 补充:%s" % (r["module"], r["feature"] or "", r["cat"] or "",
                                              r["name"] or "", (r["extra"] or "")[:30]))
        n += 1
        if n >= 8:
            break
print("\n== 其他类型 ==")
for r in (x for x in out if x["type"] not in ("主流程", "场景")):
    print(" [%s|%s|%s] %s" % (r["module"], r["feature"], r["cat"], r["name"][:60]))
