#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 /api/history 的分辨率（bucket）参数。"""
import json
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8080"
now = int(time.time())

CASES = [
    ("自动", "auto", 300),
    ("自动", "auto", 3600),
    ("自动", "auto", 86400),
    ("1 秒", "1", 300),
    ("10 秒", "10", 300),
    ("1 分钟", "60", 300),
    ("1 分钟", "60", 3600),
    ("1 分钟", "60", 86400),
    ("5 分钟", "300", 86400),
    ("1 小时", "3600", 86400),
    ("1 秒(超量)", "1", 86400),
    ("非法值", "abc", 300),
]

print("%-12s %-9s %-10s %-12s %-8s %s" % ("档位", "窗口", "请求桶宽", "实际桶宽", "点数", "备注"))
print("-" * 92)
for name, bk, span in CASES:
    url = "%s/api/history?from=%d&to=%d&max_points=600&bucket=%s" % (BASE, now - span, now, bk)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode("utf-8"))
        print("%-12s %-9s %-10s %-12s %-8s HTTP %d %s"
              % (name, "%ds" % span, bk, "-", "-", e.code, body.get("detail", "")[:28]))
        continue
    w = ("%d 分钟" % (span // 60)) if span >= 60 else ("%d 秒" % span)
    note = d.get("bucket_note") or ""
    print("%-12s %-9s %-10s %-12s %-8d %s"
          % (name, w, bk, "%.2fs" % d["bucket_s"], d["count"], note[:44]))
