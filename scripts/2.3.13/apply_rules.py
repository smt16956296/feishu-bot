# -*- coding: utf-8 -*-
"""按新规则改造：加处理人列+字段说明、拆分混合记录、建录入规则表"""
import json
import sys
import urllib.request
from datetime import datetime

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

APP_TOKEN = "<APP_TOKEN_ISSUES>"
TABLE_ID = "<TABLE_ID_ISSUES>"
OLD_REC = "reczz28bMRH0GDWP"   # 要拆分的混合记录
FILE_TOKEN = "IxZgbPPpfobCURxxTdAcFSringe"

B = "/bitable/v1/apps/%s/tables/%s" % (APP_TOKEN, TABLE_ID)


def call(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Authorization": "Bearer " + _token()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def step(name, *args):
    try:
        d = call(*args)
        print(("OK  " if d.get("code") == 0 else "FAIL") + " " + name +
              " -> " + str(d.get("code")) + " " + str(d.get("msg", ""))[:60])
        return d
    except Exception as e:
        print("FAIL " + name + " -> " + str(e)[:120])
        return None


# ---- 1. 字段：description + 新增处理人 ----
# 先取字段 id
f = call("GET", B + "/fields?page_size=50")
fmap = {it["field_name"]: it["field_id"] for it in f.get("data", {}).get("items", [])}
print("当前字段:", list(fmap))

step("问题描述加说明", "PUT", B + "/fields/" + fmap["问题描述"],
     {"field_name": "问题描述", "type": 1,
      "description": {"text": "同一个界面的多个问题分别建条目，一条只写一个问题，不要混在一起"}})
step("新增 处理人(带说明)", "POST", B + "/fields",
     {"field_name": "处理人", "type": 1,
      "description": {"text": "谁负责修就填谁（如：刘星君）"}})

# ---- 2. 拆分记录：1 条变 3 条 ----
ts = int(datetime(2026, 11, 18, 14, 40).timestamp() * 1000)
base = {"提出人": "沈梦婷", "状态": "待处理", "提出日期": ts, "处理人": "刘星君"}
splits = [
    {"问题描述": "调试传感器页 3D ROI：需增加一条浅蓝色背景（Figma 设计稿有，界面未实现）",
     "备注": "Figma 截图见附件"},
    {"问题描述": "调试传感器页 3D ROI：XY Enable 缩进不对——3D ROI 与其下参数是上下级包含关系，层级缩进要体现",
     "备注": "Figma 截图见附件"},
    {"问题描述": "调试传感器页 3D ROI：X/Y 轴范围标签顺序应为左 Min、右 Max（现状左右颠倒）",
     "备注": "Figma 截图见附件"},
]
new_ids = []
for i, s in enumerate(splits):
    fields = dict(base)
    fields.update(s)
    if i == 0:
        fields["截图/附件"] = [{"file_token": FILE_TOKEN}]
    d = step("插入拆分记录#%d" % (i + 1), "POST", B + "/records", {"fields": fields})
    if d and d.get("code") == 0:
        new_ids.append(d["data"]["record"]["record_id"])

# 第 2、3 条也试着挂同一附件
if len(new_ids) == 3:
    for rid in new_ids[1:]:
        d = call("PUT", B + "/records/" + rid,
                 {"fields": {"截图/附件": [{"file_token": FILE_TOKEN}]}})
        print("附件挂载", rid, "->", d.get("code"))

# ---- 3. 删除旧的混合记录 ----
step("删除混合旧记录", "POST", B + "/records/batch_delete", {"records": [OLD_REC]})

# ---- 4. 建「录入规则」表 ----
d = step("新建录入规则表", "POST", "/bitable/v1/apps/%s/tables" % APP_TOKEN,
         {"table": {"name": "录入规则",
                    "fields": [{"field_name": "规则", "type": 1},
                               {"field_name": "说明", "type": 1}]}})
rules_tid = None
if d and d.get("code") == 0:
    rules_tid = d["data"]["table_id"]
    RB = "/bitable/v1/apps/%s/tables/%s" % (APP_TOKEN, rules_tid)
    rules = [
        {"规则": "一题一条", "说明": "同一个界面的多个问题，分别建条目，不要混在一条里"},
        {"规则": "处理人", "说明": "谁负责修就填谁（如：刘星君），在群里指定时同步更新"},
        {"规则": "问题描述", "说明": "写清界面/模块名 + 具体问题，能从描述定位到位置"},
        {"规则": "截图/附件", "说明": "有设计稿或现场截图就挂附件列，便于比对"},
        {"规则": "状态流转", "说明": "待处理 → 处理中 → 已解决 / 暂不处理"},
    ]
    for i, r in enumerate(rules):
        step("规则#%d %s" % (i + 1, r["规则"]), "POST", RB + "/records", {"fields": r})

# ---- 5. 验证 ----
d = call("GET", B + "/records?page_size=20")
print("\n问题记录 total =", d.get("data", {}).get("total"))
for it in d.get("data", {}).get("items", []):
    fl = it.get("fields", {})
    print("  -", str(fl.get("问题描述"))[:28].replace("\n", " "),
          "| 处理人:", fl.get("处理人"), "| 状态:", fl.get("状态"))
