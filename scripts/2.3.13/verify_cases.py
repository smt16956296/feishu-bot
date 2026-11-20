# -*- coding: utf-8 -*-
"""全量验证整改结果"""
import json
import sys
import urllib.request

sys.path.insert(0, r"E:\feishu-bot")
from card import _token, API  # noqa

B = "/bitable/v1/apps/<APP_TOKEN_JOINT>/tables/<TABLE_ID_CASES>"


def call(path):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + _token()})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


rows, tok = [], None
while True:
    d = call(B + "/records?page_size=100" + (("&page_token=" + tok) if tok else ""))
    rows.extend(d["data"]["items"])
    if not d["data"].get("has_more"):
        break
    tok = d["data"]["page_token"]

short = [it["fields"] for it in rows
         if len(it["fields"].get("测试用例") or "") <= 4 and not it["fields"].get("预期/补充")]
print("总", len(rows), " 短名无补充:", len(short))
for f in short[:6]:
    print("  短:", repr(f.get("测试用例")), "| 分类:", f.get("分类"))

for it in rows:
    f = it["fields"]
    n = f.get("测试用例") or ""
    if "暗特征" in n or "投3D图" in n or "RF引导" in n or "引导报错" in n or "输入拦截" in n or "历史记录" in n:
        print("  修后:", n[:46], "| 类型:", f.get("类型"),
              "| 补充:", f.get("预期/补充"), "| 分类:", (f.get("分类") or "")[:34])
