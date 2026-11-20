# -*- coding: utf-8 -*-
"""第 12 条：KRL 机器人 POS_ID/MOD_ID 报文报「机器人引导流不存在」"""
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
B = "/bitable/v1/apps/%s/tables/<TABLE_ID_ISSUES>" % APP
SMT = "ou_<OPEN_ID>"
IMG = r"E:\feishu-bot\data\images\image_img_v3_0217j_9f4eff0d-2321-48c5-8b9d-98a0d5c3c17g.img"


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


ft = upload(IMG, "krl_robot_flow_not_exist.jpg")
print("附件上传:", "OK" if ft else "FAIL")

ts = int(datetime(2026, 11, 19, 19, 30).timestamp() * 1000)
fields = {
    "问题描述": ("KRL 机器人通信：发送 <ROBOT><JOB_ID>2</JOB_ID><POS_ID>1</POS_ID>"
                "<MOD_ID>32</MOD_ID></ROBOT> 时弹框报错「机器人引导流不存在」"
                "（报文携带 POS_ID/MOD_ID 时的引导流匹配异常）"),
    "版本": "2.3.13",
    "提出人": "沈梦婷",
    "处理人": [{"id": SMT}],
    "状态": "待处理",
    "提出日期": ts,
    "备注": "11-19 群内提出；截图见附件",
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
    print(" ", str(fl.get("问题描述"))[:22].replace("\n", " "), "|", fl.get("状态"), "|", who)
