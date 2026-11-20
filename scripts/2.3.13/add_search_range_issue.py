# -*- coding: utf-8 -*-
"""第 7 条入表：模板配置搜索范围可超出限制（处理人待定）"""
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
IMG = r"E:\feishu-bot\data\images\image_img_v3_0217j_70e95f8a-f1f2-4e06-ae35-115db0a9f66g.img"


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


size = os.path.getsize(IMG)
boundary = uuid.uuid4().hex
with open(IMG, "rb") as fp:
    fdata = fp.read()
chunks = []
for k, v in [("file_name", "search_range_overflow.jpg"), ("parent_type", "bitable_file"),
             ("parent_node", APP_TOKEN), ("size", str(size))]:
    chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                   % (boundary, k, v)).encode("utf-8"))
chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"search_range_overflow.jpg\"\r\n"
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
print("截图上传:", d.get("code"))

ts = int(datetime(2026, 11, 19, 14, 10).timestamp() * 1000)
fields = {
    "问题描述": ("模板配置界面：框选搜索范围后，重新调整搜索范围大小时，"
                "调整结果可以超出搜索框大小限制（调整时未约束边界）"),
    "版本": "2.3.13",
    "提出人": "沈梦婷",
    "状态": "待处理",
    "提出日期": ts,
    "备注": "11-19 群内提出；处理人待定；截图见附件",
}
if file_token:
    fields["截图/附件"] = [{"file_token": file_token}]
d = call("POST", B + "/records?user_id_type=open_id", {"fields": fields})
print("入表:", d.get("code"), d.get("msg"))

r = call("GET", B + "/records?page_size=50&user_id_type=open_id")
print("total =", r.get("data", {}).get("total"))
for it in r.get("data", {}).get("items", []):
    fl = it.get("fields", {})
    who = (fl.get("处理人") or [{}])[0].get("name", "-")
    print("  -", str(fl.get("问题描述"))[:22].replace("\n", " "),
          "|", fl.get("版本"), "|", who, "|", fl.get("状态"))
