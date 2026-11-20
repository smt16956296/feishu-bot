# -*- coding: utf-8 -*-
"""第 10 条：零位计算失败弹双警告"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

APP = "<APP_TOKEN_ISSUES>"
TID = "<TABLE_ID_ISSUES>"
B = "/bitable/v1/apps/%s/tables/%s" % (APP, TID)
SMT = "ou_<OPEN_ID>"
IMG = r"E:\feishu-bot\data\images\image_img_v3_0217j_f32f6e0a-24ef-436a-9701-75e8b1e7c40g.img"


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


def upload(path, name):
    size = os.path.getsize(path)
    boundary = uuid.uuid4().hex
    with open(path, "rb") as fp:
        fdata = fp.read()
    parts = []
    for k, v in [("file_name", name), ("parent_type", "bitable_file"),
                 ("parent_node", APP), ("size", str(size))]:
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                      % (boundary, k, v)).encode("utf-8"))
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                  "Content-Type: image/jpeg\r\n\r\n" % (boundary, name)).encode("utf-8"))
    parts.append(fdata)
    parts.append(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    req = urllib.request.Request(
        API + "/drive/v1/medias/upload_all", data=b"".join(parts), method="POST",
        headers={"Authorization": "Bearer " + _token(),
                 "Content-Type": "multipart/form-data; boundary=" + boundary})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("data", {}).get("file_token", "")


ft = upload(IMG, "zero_calc_fail_warn.jpg")
print("附件上传:", "OK" if ft else "FAIL")

ts = int(datetime(2026, 11, 19, 17, 45).timestamp() * 1000)
fields = {
    "问题描述": ("零位计算失败时，客户端右下角同时弹出两个警告："
                "「算法计算失败」和「一般性错误」（提示重复、口径不统一）"),
    "版本": "2.3.13",
    "提出人": "沈梦婷",
    "处理人": [{"id": SMT}],
    "状态": "待处理",
    "提出日期": ts,
    "备注": "11-19 群内提出；沈梦婷自行修复；截图见附件",
}
if ft:
    fields["截图/附件"] = [{"file_token": ft}]
d = call("POST", B + "/records?user_id_type=open_id", {"fields": fields})
print("入表:", d.get("code"), d.get("msg"))

r = call("GET", B + "/records?page_size=50&user_id_type=open_id")
print("total =", r.get("data", {}).get("total"))
for it in r.get("data", {}).get("items", []):
    fl = it["fields"]
    who = (fl.get("处理人") or [{}])[0].get("name", "-")
    print(" ", str(fl.get("问题描述"))[:20].replace("\n", " "), "|", fl.get("状态"), "|", who)
