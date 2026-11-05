# -*- coding: utf-8 -*-
"""GET /api/export —— 导出 CSV / JSON。"""

import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import apicommon  # noqa: E402

ALLOWED = ("snapshots", "events", "audit")


def handle():
    cfg = apicommon.cfg()
    qs = apicommon.query()

    what = apicommon.q1(qs, "what", "snapshots")
    if what not in ALLOWED:
        raise apicommon.HttpError(400, "bad_param",
                                "what 只能是 %s" % "/".join(ALLOWED))
    fmt = (apicommon.q1(qs, "format", "csv") or "csv").lower()
    if fmt not in ("csv", "json"):
        raise apicommon.HttpError(400, "bad_param", "format 只能是 csv 或 json")

    now = time.time()
    ts_to = apicommon.store.parse_time(apicommon.q1(qs, "to")) or now
    ts_from = apicommon.store.parse_time(apicommon.q1(qs, "from")) or (ts_to - 7 * 86400.0)

    cap = cfg["api"]["export_max_rows"]
    con = apicommon.open_store()
    try:
        rows = apicommon.store.export_rows(con, what, ts_from, ts_to, cap + 1)
        apicommon.store.add_audit(con, apicommon.actor(), "export", what,
                                "format=%s rows=%d" % (fmt, min(len(rows), cap)), 1)
    finally:
        con.close()

    if len(rows) > cap:
        raise apicommon.HttpError(400, "too_many_rows",
                                "结果超过 %d 行，请缩小时间范围" % cap)

    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    if fmt == "json":
        data = json.dumps(
            {"what": what, "from": apicommon.store._iso(ts_from),
             "to": apicommon.store._iso(ts_to), "count": len(rows), "rows": rows},
            ensure_ascii=False, indent=2).encode("utf-8")
        return apicommon.Raw(data, "application/json; charset=utf-8",
                           "%s_%s.json" % (what, stamp))

    # CSV：★ 带 UTF-8 BOM，便于 Excel 打开中文
    return apicommon.Raw(apicommon.csv_bytes(rows), "text/csv; charset=utf-8",
                       "%s_%s.csv" % (what, stamp))


METHODS = ("GET",)
