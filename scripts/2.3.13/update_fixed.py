# -*- coding: utf-8 -*-
"""刘星君反馈已修复：3条标已解决 + 补录第4条（滑动条）"""
import json
import sys
import os
import urllib.request
import uuid
from datetime import datetime

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

APP_TOKEN = "<APP_TOKEN_ISSUES>"
TABLE_ID = "<TABLE_ID_ISSUES>"
B = "/bitable/v1/apps/%s/tables/%s" % (APP_TOKEN, TABLE_ID)
XJ = "ou_<OPEN_ID>"  # 刘星君
IMG = r"E:\feishu-bot\data\images\image_img_v3_0217i_d3eadd05-9e61-4d37-962d-fed413a57b1g.img"


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


# 1. 现有 3 条 → 已解决
r = call("GET", B + "/records?page_size=20")
for it in r.get("data", {}).get("items", []):
    rid = it["record_id"]
    d = call("PUT", B + "/records/" + rid,
             {"fields": {"状态": "已解决", "备注": "11-19 群内刘星君反馈已修复"}})
    print("状态更新", str(it.get("fields", {}).get("问题描述"))[:16], "->", d.get("code"))

# 2. 上传滑动条截图
size = os.path.getsize(IMG)
boundary = uuid.uuid4().hex
with open(IMG, "rb") as fp:
    fdata = fp.read()
chunks = []
for k, v in [("file_name", "slider_issue.jpg"), ("parent_type", "bitable_file"),
             ("parent_node", APP_TOKEN), ("size", str(size))]:
    chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                   % (boundary, k, v)).encode("utf-8"))
chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"slider_issue.jpg\"\r\n"
               "Content-Type: image/jpeg\r\n\r\n" % boundary).encode("utf-8"))
chunks.append(fdata)
chunks.append(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
req = urllib.request.Request(
    API + "/drive/v1/medias/upload_all",
    data=b"".join(chunks), method="POST",
    headers={"Authorization": "Bearer " + _token(),
             "Content-Type": "multipart/form-data; boundary=" + boundary})
with urllib.request.urlopen(req, timeout=60) as resp:
    d = json.loads(resp.read())
file_token = d.get("data", {}).get("file_token", "")
print("滑动条截图上传:", d.get("code"), "token:", file_token[:16] if file_token else "无")

# 3. 补录第 4 条
ts = int(datetime(2026, 11, 18, 17, 19).timestamp() * 1000)
fields = {
    "问题描述": "调试传感器页：滑动条太窄，右侧输入框过大——输入框最多 3 位数，没必要留这么大",
    "提出人": "沈梦婷",
    "处理人": [{"id": XJ}],
    "状态": "待处理",
    "提出日期": ts,
    "备注": "11-18 17:19 群内提出（当时未@桃桃，11-19 从聊天记录补录）",
}
if file_token:
    fields["截图/附件"] = [{"file_token": file_token}]
d = call("POST", B + "/records?user_id_type=open_id", {"fields": fields})
print("补录滑动条:", d.get("code"), d.get("msg"))

# 4. 验证
r = call("GET", B + "/records?page_size=20&user_id_type=open_id")
print("total =", r.get("data", {}).get("total"))
for it in r.get("data", {}).get("items", []):
    fl = it.get("fields", {})
    print("  -", str(fl.get("问题描述"))[:24].replace("\n", " "), "|", fl.get("状态"))
