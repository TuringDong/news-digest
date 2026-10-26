#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""show_raw.py — 打印 raw.json 的抓取概况，排查某个源是否挂掉。"""

import json
import sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    d = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "raw.json", encoding="utf-8"))
except FileNotFoundError:
    print("没有 raw.json，说明抓取那一步没跑成")
    sys.exit(0)

print("时间窗口:", d["window"]["start"], "->", d["window"]["end"])
print("条目: %d  | tech=%d other=%d" % (len(d["items"]), d["counts"]["tech"], d["counts"]["other"]))
print("各源命中:", "，".join(d.get("per_source") or []))
if d.get("failures"):
    print("失败源:")
    for f in d["failures"]:
        print("  -", f)
else:
    print("所有源正常")
