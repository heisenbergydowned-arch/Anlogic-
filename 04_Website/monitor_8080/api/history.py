# -*- coding: utf-8 -*-
"""GET /api/history —— 历史快照聚合（SQLite 3.22 无窗口函数，用 GROUP BY 实现）。"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import apicommon  # noqa: E402


def handle():
    cfg = apicommon.cfg()
    qs = apicommon.query()

    now = time.time()
    ts_to = apicommon.store.parse_time(apicommon.q1(qs, "to")) or now
    ts_from = apicommon.store.parse_time(apicommon.q1(qs, "from")) or (ts_to - 3600.0)
    if ts_from > ts_to:
        ts_from, ts_to = ts_to, ts_from

    max_points = apicommon.qint(qs, "max_points", cfg["api"]["default_points"],
                              1, cfg["api"]["max_points"])
    fields_raw = apicommon.q1(qs, "fields")
    fields = [f.strip() for f in fields_raw.split(",")] if fields_raw else None
    # 显式给默认值，不依赖 store.query_history 的默认参数
    # （pwm 与 HDMI 界面的 PWM 曲线同源：applied_pwm_counts / 4000 * 100）
    if not fields:
        fields = ["pwm", "temp_c", "rpm", "current_a", "pressure_pa", "current_raw", "alarm"]

    # deadband 沿用上限：3 倍心跳。超过这个时长仍无新行，就认为数据真的断了
    max_hold = float(cfg["collector"].get("heartbeat_s", 10)) * 3.0

    # 分辨率：bucket 省略 / 0 / auto → 自动（窗口÷max_points）；也可显式给秒数
    bucket_raw = apicommon.q1(qs, "bucket")
    bucket = None
    if bucket_raw not in (None, "", "0", "auto"):
        try:
            bucket = float(bucket_raw)
        except ValueError:
            raise apicommon.HttpError(400, "bad_param", "bucket 必须是秒数或 auto")
        if bucket <= 0:
            bucket = None

    con = apicommon.open_store()
    try:
        agg = apicommon.store.query_history(con, ts_from, ts_to, max_points, fields,
                                          max_hold_s=max_hold, bucket_s=bucket)
        bounds = apicommon.store.snapshot_bounds(con)
    finally:
        con.close()

    agg["ok"] = True
    agg["from"] = apicommon.store._iso(ts_from)
    agg["to"] = apicommon.store._iso(ts_to)
    agg["bounds"] = bounds
    # 窗口比库里已有数据还宽时，前端应提示「左侧为空」
    if bounds and bounds["first"] > ts_from:
        agg["window_note"] = ("查询窗口左侧 %.0f 秒早于库中最早数据，那一段是真的没有记录"
                              % (bounds["first"] - ts_from))

    # ★ 这个端点的响应体最大（601 桶 × 13 数组 ≈ 29KB）。
    #   全局 json_bytes 用 indent=2 美化，会把它膨胀到 85KB（56KB 是空格和换行）。
    #   通过 WiFi + 板子 CPU 高负载时，每 15 秒拉 85KB 会让页面明显卡顿。
    #   这里单独返回紧凑 JSON：85KB → 29KB，省 66% 带宽。
    return apicommon.Raw(
        json.dumps(agg, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        "application/json")


METHODS = ("GET",)
