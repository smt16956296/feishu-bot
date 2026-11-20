# -*- coding: utf-8 -*-
"""整改测试用例名称：错位归位 + 下划线清理 + 类型统一"""
import json
import sys
import urllib.request

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

B = "/bitable/v1/apps/<APP_TOKEN_JOINT>/tables/<TABLE_ID_CASES>"

with open(r"E:\feishu-bot\data\cases_dump.json", encoding="utf-8") as fp:
    rows = json.load(fp)


def call(method, path, body=None):
    import urllib.error
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Authorization": "Bearer " + _token()})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"code": -1, "msg": "HTTP %s" % e.code}


updates, fixed_mis, fixed_us = [], 0, 0
for r in rows:
    name, cat, extra, typ = r["name"] or "", r["cat"] or "", r["extra"] or "", r["type"]
    new_fields = {}

    # A. 错位修复：分类列末段是真正的用例名
    segs = [s for s in cat.split(" / ") if s]
    if segs and (segs[-1].startswith("主流程：") or segs[-1].startswith("场景：")):
        last = segs[-1]
        t = "主流程" if last.startswith("主流程") else "场景"
        real = last.split("：", 1)[1]
        new_fields["测试用例"] = real
        new_fields["预期/补充"] = name          # 原主键(变体/预期值)归补充
        new_fields["分类"] = " / ".join(segs[:-1])
        new_fields["类型"] = t
        fixed_mis += 1
    else:
        # B. 下划线清理
        n = name
        if n.startswith("自动引导报错_"):
            n = "引导报错：" + n[len("自动引导报错_"):].replace("_", "，")
        elif n.startswith("自动引导_"):
            n = n[len("自动引导_"):].replace("_", "，")
        if n != name:
            new_fields["测试用例"] = n
            fixed_us += 1
        # C. 类型缺失 → 场景
        if typ not in ("主流程", "场景"):
            new_fields["类型"] = "场景"
        # D. 分类里的自动引导_ 前缀
        if "自动引导_" in cat:
            new_fields["分类"] = cat.replace("自动引导_", "")
        # 错位补充清理：补充列若与用例名重复则置空
        if extra and extra in (new_fields.get("测试用例", name)):
            new_fields["预期/补充"] = ""

    if new_fields:
        updates.append({"record_id": r["rid"], "fields": new_fields})

print("需更新:", len(updates), "（错位 %d / 下划线 %d）" % (fixed_mis, fixed_us))

ok = 0
for i in range(0, len(updates), 100):
    d = call("POST", B + "/records/batch_update", {"records": updates[i:i + 100]})
    ok += len(updates[i:i + 100]) if d.get("code") == 0 else 0
    if d.get("code") != 0:
        print("批次 FAIL:", d.get("code"), str(d.get("msg"))[:120])
print("更新成功:", ok, "/", len(updates))

# 抽样验证
d = call("GET", B + "/records?page_size=100")
items = d.get("data", {}).get("items", [])
bad = [it for it in items
       if (it["fields"].get("测试用例") or "") in ("", "BF", "ISV_IC2", "默认展开")
       or "自动引导_" in (it["fields"].get("测试用例") or "")]
print("剩余可疑条数(前100):", len(bad))
for it in items[:3]:
    f = it["fields"]
    print("  样例:", f.get("测试用例"), "|", f.get("类型"), "|", f.get("预期/补充"), "|", f.get("分类"))
