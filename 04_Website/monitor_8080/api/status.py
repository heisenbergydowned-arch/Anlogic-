# -*- coding: utf-8 -*-
"""GET /api/status —— 实时状态（state.json 原文 + 派生字段）。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import apicommon  # noqa: E402


def handle():
    cfg = apicommon.cfg()
    rec, age, err = apicommon.state_reader.read_state(cfg["paths"]["state_json"])
    sr = apicommon.state_reader

    derived = {
        "link_ok": bool(rec.get("link_ok")),
        "alarm_level": rec.get("alarm"),
        "inhibit": bool(rec.get("inhibit")),
        "configured": bool(rec.get("configured")),
        "mode": rec.get("mode"),
        "action": rec.get("action"),
        "message": rec.get("message"),
        "uptime_ms": rec.get("uptime_ms"),
        "sequence": rec.get("sequence"),
        # ★ 无效测量值一律 null，前端显示 `--`，绝不显示 0
        "rpm": rec.get("rpm"),
        "temp_c": rec.get("temp_c"),
        "current_raw": rec.get("current_raw"),
        "current_a": rec.get("current_a"),
        "pressure_pa": rec.get("pressure_pa"),
        "current_kind": rec.get("current_kind"),
        "pressure_kind": rec.get("pressure_kind"),
        "pressure_ok": bool(rec.get("pressure_ok")),
        "environment_state": rec.get("environment_state"),
        "environment_hardware_profile": rec.get("environment_hardware_profile"),
        "aht_valid": bool(rec.get("aht_valid")),
        "inlet_temperature_c": rec.get("inlet_temperature_c"),
        "relative_humidity_pct": rec.get("relative_humidity_pct"),
        "validity": sr.parse_validity(rec.get("validity")),
        "validity_raw": rec.get("validity"),
        "faults_active": rec.get("faults") or [],
        "faults_latched": rec.get("latched") or [],
        "frame_state": rec.get("frame_state"),
        "frame_id": rec.get("frame_id"),
        "frame_age_ms": rec.get("frame_age_ms"),
        "quality": rec.get("quality"),
        "quality_reasons": rec.get("quality_reasons"),
        "queue": rec.get("queue"),
        "drops": rec.get("drops"),
        "feature_count": rec.get("feature_count") or 0,
        "has_valid_frame": bool(rec.get("has_valid_frame")),
    }

    mock_info = None
    try:
        raw, _, _ = sr.read_raw(cfg["paths"]["state_json"])
        if raw and isinstance(raw.get("_mock"), dict):
            mock_info = raw["_mock"]
    except Exception:
        mock_info = None

    return {
        "ok": True,
        "state_age_ms": age,
        "state_error": err,
        "display": rec.get("display") or {},
        "derived": derived,
        "features": rec.get("features"),
        "mock": mock_info,
    }


METHODS = ("GET",)
