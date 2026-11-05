#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证：趋势图上的断线区间，是否都能对应到「传感器无效」的原始记录？

做法：取近 5 分钟的聚合序列 → 找出所有 null 连续段 → 回查数据库里那段时间的行，
      看它们的 validity / frame_state / rpm 到底是什么。
"""
import json
import time
import sqlite3
import urllib.request

DB = "/home/uisrc/web/data/cabinet.sqlite3"
BASE = "http://127.0.0.1:8080"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def fmt(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts))


def main():
    now = int(time.time())
    d = get("/api/history?from=%d&to=%d&max_points=600" % (now - 300, now))
    s = d["series"]
    ts, rpm, held = s["ts"], s["rpm"], s["rpm_held"]
    bucket = d["bucket_s"]

    print("窗口 %s ~ %s  桶宽 %.1fs  共 %d 桶" % (fmt(ts[0]), fmt(ts[-1]), bucket, len(ts)))
    print("max_hold_s = %s   rows = %d" % (d.get("max_hold_s"), d["rows"]))
    print()

    # 找出所有 null 连续段
    runs = []
    i = 0
    while i < len(ts):
        if rpm[i] is None:
            j = i
            while j + 1 < len(ts) and rpm[j + 1] is None:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    print("=== 断线区间共 %d 段 ===" % len(runs))
    print("%-4s %-9s %-9s %6s %6s  %-28s %-14s %s"
          % ("#", "起", "止", "时长", "行数", "validity", "frame_state", "判定"))
    for k, (a, b) in enumerate(runs):
        t0, t1 = ts[a], ts[b] + bucket
        rows = con.execute(
            "SELECT validity, frame_state, rpm FROM snapshots WHERE ts>=? AND ts<=? ORDER BY ts",
            (t0, t1)).fetchall()
        n = len(rows)
        if n == 0:
            # 看区间之前最后一行是什么
            prev = con.execute(
                "SELECT ts, validity, rpm FROM snapshots WHERE ts<? ORDER BY ts DESC LIMIT 1",
                (t0,)).fetchone()
            gap = (t0 - prev["ts"]) if prev else None
            if prev is None:
                verdict = "库中无更早数据（窗口左侧为空）"
            elif gap is not None and gap > float(d.get("max_hold_s") or 30):
                verdict = "中断 %.0fs > max_hold，停止沿用" % gap
            else:
                verdict = "?? 应沿用却断了"
            vs = "(无行)"
            fs = "-"
        else:
            vals = sorted(set(r["validity"] or "" for r in rows))
            fss = sorted(set(r["frame_state"] or "" for r in rows))
            nn = sum(1 for r in rows if r["rpm"] is not None)
            vs = vals[0][:28] if len(vals) == 1 else ("%d 种" % len(vals))
            fs = ",".join(fss)[:14]
            verdict = ("传感器无效 (validity 全 0)" if nn == 0
                       else "?? 有 %d 行非空却断了" % nn)
        print("%-4d %-9s %-9s %5.0fs %6d  %-28s %-14s %s"
              % (k + 1, fmt(t0), fmt(t1), t1 - t0, n, vs, fs, verdict))

    # 全库层面：validity 与 rpm 的关系
    print()
    tot = con.execute("SELECT COUNT(*) n FROM snapshots").fetchone()["n"]
    bad = con.execute(
        "SELECT COUNT(*) n FROM snapshots WHERE validity LIKE '%RPM:0%'").fetchone()["n"]
    nul = con.execute("SELECT COUNT(*) n FROM snapshots WHERE rpm IS NULL").fetchone()["n"]
    print("=== 全库核对 ===")
    print("  总行数            %d" % tot)
    print("  validity 含 RPM:0 %d" % bad)
    print("  rpm 为 NULL 的行  %d" % nul)
    print("  → 两者应一致：%s" % ("✅ 一致（NULL 只来自无效数据）" if bad == nul
                                  else "❌ 不一致，需要查"))
    con.close()


if __name__ == "__main__":
    main()
