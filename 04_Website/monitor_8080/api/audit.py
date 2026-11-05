# -*- coding: utf-8 -*-
"""GET /api/audit —— 审计日志。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import apicommon  # noqa: E402


def handle():
    cfg = apicommon.cfg()
    qs = apicommon.query()
    limit = apicommon.qint(qs, "limit", 50, 1, 500)
    offset = apicommon.qint(qs, "offset", 0, 0, None)

    con = apicommon.open_store()
    try:
        total, items = apicommon.store.list_audit(con, limit, offset)
    finally:
        con.close()

    return {"ok": True, "total": total, "limit": limit, "offset": offset, "items": items}


METHODS = ("GET",)
