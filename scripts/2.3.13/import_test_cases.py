# -*- coding: utf-8 -*-
"""在联调 app 内建「测试用例」表，导入 xmind 全部测试用例（batch_create）"""
import json
import sys
import zipfile
import urllib.error
import urllib.request

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

APP = "<APP_TOKEN_JOINT>"   # 迭代二联调 app
XMIND = r"D:\ShareCache\颜文轩\BF易用性提升\测试方案\【BF测量能力与易用性提升产品变更】BF测量能力与易用性提升产品变更-迭代集成测试点梳理.xmind"

OPTS = [{"name": "待测试"}, {"name": "未通过"}, {"name": "通过"}]


def call(method, path, body=None):
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


# ---- 1. 解析 xmind ----
z = zipfile.ZipFile(XMIND)
data = json.loads(z.read("content.json"))
root = data[0]["rootTopic"]


def walk(topic, path=()):
    title = topic.get("title", "").strip()
    children = topic.get("children", {}).get("attached", [])
    if not children:
        return [(path, title)]
    out = []
    for c in children:
        out.extend(walk(c, path + (title,)))
    return out


cases = []   # (模块, 功能块, 分类, 用例名, 补充)
skipped = 0
for path, leaf in walk(root):
    # path[0]=根, path[1]=模块, path[2]=功能块, path[3:]=分类层级
    if not leaf:
        continue
    if leaf.startswith(("改动点", "策略")):
        skipped += 1
        continue
    module = path[1] if len(path) > 1 else ""
    feature = path[2] if len(path) > 2 else ""
    cat = " / ".join(p for p in path[3:] if p)
    name, extra = leaf, ""
    if " >> " in leaf:
        name, extra = leaf.split(" >> ", 1)
    typ = "主流程" if name.startswith("主流程") else ("场景" if name.startswith("场景") else "用例")
    name = name.split("：", 1)[1] if "：" in name else name
    cases.append((module, feature, cat, name, extra, typ))

print("用例数:", len(cases), " 跳过说明节点:", skipped)

# ---- 2. 建表 ----
d = call("POST", "/bitable/v1/apps/%s/tables" % APP, {"table": {
    "name": "测试用例",
    "fields": [
        {"field_name": "测试用例", "type": 1,
         "description": {"text": "迭代集成测试用例（源：颜文轩 xmind 测试点梳理）"}},
        {"field_name": "模块", "type": 3, "property": {"options": [
            {"name": m} for m in dict.fromkeys(c[0] for c in cases)]}},
        {"field_name": "功能块", "type": 1},
        {"field_name": "分类", "type": 1},
        {"field_name": "类型", "type": 3, "property": {"options": [
            {"name": "主流程"}, {"name": "场景"}]}},
        {"field_name": "预期/补充", "type": 1},
        {"field_name": "客户端界面", "type": 3, "property": {"options": OPTS}},
        {"field_name": "服务端调用", "type": 3, "property": {"options": OPTS}},
        {"field_name": "测试日期", "type": 5, "property": {"date_formatter": "yyyy/MM/dd"}},
        {"field_name": "备注", "type": 1},
        {"field_name": "关联问题", "type": 15,
         "description": {"text": "有问题贴「BestFit 开发问题记录」对应条目链接"}},
    ]}})
print("建表:", d.get("code"), d.get("msg"))
tid = d["data"]["table_id"]
B = "/bitable/v1/apps/%s/tables/%s" % (APP, tid)

# ---- 3. 批量插入（每批 100）----
recs = [{"fields": {
    "测试用例": c[3] + ("（%s）" % c[4] if c[4] else ""),
    "模块": c[0], "功能块": c[1], "分类": c[2], "类型": c[5],
    "预期/补充": c[4] or "",
    "客户端界面": "待测试", "服务端调用": "待测试",
}} for c in cases]

ok = 0
for i in range(0, len(recs), 100):
    d = call("POST", B + "/records/batch_create", {"records": recs[i:i + 100]})
    ok += len(recs[i:i + 100]) if d.get("code") == 0 else 0
    if d.get("code") != 0:
        print("批次 %d FAIL:" % i, d.get("code"), str(d.get("msg"))[:100])
print("插入成功:", ok, "/", len(recs))

# ---- 4. 验证 ----
d = call("GET", B + "/records?page_size=5")
print("验证 total =", d.get("data", {}).get("total"))
print("表:", tid)
