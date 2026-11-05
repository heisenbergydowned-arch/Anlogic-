# -*- coding: utf-8 -*-
"""POST /api/ack —— ★ 全站唯一的「写」动作：确认事件（只写自己的库）。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import apicommon  # noqa: E402


def handle():
    body = apicommon.body_json()
    key = str(body.get("event_key") or "").strip()
    note = str(body.get("note") or "").strip()[:500]
    if not key:
        raise apicommon.HttpError(400, "missing_param", "缺少 event_key")

    who = apicommon.actor()
    con = apicommon.open_store()
    try:
        ok = apicommon.store.ack_event(con, key, who, note)
        if not ok:
            raise apicommon.HttpError(404, "event_not_found", "找不到该事件：%s" % key)
        row = apicommon.store.find_event(con, key)
        audit_id = con.execute("SELECT MAX(id) AS i FROM audit").fetchone()["i"]
    finally:
        con.close()

    return {
        "ok": True,
        "event_key": key,
        "code": row["code"],
        "acknowledged_at_iso": apicommon.store._iso(row["acknowledged_at"]),
        "acknowledged_by": who,
        "audit_id": audit_id,
        "note": "ACK 仅记录审计，不改变硬件保护、不消音、不复位保护",
    }


METHODS = ("POST",)
