# -*- coding: utf-8 -*-
"""第 6 条入表：DLP 调试模式与报错存图开关冗余"""
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
XJ = "ou_<OPEN_ID>"
IMG = r"E:\feishu-bot\data\images\image_img_v3_0217j_f1157d66-d49a-408c-b365-cf11670b6feg.img"


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


# 1. 上传截图
size = os.path.getsize(IMG)
boundary = uuid.uuid4().hex
with open(IMG, "rb") as fp:
    fdata = fp.read()
chunks = []
for k, v in [("file_name", "dlp_debug_switch.jpg"), ("parent_type", "bitable_file"),
             ("parent_node", APP_TOKEN), ("size", str(size))]:
    chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                   % (boundary, k, v)).encode("utf-8"))
chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"dlp_debug_switch.jpg\"\r\n"
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

# 2. 入表（ts=1795059157857 → 本地 11:32:37）
ts = int(datetime(2026, 11, 19, 11, 32).timestamp() * 1000)
fields = {
    "问题描述": ("DLP 传感器调试界面：启用调试模式后，「报错存图」开关实际不再起作用"
                "（调试模式下会向 debug 文件夹存全量图片）——两开关冗余，交互可优化"),
    "版本": "2.3.13",
    "提出人": "沈梦婷",
    "处理人": [{"id": XJ}],
    "状态": "待处理",
    "提出日期": ts,
    "备注": "11-19 群内@刘星君提出；截图见附件",
}
if file_token:
    fields["截图/附件"] = [{"file_token": file_token}]
d = call("POST", B + "/records?user_id_type=open_id", {"fields": fields})
print("入表:", d.get("code"), d.get("msg"))

# 3. 验证
r = call("GET", B + "/records?page_size=50&user_id_type=open_id")
print("total =", r.get("data", {}).get("total"))
for it in r.get("data", {}).get("items", []):
    fl = it.get("fields", {})
    who = (fl.get("处理人") or [{}])[0].get("name", "")
    print("  -", str(fl.get("问题描述"))[:24].replace("\n", " "),
          "|", fl.get("版本"), "|", who, "|", fl.get("状态"))
