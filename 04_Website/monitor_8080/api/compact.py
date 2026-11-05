# -*- coding: utf-8 -*-
"""
GET  /api/compact —— 查询数据库文件里有多少空闲页（可回收空间）
POST /api/compact —— 执行 VACUUM，把空闲页真正还给文件系统

★ 与 /api/purge 的区别：
  purge  删除历史行（不可逆），但 SQLite 在 auto_vacuum=0 时只把页丢进
         freelist，文件一点不缩 —— 所以删完必须再压缩才省磁盘。
  compact 只重排文件、回收空闲页，**不删除任何数据**。

★ VACUUM 需要排他锁，期间采集进程的写入会阻塞 1~3 秒。
  拿不到锁时返回 409，不排队硬等。
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import apicommon  # noqa: E402

# 低于这个量不值得压缩：收益太小，还要短暂锁库
MIN_RECLAIM_BYTES = 256 * 1024


def _snapshot(con):
    total, free_pages, free_bytes, ratio = apicommon.store.page_stats(con)
    return {
        "db_bytes": total,
        "free_pages": free_pages,
        "reclaimable": free_bytes,
        "free_ratio": round(ratio, 4),
        "auto_vacuum": con.execute("PRAGMA auto_vacuum").fetchone()[0],
    }


def handle():
    method = apicommon.require_method("GET", "POST")
    con = apicommon.open_store()
    try:
        info = _snapshot(con)
        info["worth"] = info["reclaimable"] >= MIN_RECLAIM_BYTES
        info["min_reclaim_bytes"] = MIN_RECLAIM_BYTES

        if method == "GET":
            info["ok"] = True
            return info

        body = apicommon.body_json()
        if str(body.get("confirm") or "") != "VACUUM":
            raise apicommon.HttpError(400, "confirm_required",
                                      '必须显式传 confirm="VACUUM" 才执行压缩')

        before = info["db_bytes"]

        # VACUUM 不能在事务内执行；open_store 是 autocommit，可以直接跑
        try:
            con.execute("VACUUM")
        except sqlite3.OperationalError as e:
            raise apicommon.HttpError(409, "db_busy",
                                      "数据库正被占用，稍后重试（%s）" % e)

        apicommon.store.add_audit(con, apicommon.actor(), "vacuum", "database",
                                  "before=%d free=%d" % (before, info["reclaimable"]), 1)
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass

        after = _snapshot(con)
        saved = max(0, before - after["db_bytes"])
        after.update({
            "ok": True,
            "before_bytes": before,
            "saved_bytes": saved,
            "saved_ratio": round(saved / float(before), 4) if before else 0.0,
            "note": "VACUUM 完成，已回收空闲页；数据一行未删",
        })
        return after
    finally:
        con.close()


METHODS = ("GET", "POST")
