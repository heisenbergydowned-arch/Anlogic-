#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 query_history 的 deadband 沿用语义。"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8080"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    now = int(time.time())
    d = get("/api/history?from=%d&to=%d&max_points=600" % (now - 300, now))
    s = d["series"]

    print("桶宽 %.2fs | 桶数 %d | 实际行数 %d | stride %s"
          % (d["bucket_s"], d["count"], d["rows"], d.get("stride")))

    for k in ("rpm", "temp_c"):
        vals = s.get(k) or []
        held = s.get(k + "_held") or []
        nn = sum(1 for x in vals if x is not None)
        hd = sum(held)
        print("  %-8s 非 null %3d / %d   实测 %3d   沿用 %3d   真缺失 %3d"
              % (k, nn, len(vals), nn - hd, hd, len(vals) - nn))

    print("  window_note:", d.get("window_note", "(无)"))
    print("  held_note  :", d.get("held_note", "(无)"))

    # 用 rpm 的前 40 个点示意
    print()
    print("  rpm 前 40 个点（· = null，= = 沿用值，数字 = 实测）:")
    row = []
    for i in range(min(40, len(s["rpm"]))):
        v = s["rpm"][i]
        h = (s["rpm_held"] or [])[i] if i < len(s.get("rpm_held") or []) else 0
        if v is None:
            row.append("·")
        elif h:
            row.append("=")
        else:
            row.append("#")
    print("   " + "".join(row))
    print("   · null   = 沿用(deadband)   # 实测样本")


if __name__ == "__main__":
    main()
