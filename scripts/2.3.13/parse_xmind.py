# -*- coding: utf-8 -*-
"""解析 xmind 测试用例树 → 输出扁平结构预览"""
import zipfile
import json

P = r"D:\ShareCache\颜文轩\BF易用性提升\测试方案\【BF测量能力与易用性提升产品变更】BF测量能力与易用性提升产品变更-迭代集成测试点梳理.xmind"

z = zipfile.ZipFile(P)
data = json.loads(z.read("content.json"))
root = data[0]["rootTopic"]


def walk(topic, depth=0, path=()):
    title = topic.get("title", "").strip()
    children = topic.get("children", {})
    subs = []
    for attached in children.get("attached", []):
        subs.extend(walk(attached, depth + 1, path + (title,)))
    if not subs:  # 叶子
        return [(path, title)]
    return subs


rows = walk(root)
print("叶子节点数:", len(rows))
for path, leaf in rows:
    print(" | ".join(p for p in path[1:] if p) + (" >> " + leaf if leaf else ""))
