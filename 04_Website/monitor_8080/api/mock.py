# -*- coding: utf-8 -*-
"""
/api/mock —— 模拟器控制（★ 仅本地原型可用）

真机上 mock.enabled=false 时本接口一律返回 403，
前端也会自动隐藏「模拟器控制」面板。

这里操作的是**模拟器**，不是硬件 —— 真机上的保护阈值/PWM/继电器
一律不允许从网页修改。
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import apicommon  # noqa: E402

ACTIONS = ("reset", "jump_phase", "inject_fault", "clear_faults",
           "sensors", "set_mode", "set_configured", "set_target_rpm",
           "freeze", "set_sim_mode")


def _guard():
    if not apicommon.cfg().get("mock", {}).get("enabled"):
        raise apicommon.HttpError(403, "mock_disabled",
                                "模拟器已关闭（真机模式），本接口不可用")


def handle():
    _guard()
    cfg = apicommon.cfg()
    method = apicommon.require_method("GET", "POST")

    if method == "GET":
        rec, age, err = apicommon.state_reader.read_state(cfg["paths"]["state_json"])
        raw, _, _ = apicommon.state_reader.read_raw(cfg["paths"]["state_json"])
        info = (raw or {}).get("_mock") or {}
        return {"ok": True, "mock": True, "info": info,
                "actions": list(ACTIONS), "state_age_ms": age, "state_error": err}

    body = apicommon.body_json()
    action = str(body.get("action") or "").strip()
    if action not in ACTIONS:
        raise apicommon.HttpError(400, "bad_action",
                                "action 必须是 %s 之一" % "/".join(ACTIONS))

    cmd_path = cfg["mock"]["cmd_file"]
    d = os.path.dirname(cmd_path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    tmp = cmd_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
    os.replace(tmp, cmd_path)

    # 记审计：即使只是操作模拟器，也让审计链路可见
    who = apicommon.actor()
    detail = json.dumps({k: v for k, v in body.items() if k != "action"},
                        ensure_ascii=False)
    con = apicommon.open_store()
    try:
        apicommon.store.add_audit(con, who, "mock:" + action, "simulator", detail, 1)
    finally:
        con.close()

    return {"ok": True, "action": action, "detail": detail,
            "note": "指令已投递给模拟器，下一 tick 生效；真机上无此接口"}


METHODS = ("GET", "POST")
