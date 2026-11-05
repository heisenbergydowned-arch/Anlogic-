#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mock_device.py —— 机柜风冷边缘智能测控系统的数据源模拟器（两种模式）

  sim_mode = "random"    （默认）随机过程模拟：转速走 OU 均值回复随机游走、
                          温度一阶热滞后跟随转速、电流与转速相关；
                          传感器随机掉线 → 自然产生 null 缺口；
                          故障按状态条件随机触发（温度高了才可能 TEMP_WARN）。
  sim_mode = "scripted"  固定 7 幕剧本，便于演示确定性的剧情。

两种模式都按真实 state.json 的结构与节奏（每 tick_ms 原子重写）产出。

★ 这是唯一「产生数据」的地方。采集器 collector.py 只读不写。
★ 通过 data/mock_cmd.json 接受控制指令（由 /api/mock 写入），
  真机上把 config.json 的 mock.enabled 改成 false 即可完全停用。
"""

import os
import sys
import json
import math
import time
import random
import signal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

CFG_PATH = os.environ.get("CABINET_WEB_CONFIG") or os.path.join(HERE, "config.json")
with open(CFG_PATH, "r", encoding="utf-8") as _f:
    CFG = json.load(_f)

STATE_PATH = CFG["mock"]["state_json"]
CMD_FILE = CFG["mock"]["cmd_file"]
TICK = CFG["mock"].get("tick_ms", 100) / 1000.0
NOMINAL_RPM = 2400.0

_running = True

# 故障等级（与 collector.py 保持一致）
FAULT_LEVEL = {
    "OC_HARD": 3, "TEMP_HARD": 3, "CURRENT_PROTECTION_LOST": 3,
    "STALL_CORROBORATED": 3, "OVERSPEED": 3, "VIB_HARD": 3,
    "CURRENT_HIGH": 2, "TEMP_WARN": 2, "TEMP_LOSS": 2, "FG_LOSS": 2,
    "START_FAIL": 2, "VIB_WARN": 2, "PS_LOSS": 2, "CMD_EXPIRED": 2,
    "TRACK_ERROR": 2,
    "DIAG_LOSS": 1, "AUX_LOSS": 1, "CONFIG_UNQUALIFIED": 1,
    "STOP_UNCONFIRMED": 1, "SOFT_EXPIRED": 1,
    "SOFT_PS": 0,
}


def _stop(signum, frame):
    global _running
    _running = False


def _fmt(v, n=2):
    """None -> '--'（★ 绝不用 0 代替缺失值）"""
    return "--" if v is None else (("%." + str(n) + "f") % v)


def _alarm_of(faults):
    return max([FAULT_LEVEL.get(x, 1) for x in faults] or [0])


# =================================================================== 基类

class BaseSim(object):
    def __init__(self):
        self.uptime0 = time.time()
        self.sequence = 0
        self.frame_id = 0
        self.frame_seen = 0.0
        self.queue = 0
        self.drops = 0
        # 手动覆盖项（由 /api/mock 写入）
        self.ovr_faults = None
        self.ovr_sensors = None
        self.ovr_mode = None
        self.ovr_configured = None
        self.ovr_alarm = None
        self.ovr_target_rpm = None
        self.frozen = False
        self.rnd = random.Random(CFG["mock"].get("seed"))
        self.name = "base"

    # ---------------------------------------------------------- 控制指令
    def apply_cmd(self, cmd):
        act = cmd.get("action")
        if act == "reset":
            self.reset()
            return "场景已重置"
        if act == "inject_fault":
            code = str(cmd.get("code") or "TEMP_HARD").upper()
            cur = list(self.base_faults())
            if code not in cur:
                cur.append(code)
            self.ovr_faults = cur
            return "已注入故障 %s" % code
        if act == "clear_faults":
            self.ovr_faults = []
            self.ovr_alarm = 0
            self.clear_internal_faults()
            return "已清除全部故障"
        if act == "sensors":
            self.ovr_sensors = bool(cmd.get("online"))
            return "传感器%s" % ("上线" if self.ovr_sensors else "离线")
        if act == "set_mode":
            self.ovr_mode = str(cmd.get("mode") or "RUNNING").upper()
            return "模式设为 %s" % self.ovr_mode
        if act == "set_configured":
            self.ovr_configured = bool(cmd.get("configured"))
            return "configured=%s" % self.ovr_configured
        if act == "set_target_rpm":
            try:
                self.ovr_target_rpm = float(cmd.get("rpm"))
            except (TypeError, ValueError):
                return "rpm 非法"
            self.set_target(self.ovr_target_rpm)
            return "目标转速设为 %.0f rpm" % self.ovr_target_rpm
        if act == "freeze":
            self.frozen = bool(cmd.get("on", True))
            return "画面已%s" % ("冻结" if self.frozen else "恢复")
        return None   # 子类可扩展

    # 供子类覆写的钩子
    def reset(self):
        pass

    def base_faults(self):
        return []

    def clear_internal_faults(self):
        pass

    def set_target(self, rpm):
        pass

    def step(self, now):
        raise NotImplementedError


# =================================================================== 随机模式

class RandomSim(BaseSim):
    """随机过程模拟：看起来像真实遥测，而不是脚本曲线。"""

    def __init__(self):
        BaseSim.__init__(self)
        self.name = "random"
        self.rc = CFG["mock"]["random"]

        self.rpm = 0.0
        self.temp = self.rc["temp"]["base_c"]
        self.current = 0.0
        self.ambient = 0.0
        self.target_rpm = 0.0
        self.next_target = time.time() + 3.0
        self.dropping = False
        self.dropout_until = 0.0
        self.faults = {}       # code -> 恢复时刻
        self.latched = {}      # code -> 锁存到期时刻
        self.last = time.time()

    def reset(self):
        RandomSim.__init__(self)

    def clear_internal_faults(self):
        self.faults = {}
        self.latched = {}

    def set_target(self, rpm):
        self.target_rpm = float(rpm)

    def base_faults(self):
        return sorted(self.faults)

    @staticmethod
    def _cond_ok(cond, vals):
        if not cond:
            return True
        field, op, thr = cond
        v = vals.get(field)
        if v is None:
            return False
        return (v > thr) if op == ">" else (v < thr)

    def step(self, now):
        dt = max(0.001, min(1.0, now - self.last))
        self.last = now
        r = self.rnd
        rc = self.rc

        # ---- 目标转速随机跳变（模拟负载 / 档位切换）----
        if now >= self.next_target:
            self.target_rpm = float(r.choice(rc["rpm"]["targets"]))
            lo, hi = rc["rpm"]["target_hold_s"]
            self.next_target = now + r.uniform(lo, hi)
        if self.ovr_target_rpm is not None:
            self.target_rpm = self.ovr_target_rpm

        # ---- 转速：Ornstein-Uhlenbeck 均值回复随机游走 ----
        p = rc["rpm"]
        self.rpm += (p["theta"] * (self.target_rpm - self.rpm) * dt
                     + p["sigma"] * math.sqrt(dt) * r.gauss(0, 1))
        self.rpm = max(p["min"], min(p["max"], self.rpm))

        # ---- 环境温度：慢速随机漂移 ----
        t = rc["temp"]
        self.ambient += (-self.ambient / t["ambient_tau_s"] * dt
                         + t["ambient_sigma"] * math.sqrt(dt) * r.gauss(0, 1))

        # ---- 温度：一阶热滞后（跟随转速负载 + 环境）----
        load = self.rpm / NOMINAL_RPM
        t_target = t["base_c"] + t["gain_c"] * load + self.ambient
        self.temp += ((t_target - self.temp) / t["tau_s"] * dt
                      + t["sigma"] * math.sqrt(dt) * r.gauss(0, 1))

        # ---- 电流：与转速相关（一阶滞后 + 噪声）----
        c = rc["current"]
        c_target = c["at_nominal"] * load
        self.current += ((c_target - self.current) / c["tau_s"] * dt
                         + c["sigma"] * math.sqrt(dt) * r.gauss(0, 1))
        self.current = max(0.0, min(float(c["full_scale"]), self.current))

        # ---- 传感器随机掉线 → 自然产生 null 缺口 ----
        d = rc["dropout"]
        if self.dropping:
            if now >= self.dropout_until:
                self.dropping = False
        elif r.random() < d["rate_per_s"] * dt:
            self.dropping = True
            self.dropout_until = now + r.uniform(d["dur_s"][0], d["dur_s"][1])

        sensors = (not self.dropping)
        if self.ovr_sensors is not None:
            sensors = self.ovr_sensors

        vals = {
            "rpm": self.rpm if sensors else None,
            "temp_c": self.temp if sensors else None,
            "current_raw": self.current if sensors else None,
        }

        # ---- 故障：按状态条件随机触发 / 随机恢复 ----
        for code, spec in rc["faults"].items():
            # config 里用 "_note" 之类的下划线键写注释，必须跳过
            if code.startswith("_") or not isinstance(spec, dict):
                continue
            if code in self.faults:
                if now >= self.faults[code]:
                    del self.faults[code]
                    if FAULT_LEVEL.get(code, 1) >= 3:
                        self.latched[code] = now + 120.0   # L3 锁存 2 分钟
            elif self._cond_ok(spec.get("condition"), vals):
                if r.random() < spec["rate"] * dt:
                    self.faults[code] = now + r.expovariate(1.0 / spec["dwell_s"])

        for code in list(self.latched):
            if now >= self.latched[code]:
                del self.latched[code]

        faults = sorted(self.faults)
        if self.ovr_faults is not None:
            faults = sorted(self.ovr_faults)
        latched = sorted(set(list(self.latched)
                             + [x for x in faults if FAULT_LEVEL.get(x, 1) >= 3]))

        # ---- 模式：由状态推导 ----
        configured = True if self.ovr_configured is None else self.ovr_configured
        if not configured:
            mode = "READY_OFF"
        elif self.rpm < 60.0 and self.target_rpm <= 0.0:
            mode = "READY_OFF"
        elif abs(self.rpm - self.target_rpm) > 150.0:
            mode = "STARTING"
        else:
            mode = "RUNNING"
        if self.ovr_mode:
            mode = self.ovr_mode

        alarm = _alarm_of(faults)
        if self.ovr_alarm is not None:
            alarm = self.ovr_alarm
        action = "INHIBIT" if alarm >= 3 else ("DERATE" if alarm == 2 else "NONE")

        if not configured:
            message = "WAITING FOR CONFIGURATION"
        elif not sensors:
            message = "SENSOR DROPOUT"
        elif alarm >= 3:
            message = "FAULT · INHIBIT"
        elif alarm == 2:
            message = "DERATE ACTIVE"
        elif alarm == 1:
            message = "MAINTENANCE ADVISORY"
        elif mode == "STARTING":
            message = "SPINNING UP"
        else:
            message = "NOMINAL"

        info = {
            "sim_mode": "random",
            "target_rpm": round(self.target_rpm, 1),
            "ambient_c": round(self.ambient, 2),
            "dropping": bool(self.dropping),
            "active_faults": faults,
            "latched": latched,
        }
        return build_state(self, now, sensors, vals["rpm"], vals["temp_c"],
                           vals["current_raw"], faults, latched, mode, action,
                           configured, alarm, message, info)


# =================================================================== 脚本模式

PHASES = [
    dict(name="冷启动 · 未配置", dur=25,
         configured=False, sensors=False, mode="READY_OFF", alarm=1,
         faults=["DIAG_LOSS", "AUX_LOSS", "CONFIG_UNQUALIFIED"],
         message="WAITING FOR CONFIGURATION"),
    dict(name="配置合格 · 等待采样", dur=20,
         configured=True, sensors=False, mode="READY_OFF", alarm=1,
         faults=["DIAG_LOSS"], message="WAITING FOR SAMPLES"),
    dict(name="传感器上线 · 启动", dur=30,
         configured=True, sensors=True, mode="STARTING", alarm=0,
         faults=[], message="SPINNING UP",
         rpm=(0, 2400), temp=(25.0, 42.0), current=(0, 480)),
    dict(name="正常运行", dur=60,
         configured=True, sensors=True, mode="RUNNING", alarm=0,
         faults=[], message="NOMINAL",
         rpm=(2400, 2400), temp=(42.0, 42.0), current=(480, 480), jitter=True),
    dict(name="温度预警", dur=30,
         configured=True, sensors=True, mode="RUNNING", alarm=2,
         faults=["TEMP_WARN"], message="TEMP WARNING",
         rpm=(2400, 2650), temp=(42.0, 58.0), current=(480, 560), jitter=True),
    dict(name="温度硬故障", dur=30,
         configured=True, sensors=True, mode="RUNNING", alarm=3,
         faults=["TEMP_WARN", "TEMP_HARD"], message="TEMP HARD LIMIT",
         rpm=(2650, 2850), temp=(58.0, 74.0), current=(560, 700), jitter=True),
    dict(name="故障恢复", dur=30,
         configured=True, sensors=True, mode="RUNNING", alarm=0,
         faults=[], message="RECOVERED",
         rpm=(2850, 2400), temp=(74.0, 44.0), current=(700, 480), jitter=True),
]
TOTAL = sum(p["dur"] for p in PHASES)


class ScriptedSim(BaseSim):
    """固定 7 幕剧本 —— 演示确定性剧情时用。"""

    def __init__(self):
        BaseSim.__init__(self)
        self.name = "scripted"
        self.t0 = time.time()

    def reset(self):
        ScriptedSim.__init__(self)

    def base_faults(self):
        if self.ovr_faults is not None:
            return list(self.ovr_faults)
        return list(self._phase(time.time())[1]["faults"])

    def _phase(self, now):
        tt = (now - self.t0) % TOTAL
        acc = 0.0
        for i, p in enumerate(PHASES):
            if tt < acc + p["dur"]:
                return i, p, (tt - acc) / float(p["dur"])
            acc += p["dur"]
        return len(PHASES) - 1, PHASES[-1], 1.0

    @staticmethod
    def _lerp(rng, prog):
        return None if not rng else rng[0] + (rng[1] - rng[0]) * prog

    def apply_cmd(self, cmd):
        if cmd.get("action") == "jump_phase":
            idx = int(cmd.get("phase", 0)) % len(PHASES)
            acc = sum(p["dur"] for p in PHASES[:idx])
            self.t0 = time.time() - acc
            self.ovr_faults = None
            self.ovr_sensors = None
            self.ovr_mode = None
            self.ovr_configured = None
            self.ovr_alarm = None
            return "已跳到第 %d 幕：%s" % (idx + 1, PHASES[idx]["name"])
        return BaseSim.apply_cmd(self, cmd)

    def step(self, now):
        idx, p, prog = self._phase(now)

        configured = self.ovr_configured if self.ovr_configured is not None else p["configured"]
        sensors = self.ovr_sensors if self.ovr_sensors is not None else p["sensors"]
        mode = self.ovr_mode or p["mode"]
        faults = self.base_faults()
        alarm = self.ovr_alarm if self.ovr_alarm is not None else p["alarm"]
        if self.ovr_faults is not None:
            alarm = _alarm_of(faults)
        action = "INHIBIT" if alarm >= 3 else ("DERATE" if alarm == 2 else "NONE")

        rpm = temp_c = current = None
        if sensors:
            rpm = self._lerp(p.get("rpm"), prog)
            temp_c = self._lerp(p.get("temp"), prog)
            current = self._lerp(p.get("current"), prog)
            if p.get("jitter"):
                # ★ 抖动幅度必须小于 deadband 阈值，否则噪声会被当成真实变化
                rpm += math.sin(now * 0.7) * 3.5 + self.rnd.uniform(-1.5, 1.5)
                temp_c += math.sin(now * 0.31) * 0.10 + self.rnd.uniform(-0.04, 0.04)
                current += math.sin(now * 0.53) * 2.0 + self.rnd.uniform(-1.0, 1.0)
            if self.ovr_target_rpm is not None:
                rpm = self.ovr_target_rpm + math.sin(now * 0.7) * 3.5

        info = {"sim_mode": "scripted", "phase_index": idx, "phase": p["name"],
                "elapsed_s": round(prog * p["dur"], 2), "phase_dur_s": p["dur"],
                "cycle_elapsed_s": round((now - self.t0) % TOTAL, 2),
                "total_cycle_s": TOTAL, "phases": [x["name"] for x in PHASES]}
        return build_state(self, now, sensors, rpm, temp_c, current, faults, [],
                           mode, action, configured, alarm, p["message"], info)


# =================================================================== 统一产出

def build_state(sim, now, sensors, rpm, temp_c, current, faults, latched,
                mode, action, configured, alarm, message, info):
    """★ 无效值一律 None → JSON null；display 里显示 '--'。"""
    if sensors and (now - sim.frame_seen) > 0.5:
        sim.frame_seen = now
        sim.frame_id += 1
    frame_state = "RECEIVED_REAL" if sensors else "EMPTY"
    frame_age_ms = int((now - sim.frame_seen) * 1000) if sensors else None

    features = None
    if sensors and sim.frame_id:
        base = (rpm or 0.0) / NOMINAL_RPM
        features = [round(base * (1.0 + 0.25 * math.sin(now * 0.3 + i * 0.7))
                          + sim.rnd.uniform(-0.02, 0.02), 5) for i in range(39)]

    if sim.rnd.random() < 0.01:
        sim.drops += 1

    quality = None if not sensors else ("GOOD" if not faults else "DEGRADED")
    quality_reasons = ("no frame" if not sensors
                       else ("; ".join(faults) if faults else "ok"))
    validity = "RPM:%d ADC:%d TEMP:%d PRESS:%d" % (
        (1 if sensors else 0), (1 if sensors else 0),
        (1 if sensors else 0), (1 if sensors else 0))

    display = {
        "message": message,
        "mode": mode,
        "alarm": str(int(alarm)),
        "action": action,
        "inhibit": "YES" if action == "INHIBIT" else "NO",
        "configured": "YES" if configured else "NO",
        "uptime_ms": str(int((now - sim.uptime0) * 1000)),
        "sequence": str(sim.sequence),
        "validity": validity,
        "rpm": "--" if rpm is None else str(int(round(rpm))),
        "temp": _fmt(temp_c),
        "current": "--" if current is None else str(int(round(current))),
        "pressure": "OK" if sensors else "--",
        "frame_state": frame_state,
        "frame_id": str(sim.frame_id),
        "frame_age": "--" if frame_age_ms is None else str(frame_age_ms),
        "quality": quality or "--",
        "quality_reasons": quality_reasons,
        "queue": str(sim.queue),
        "drops": str(sim.drops),
        "faults": ", ".join(faults) if faults else "NONE",
        "latched": ", ".join(latched) if latched else "NONE",
        "feature_count": str(len(features) if features else 0),
    }
    for i in range(39):
        display["feature_%02d" % i] = "--" if not features else ("%.5f" % features[i])

    req = sim.ovr_target_rpm
    if req is None:
        req = info.get("target_rpm", rpm or 0)
    status = {
        "uptime_ms": int((now - sim.uptime0) * 1000),
        "mode": mode,
        "applied_pwm_counts": int((rpm or 0) / 10.0),
        "requested_rpm": int(round(float(req or 0))),
        "measured_rpm": int(round(rpm)) if rpm is not None else 0,
        "temp_raw_1_16_C": int(round(temp_c * 16.0)) if temp_c is not None else 0,
        "current_distance_raw_code": int(round(current)) if current is not None else 0,
        "configuration_id": 0x1A2B if configured else 0,
    }

    return {
        "display": display,
        "observation": {
            "status": status,
            "mailbox_before_read": 0,
            "frame": ({"id": sim.frame_id, "age_ms": frame_age_ms or 0,
                       "state": frame_state, "features": features} if sensors else None),
        },
        "_mock": info,
    }


def write_state(st):
    d = os.path.dirname(STATE_PATH)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    tmp = STATE_PATH + ".tmp.%d" % os.getpid()
    with open(tmp, "wb") as f:
        f.write(json.dumps(st, ensure_ascii=False).encode("utf-8"))
    os.replace(tmp, STATE_PATH)   # ★ 原子替换：读侧永远看到完整 JSON


# =================================================================== 主循环

def make_sim(mode_name):
    return RandomSim() if mode_name == "random" else ScriptedSim()


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    sim = make_sim(CFG["mock"].get("sim_mode", "random"))
    print("[mock] sim_mode=%s  state -> %s (tick %.0f ms)"
          % (sim.name, STATE_PATH, TICK * 1000), flush=True)

    n = 0
    while _running:
        if os.path.exists(CMD_FILE):
            try:
                with open(CMD_FILE, "r", encoding="utf-8") as f:
                    cmd = json.load(f)
                os.remove(CMD_FILE)
                act = cmd.get("action")
                if act == "set_sim_mode":
                    want = str(cmd.get("mode") or "random")
                    if want != sim.name:
                        sim = make_sim(want)
                        print("[mock] 切换模式 -> %s" % sim.name, flush=True)
                    msg = "已切到 %s 模式" % sim.name
                else:
                    msg = sim.apply_cmd(cmd)
                    if msg is None:
                        msg = "当前模式不支持该指令: %s" % act
                print("[mock] cmd %s -> %s" % (act, msg), flush=True)
            except Exception as e:
                print("[mock] cmd error: %s" % e, flush=True)
                try:
                    os.remove(CMD_FILE)
                except OSError:
                    pass

        if sim.frozen:
            time.sleep(TICK)
            continue

        sim.sequence += 1
        write_state(sim.step(time.time()))
        n += 1
        time.sleep(TICK)

    print("[mock] stopped after %d ticks" % n, flush=True)


if __name__ == "__main__":
    main()
