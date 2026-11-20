# -*- coding: utf-8 -*-
"""把处理人列改成人员字段（@真人）"""
import json
import sys
import urllib.request

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa
from push import resolve_open_id  # noqa

APP_TOKEN = "<APP_TOKEN_ISSUES>"
TABLE_ID = "<TABLE_ID_ISSUES>"
B = "/bitable/v1/apps/%s/tables/%s" % (APP_TOKEN, TABLE_ID)


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


if __name__ == "__main__":
    # 1. 刘星君 open_id
    xj = resolve_open_id("刘星君")
    print("刘星君 open_id:", xj or "未找到")
    if not xj:
        sys.exit(1)

    # 2. 字段现状
    f = call("GET", B + "/fields?page_size=50")
    fmap = {it["field_name"]: it for it in f.get("data", {}).get("items", [])}
    fixer = fmap.get("处理人")
    if fixer:
        print("处理人字段:", fixer["field_id"], "type=", fixer["type"])

    # 3. 删文本版（若已删则跳过），建人员版
    if fixer:
        d = call("DELETE", B + "/fields/" + fixer["field_id"])
        print("删文本处理人:", d.get("code"), d.get("msg"))
    else:
        print("文本处理人已不存在，直接建")
    d = call("POST", B + "/fields", {"field_name": "处理人", "type": 11})
    if d.get("code") != 0:
        print("最小body失败:", d.get("code"), str(d.get("msg"))[:200])
        d = call("POST", B + "/fields",
                 {"field_name": "处理人", "type": 11, "property": {"user_type": "User"}})
    print("建人员处理人:", d.get("code"), d.get("msg"))
    new_fid = d.get("data", {}).get("field", {}).get("field_id", "")

    # 4. 三条记录写入人员
    r = call("GET", B + "/records?page_size=20")
    for it in r.get("data", {}).get("items", []):
        rid = it["record_id"]
        d = call("PUT", B + "/records/%s?user_id_type=open_id" % rid,
                 {"fields": {"处理人": [{"id": xj}]}})
        print("记录", rid, "->", d.get("code"), d.get("msg"))

    # 5. 验证
    r = call("GET", B + "/records?page_size=20&user_id_type=open_id")
    for it in r.get("data", {}).get("items", []):
        fl = it.get("fields", {})
        print("  验证:", str(fl.get("问题描述"))[:20].replace("\n", " "),
              "| 处理人:", json.dumps(fl.get("处理人"), ensure_ascii=False)[:80])
