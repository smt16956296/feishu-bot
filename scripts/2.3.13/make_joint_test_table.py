# -*- coding: utf-8 -*-
"""建「迭代二前后端联调测试进展记录」表：14 功能点 + 客户端/服务端测试列 + 关联问题"""
import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

ISSUES_TABLE = "<TABLE_ID_ISSUES>"  # 问题记录表（link 目标）
XJ = "ou_<OPEN_ID>"
SMT = "ou_<OPEN_ID>"

FEATURES = [
    "新增调试传感器功能，支持DLP传感器调试模式采图与报错存图",
    "新增「历史数据均值请求」信号处理，支持机器人按车型编号、结果组编号请求历史数据均值",
    "新增错误码标准化与报错优化，统一错误码分级与提示口径",
    "新增offset固定补偿值调整功能，支持配置测点期望变化量与权重并计算offset固定补偿值",
    "引导、电子垫片及通用电子垫片算法新增「降级默认值」配置，支持固定值或近N台车均值兜底",
    "零位计算补充零位失败记录保存规则与模板优化跳转",
    "查询引导结果补充查询条件区展开/折叠等交互优化说明",
    "技术规格补充软件启动响应时间指标（36个暗特征模板小于20s）与日志打印要求",
    "间隙面差调整引导算法计算改为按策略组跳过测点异常，不再因单个测点异常导致整个算法不计算（现场需求）",
    "无需保存传感器配置即可读取并显示传感器内参",
    "零件配置删除3D传感器的不投3D图描述",
    "批量模板匹配界面优化",
    "框选ROI时清空深度图片",
    "零件配置图片节点，点击3D采图时，2D、3D同时采",
]

OPTS = [{"name": "待测试"}, {"name": "未通过"}, {"name": "通过"}]


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


# 1. 建 app
d = call("POST", "/bitable/v1/apps", {"name": "迭代二前后端联调测试进展记录"})
app_token = d["data"]["app"]["app_token"]
table_id = d["data"]["app"]["default_table_id"]
print("app:", app_token, "table:", table_id)
B = "/bitable/v1/apps/%s/tables/%s" % (app_token, table_id)

# 2. 表名
call("PATCH", B, {"name": "联调测试进展"})

# 3. 字段改造
f = call("GET", B + "/fields?page_size=50")
fmap = {it["field_name"]: it["field_id"] for it in f.get("data", {}).get("items", [])}
print("默认字段:", list(fmap))
call("PUT", B + "/fields/" + fmap["文本"],
     {"field_name": "功能点", "type": 1,
      "description": {"text": "迭代二 14 个功能点，开发机自测试（算法相关用 196 工控机）"}})
call("PUT", B + "/fields/" + fmap["单选"],
     {"field_name": "客户端界面", "type": 3, "property": {"options": OPTS}})
call("POST", B + "/fields",
     {"field_name": "服务端调用", "type": 3, "property": {"options": OPTS}})
call("PUT", B + "/fields/" + fmap["日期"],
     {"field_name": "测试日期", "type": 5, "property": {"date_formatter": "yyyy/MM/dd"}})
call("PUT", B + "/fields/" + fmap["附件"], {"field_name": "测试截图/日志", "type": 17})
call("POST", B + "/fields",
     {"field_name": "备注", "type": 1,
      "description": {"text": "有问题写现象，并在「关联问题」里挂上问题记录表的条目"}})
d = call("POST", B + "/fields",
         {"field_name": "关联问题", "type": 18,
          "property": {"table_id": ISSUES_TABLE}})
print("link字段:", d.get("code"), str(d.get("msg"))[:80])

# 4. 清掉默认空行（先读回看有几条）
r = call("GET", B + "/records?page_size=50")
empty = [it["record_id"] for it in r.get("data", {}).get("items", [])
         if not any(v for v in it.get("fields", {}).values())]
if empty:
    d = call("POST", B + "/records/batch_delete", {"records": empty})
    print("清空行 %d 条:" % len(empty), d.get("code"))

# 5. 插入 14 个功能点
for i, feat in enumerate(FEATURES, 1):
    d = call("POST", B + "/records",
             {"fields": {"功能点": "%d. %s" % (i, feat),
                          "客户端界面": "待测试", "服务端调用": "待测试"}})
    if d.get("code") != 0:
        print("FAIL #%d" % i, d.get("msg"))
print("功能点插入完成")

# 6. 验证
r = call("GET", B + "/records?page_size=50")
print("total =", r.get("data", {}).get("total"))

# 7. 公开为组织内可编辑（群里的人点链接能填）
d = call("PUT", "/drive/v1/permissions/%s/public?type=bitable" % app_token,
         {"link_share_entity": "tenant_editable", "external_access": False})
print("公开权限:", d.get("code"), str(d.get("msg"))[:60])
if d.get("code") != 0:
    # fallback：加协作者
    for who in (SMT, XJ):
        d = call("POST", "/drive/v1/permissions/%s/members?type=bitable&need_notification=false" % app_token,
                 {"member_type": "openid", "member_id": who, "perm": "full_access"})
        print("协作者", who[:10], "->", d.get("code"))

print("\nAPP_TOKEN:", app_token)
print("URL: https://rsag16mz9z.feishu.cn/base/" + app_token)
