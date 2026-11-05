# -*- coding: utf-8 -*-
"""GET /api/snapshots —— 遥测快照数据分页查询与单条详情。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import apicommon  # noqa: E402


def handle():
    qs = apicommon.query()
    sid = apicommon.qint(qs, "id", 0, 0, None)
    if sid > 0:
        con = apicommon.open_store()
        try:
            row = con.execute("SELECT * FROM snapshots WHERE id=?", (sid,)).fetchone()
            if not row:
                raise apicommon.HttpError(404, "not_found", "快照记录不存在")
            return {"ok": True, "item": dict(row)}
        finally:
            con.close()

    limit = apicommon.qint(qs, "limit", 50, 1, 500)
    offset = apicommon.qint(qs, "offset", 0, 0, None)

    con = apicommon.open_store()
    try:
        total = con.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
        rows = con.execute(
            "SELECT id, ts, ts_iso, sequence, link_ok, message, mode, alarm, action, "
            "inhibit, configured, uptime_ms, rpm, temp_c, current_raw, pressure_ok, "
            "current_a, pressure_pa, current_kind, pressure_kind, "
            "validity, faults, latched, queue, drops, frame_id, frame_age_ms, "
            "frame_state, quality, quality_reasons, feature_count "
            "FROM snapshots ORDER BY ts DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
        items = [dict(r) for r in rows]
    finally:
        con.close()

    return {
        "ok": True,
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


METHODS = ("GET",)
