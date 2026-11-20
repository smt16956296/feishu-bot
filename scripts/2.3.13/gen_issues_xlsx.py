# -*- coding: utf-8 -*-
"""从 2313_dev_issues.md 生成 xlsx（后续权限批下来前的正式载体）"""
import re
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

SRC = r"E:\feishu-bot\data\2313_dev_issues.md"
OUT = r"E:\feishu-bot\data\2313_dev_issues.xlsx"

text = open(SRC, encoding="utf-8").read()

# 解析条目块：## N. 标题 …
entries = []
blocks = re.split(r"\n## ", text)
for b in blocks[1:]:
    lines = b.strip().split("\n")
    title = lines[0].strip()
    num = title.split(".")[0].strip()
    tname = title.split(".", 1)[1].strip() if "." in title else title
    date, owner, fixer, ver, status, body = "", "", "", "", "", []
    for ln in lines[1:]:
        s = ln.strip()
        if s.startswith("- 日期："):
            date = s.replace("- 日期：", "").strip()
        elif s.startswith("- 提出人："):
            owner = s.replace("- 提出人：", "").strip()
        elif s.startswith("- 处理人："):
            fixer = s.replace("- 处理人：", "").strip()
        elif s.startswith("- 版本："):
            ver = s.replace("- 版本：", "").strip()
        elif s.startswith("- 状态："):
            status = s.replace("- 状态：", "").strip()
        elif s.startswith("- 问题（原话）："):
            body.append(s.replace("- 问题（原话）：", "").strip())
        elif s.startswith(("1. ", "2. ", "3. ", "4. ", "5. ", "- ")):
            body.append(s)
    entries.append({
        "num": int(num),
        "ver": ver,
        "date": date[:16],
        "owner": owner,
        "fixer": fixer,
        "desc": (tname + "\n" + "\n".join(x.lstrip("- ").strip() for x in body if x.strip())).strip(),
        "status": status or "待处理",
    })

wb = Workbook()
ws = wb.active
ws.title = "问题记录"

headers = ["序号", "版本", "提出日期", "提出人", "处理人", "问题描述", "状态"]
widths = [6, 9, 17, 10, 10, 76, 10]

thin = Side(style="thin", color="C0C0C0")
border = Border(left=thin, right=thin, top=thin, bottom=thin)
head_fill = PatternFill("solid", fgColor="2B2B2B")
head_font = Font(color="FFFFFF", bold=True, size=11)
wrap = Alignment(vertical="top", wrap_text=True)

for c, (h, w) in enumerate(zip(headers, widths), 1):
    cell = ws.cell(row=1, column=c, value=h)
    cell.fill, cell.font, cell.border = head_fill, head_font, border
    cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.column_dimensions[get_column_letter(c)].width = w

st_fill = {"待处理": "FCE8E8", "处理中": "FFF3E0", "已解决": "E8F5E9", "暂不处理": "F2F2F2"}
for r, e in enumerate(entries, 2):
    vals = [e["num"], e["ver"], e["date"], e["owner"], e["fixer"], e["desc"], e["status"]]
    for c, v in enumerate(vals, 1):
        cell = ws.cell(row=r, column=c, value=v)
        cell.border, cell.alignment = border, wrap
        if c in (1, 2, 4, 5, 7):
            cell.alignment = Alignment(horizontal="center", vertical="top")
        if c == 7:
            cell.fill = PatternFill("solid", fgColor=st_fill.get(e["status"], "FFFFFF"))
    ws.row_dimensions[r].height = 58

ws.freeze_panes = "A2"
wb.save(OUT)
print("OK", OUT, "条目数:", len(entries))
