# -*- coding: utf-8 -*-
"""初始化新建的 2.3.13 问题记录多维表格：表名+字段结构+第1条记录+加沈梦婷为协作者"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

APP_TOKEN = "<APP_TOKEN_ISSUES>"
TABLE_ID = "<TABLE_ID_ISSUES>"
SHEN_OPEN_ID = "ou_<OPEN_ID>"


def call(method, path, body=None):
    url = API + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Authorization": "Bearer " + _token()},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def step(name, method, path, body=None):
    code, d = call(method, path, body)
    ok = d.get("code", -1) in (0, 1254306)  # 1254306=字段已存在等幂等场景
    tag = "OK  " if ok else "FAIL"
    print("%s %s -> %s %s" % (tag, name, d.get("code"), str(d.get("msg", ""))[:70]))
    return d


if __name__ == "__main__":
    # 0. 先拿默认字段列表（确认结构）
    _, f = call("GET", "/bitable/v1/apps/%s/tables/%s/fields?page_size=50" % (APP_TOKEN, TABLE_ID))
    fields = {it["field_name"]: it["field_id"] for it in f.get("data", {}).get("items", [])}
    print("默认字段:", list(fields))

    B = "/bitable/v1/apps/%s/tables/%s" % (APP_TOKEN, TABLE_ID)

    # 1. 表名
    step("表名", "PATCH", "/bitable/v1/apps/%s/tables/%s" % (APP_TOKEN, TABLE_ID),
         {"name": "问题记录"})

    # 2. 改默认字段（按名字找 id）
    if "文本" in fields:
        step("文本→问题描述", "PUT", B + "/fields/" + fields["文本"], {"field_name": "问题描述", "type": 1})
    if "单选" in fields:
        step("单选→状态", "PUT", B + "/fields/" + fields["单选"], {
            "field_name": "状态", "type": 3,
            "property": {"options": [{"name": "待处理"}, {"name": "处理中"},
                                     {"name": "已解决"}, {"name": "暂不处理"}]}})
    if "日期" in fields:
        step("日期→提出日期", "PUT", B + "/fields/" + fields["日期"], {
            "field_name": "提出日期", "type": 5,
            "property": {"date_formatter": "yyyy/MM/dd HH:mm"}})
    if "附件" in fields:
        step("附件→截图/附件", "PUT", B + "/fields/" + fields["附件"], {"field_name": "截图/附件", "type": 17})

    # 3. 新增字段
    step("新增 提出人", "POST", B + "/fields", {"field_name": "提出人", "type": 1})
    step("新增 备注", "POST", B + "/fields", {"field_name": "备注", "type": 1})

    # 4. 插入第 1 条记录
    ts = int(datetime(2026, 11, 18, 14, 40).timestamp() * 1000)
    step("插入记录#1(3D ROI)", "POST", B + "/records", {
        "fields": {
            "问题描述": ("调试传感器页 3D ROI 界面：\n"
                        "1. 3DROI有一条浅蓝色背景，最好做一下\n"
                        "2. XY Enable缩进不对，这里有一个3D ROI包含以下参数的上下级关系\n"
                        "3. 左Min、右Max（X/Y 轴范围标签顺序应为左 Min、右 Max）"),
            "提出人": "沈梦婷",
            "状态": "待处理",
            "提出日期": ts,
            "备注": "转刘星君处理；群内附 Figma 截图",
        }})

    # 5. 把沈梦婷加为协作者（full_access）
    step("加沈梦婷为协作者", "POST",
         "/drive/v1/permissions/%s/members?type=bitable&need_notification=false" % APP_TOKEN,
         {"member_type": "openid", "member_id": SHEN_OPEN_ID, "perm": "full_access"})

    print("\n表链接: https://rsag16mz9z.feishu.cn/base/" + APP_TOKEN)
