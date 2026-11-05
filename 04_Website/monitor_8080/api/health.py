# -*- coding: utf-8 -*-
"""GET /api/health —— 健康检查。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import apicommon  # noqa: E402

VERSION = "1.0.0"


def handle():
    cfg = apicommon.cfg()
    rec, age, err = apicommon.state_reader.read_state(cfg["paths"]["state_json"])

    db_ok = True
    db_rows = None
    last_snap = None
    collector_running = False
    db_err = None
    try:
        con = apicommon.open_store()
        try:
            db_rows = con.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
            last_snap = apicommon.store.get_meta(con, "last_snapshot_at")
        finally:
            con.close()
    except Exception as e:
        db_ok = False
        db_err = e.__class__.__name__

    if last_snap:
        import time as _t
        import datetime as _d
        try:
            dt = _d.datetime.strptime(last_snap, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=_d.timezone.utc)
            collector_running = (_t.time() - dt.timestamp()) < 30
        except ValueError:
            pass

    state_ok = bool(rec.get("link_ok")) and age >= 0 and age < 5000
    ok = bool(db_ok and collector_running and state_ok)

    return {
        "ok": ok,
        "version": VERSION,
        "db_ok": db_ok,
        "db_error": db_err,
        "db_rows": db_rows,
        "state_present": age >= 0,
        "state_age_ms": age,
        "state_ok": state_ok,
        "state_error": err,
        "collector_running": collector_running,
        "collector_last_run_iso": last_snap,
        "mock_enabled": bool(cfg.get("mock", {}).get("enabled")),
    }


METHODS = ("GET",)
