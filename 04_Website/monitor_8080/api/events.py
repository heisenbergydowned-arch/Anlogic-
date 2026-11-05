# -*- coding: utf-8 -*-
"""GET /api/events —— 故障/报警事件列表。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import apicommon  # noqa: E402


def handle():
    cfg = apicommon.cfg()
    qs = apicommon.query()

    limit = apicommon.qint(qs, "limit", 50, 1, cfg["api"]["max_events"])
    offset = apicommon.qint(qs, "offset", 0, 0, None)
    state = apicommon.q1(qs, "state", "all")
    unack = str(apicommon.q1(qs, "unack_only", "0")).lower() in ("1", "true", "yes")

    con = apicommon.open_store()
    try:
        total, items = apicommon.store.list_events(con, limit, offset, state, unack)
        active = apicommon.store.count_active_events(con)
        unack_n = apicommon.store.count_unack_events(con)
    finally:
        con.close()

    return {
        "ok": True,
        "total": total,
        "active": active,
        "unacknowledged": unack_n,
        "limit": limit,
        "offset": offset,
        "items": items,
        "boundary_note": "ACK 仅在本机数据库记录审计，不改变硬件保护、不消音、不复位",
    }


METHODS = ("GET",)
