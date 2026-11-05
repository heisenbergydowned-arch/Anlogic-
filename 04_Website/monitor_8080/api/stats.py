# -*- coding: utf-8 -*-
"""GET /api/stats —— 数据库统计。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import apicommon  # noqa: E402


def handle():
    cfg = apicommon.cfg()
    dbp = apicommon.db_path()

    con = apicommon.open_store()
    try:
        st = apicommon.store.db_stats(con, dbp)
        st["last_purge_at"] = apicommon.store.get_meta(con, "last_purge_at")
        st["last_snapshot_at"] = apicommon.store.get_meta(con, "last_snapshot_at")
        st["collector_started_at"] = apicommon.store.get_meta(con, "collector_started_at")
        st["boot_id"] = apicommon.store.get_meta(con, "boot_id")
        st["created_at"] = apicommon.store.get_meta(con, "created_at")
    finally:
        con.close()

    c = cfg["collector"]
    st["ok"] = True
    st["config"] = {
        "store_mode": c.get("store_mode"),
        "sample_interval_s": c.get("sample_interval_s"),
        "heartbeat_s": c.get("heartbeat_s"),
        "retain_days": c.get("retain_days"),
        "deadband": c.get("deadband"),
    }
    st["estimate_mb_per_day"] = 3.0 if c.get("store_mode") == "deadband" else 28.0
    return st


METHODS = ("GET",)
