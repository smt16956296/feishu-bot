# -*- coding: utf-8 -*-
"""file.py — 飞书文件消息工具（上传 + 发送）。

2026-11-20 从 push.py 拆出（沈梦婷建议）：文件消息与文本/卡片差异大
（multipart 上传、file_type、大小限制），单独成模块，与 card.py / recall.py
保持「一种消息类型一个模块」的对称结构。push.py --attach 改为调用本模块，
命令行用法不变。

用法（命令行）：
    py -3 -X utf8 file.py --chat oc_xxx --path 报告.xlsx
    py -3 -X utf8 file.py --to ou_xxx --path 数据.zip
    py -3 -X utf8 file.py --chat oc_xxx --path a.xlsx --text "说明文字"   # 文字+文件

用法（Python 代码）：
    from file import upload, send_file
    key = upload(r"E:\\tmp\\a.xlsx")            # 只上传，拿 file_key（可复用发多条）
    send_file("oc_xxx", r"E:\\tmp\\a.xlsx", is_chat=True)

飞书限制：
    · im/v1/files 上传接口 file_type=stream（通用文件），单文件上限 30MB
    · 文件消息没有「引用回复」，--reply 无效
    · file_key 上传后可复用（同一文件发多个会话不必重复上传）
"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

# 与 bot.py / push.py 同源：应用凭证从 config.py（.env）读，不硬编码
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import APP_ID, APP_SECRET  # noqa: E402

API = "https://open.feishu.cn/open-apis"
MAX_SIZE = 30 * 1024 * 1024  # 飞书文件上传上限 30MB


def _token() -> str:
    """取 tenant_access_token（内部应用）。"""
    req = urllib.request.Request(
        API + "/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        tok = json.loads(r.read()).get("tenant_access_token", "")
    if not tok:
        raise RuntimeError("取 tenant_access_token 失败")
    return tok


def upload(path: str, file_type: str = "stream") -> str:
    """上传本地文件，返回 file_key（上传失败抛异常）。

    file_type: stream=通用文件 / mp4=视频 / opus=音频 / pdf。默认 stream 兜底最稳。
    """
    size = os.path.getsize(path)
    if size > MAX_SIZE:
        raise ValueError("文件 %.1fMB 超过飞书 30MB 上限，请压缩或走网盘链接" % (size / 1048576))
    fname = os.path.basename(path)
    with open(path, "rb") as f:
        fdata = f.read()
    boundary = uuid.uuid4().hex
    chunks = []
    for k, v in [("file_type", file_type), ("file_name", fname), ("duration", "0")]:
        chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                       % (boundary, k, v)).encode("utf-8"))
    chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                   "Content-Type: application/octet-stream\r\n\r\n" % (boundary, fname)).encode("utf-8"))
    chunks.append(fdata)
    chunks.append(("\r\n--%s--\r\n" % boundary).encode("utf-8"))
    req = urllib.request.Request(
        API + "/im/v1/files",
        data=b"".join(chunks), method="POST",
        headers={"Authorization": "Bearer " + _token(),
                 "Content-Type": "multipart/form-data; boundary=" + boundary},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    if d.get("code") != 0:
        raise RuntimeError("文件上传失败 code=%s msg=%s" % (d.get("code"), d.get("msg")))
    return d.get("data", {}).get("file_key", "")


def send_file(receive_id: str, path: str, is_chat: bool = False) -> bool:
    """上传本地文件并以文件消息发送。receive_id 为 open_id（私聊）或 chat_id（群）。"""
    try:
        file_key = upload(path)
        rid_type = "chat_id" if is_chat else "open_id"
        payload = {"receive_id": receive_id, "msg_type": "file",
                   "content": json.dumps({"file_key": file_key})}
        req = urllib.request.Request(
            API + "/im/v1/messages?receive_id_type=%s" % rid_type,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + _token(),
                     "Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read())
        ok = d.get("code") == 0
        if not ok:
            print("[ERROR] 文件消息发送失败 code=%s msg=%s" % (d.get("code"), d.get("msg")),
                  file=sys.stderr)
        return ok
    except urllib.error.HTTPError as e:
        print("[ERROR] 文件发送 HTTP %s: %s" % (e.code, e.read().decode()[:200]), file=sys.stderr)
        return False
    except Exception as e:
        print("[ERROR] 文件发送异常: %s" % e, file=sys.stderr)
        return False


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="发文件消息到飞书（群/私聊）")
    ap.add_argument("--chat", default="", help="群 chat_id（oc_ 开头）")
    ap.add_argument("--to", default="", help="私聊 open_id（ou_ 开头）")
    ap.add_argument("--path", required=True, help="本地文件绝对路径（≤30MB）")
    ap.add_argument("--text", default="", help="随文件附带的说明文字（先发一条文本）")
    args = ap.parse_args()

    if not os.path.isfile(args.path):
        print("[ERROR] 文件不存在: %s" % args.path, file=sys.stderr)
        return 1
    if not args.chat and not args.to:
        print("[ERROR] 需要 --chat 或 --to", file=sys.stderr)
        return 1

    if args.text.strip():
        # 复用 push.py 的文本发送（避免重复造轮子）
        from push import send, send_to_chat
        if args.chat:
            send_to_chat(args.chat, args.text)
        else:
            send(args.text, args.to)

    ok = send_file(args.chat or args.to, args.path, is_chat=bool(args.chat))
    print("OK" if ok else "FAILED", file=sys.stderr if not ok else sys.stdout)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
