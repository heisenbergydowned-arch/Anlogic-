# -*- coding: utf-8 -*-
"""POST /api/purge —— 删除过期数据。必须显式 confirm == "PURGE"。"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import apicommon  # noqa: E402

ALLOWED = ("snapshots", "audit", "events", "events_all", "checkpoint")


def handle():
    body = apicommon.body_json()
    what = body.get("what") or []
    if isinstance(what, str):
        what = [x.strip() for x in what.split(",")]
    if "all" in what or "ALL" in what:
        what = ["snapshots", "audit", "events_all"]
    what = [w for w in what if w in ALLOWED]
    if not what:
        raise apicommon.HttpError(400, "bad_param",
                                "what 只能是 %s 的子集" % "/".join(ALLOWED))

    who = apicommon.actor()
    con = apicommon.open_store()
    try:
        if what == ["checkpoint"]:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            apicommon.store.add_audit(con, who, "checkpoint", "wal",
                                      str(body.get("note") or "manual truncate")[:200], 1)
            left = apicommon.store.db_stats(con, apicommon.db_path())
            return {
                "ok": True,
                "action": "checkpoint",
                "remaining": {"snapshots": left["snapshots"], "events": left["events"],
                              "audit": left["audit"]},
                "stats": left,
                "note": "已成功执行 PRAGMA wal_checkpoint(TRUNCATE) 截断 WAL",
            }

        if str(body.get("confirm") or "") != "PURGE":
            raise apicommon.HttpError(400, "confirm_required",
                                    '必须显式传 confirm="PURGE" 才执行删除')

        before_val = body.get("before_iso")
        if before_val in ("now", "NOW"):
            before = time.time()
        else:
            before = apicommon.store.parse_time(before_val)

        if before is None:
            days = body.get("before_days")
            if days in ("now", "NOW"):
                before = time.time()
            else:
                try:
                    days = float(days)
                except (TypeError, ValueError):
                    raise apicommon.HttpError(400, "bad_param", "需要 before_iso 或 before_days")
                if days < 0:
                    raise apicommon.HttpError(400, "bad_param", "before_days 不能为负数")
                before = time.time() - days * 86400.0

        if before > time.time() + 5.0:
            raise apicommon.HttpError(400, "bad_param", "before 时间不能是未来")

        now = time.time()
        if before > now:
            before = now

        deleted = apicommon.store.purge(con, before, what, who,
                                      str(body.get("note") or "")[:200])
        left = apicommon.store.db_stats(con, apicommon.db_path())
    finally:
        con.close()

    note_msg = "已执行 WAL checkpoint(TRUNCATE)"
    if "events_all" in what:
        note_msg = "events 已清理全部（含活动与已恢复）；" + note_msg
    elif "events" in what:
        note_msg = "events 只删除「已恢复且早于该时间」的条目；" + note_msg

    return {
        "ok": True,
        "deleted": deleted,
        "before_iso": apicommon.store._iso(before),
        "what": what,
        "remaining": {"snapshots": left["snapshots"], "events": left["events"],
                      "audit": left["audit"]},
        "note": note_msg,
    }


METHODS = ("POST",)
