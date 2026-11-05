#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collector.py —— 常驻采集进程：定时读 state.json → 降采样入库 → 故障事件检测 → 过期清理。

职责边界（与设计方案一致）：
  * 只读 state.json，只写自己的 SQLite；绝不打开 UIO 设备节点，绝不写硬件
  * 无效测量值一律存 NULL
  * 事件按 (boot_id, code) 去重：同一上电周期内同一故障只建一条事件
  * 启动后第一轮只记基线，不产生事件（避免重启把已有故障当成「新发生」）
"""

import os
import sys
import json
import time
import hashlib
import signal
import logging
from logging.handlers import RotatingFileHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import store          # noqa: E402
import state_reader   # noqa: E402

CFG_PATH = os.environ.get("CABINET_WEB_CONFIG") or os.path.join(HERE, "config.json")
CFG = state_reader.load_config(CFG_PATH)

STATE_JSON = CFG["paths"]["state_json"]
DB_PATH = CFG["paths"]["db"]
LOG_DIR = CFG["paths"]["log"]
CCOL = CFG["collector"]

# 故障等级表 —— 本项目唯一的业务判断，其余全是搬运
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

# 参与 deadband 判定的离散字段
DISCRETE = ["link_ok", "mode", "alarm", "action", "inhibit", "configured",
            "faults", "latched", "frame_state"]

_running = True
log = logging.getLogger("collector")


def _stop(signum, frame):
    global _running
    _running = False


def setup_logging():
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    if not os.path.isdir(LOG_DIR):
        os.makedirs(LOG_DIR)
    fh = RotatingFileHandler(os.path.join(LOG_DIR, "collector.log"),
                             maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)


def new_boot_id(uptime_ms):
    raw = "%d|%d" % (int(time.time()), int(uptime_ms or 0))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def event_key(boot_id, code):
    return hashlib.sha1(("%s|%s" % (boot_id, code)).encode("utf-8")).hexdigest()[:32]


def discrete_values(rec):
    values = tuple(tuple(rec.get(k)) if isinstance(rec.get(k), list) else rec.get(k)
                   for k in DISCRETE)
    # Persist validity transitions immediately, even inside the minimum interval.
    return values + (rec.get("current_a") is not None, rec.get("pressure_pa") is not None,
                     rec.get("current_kind"), rec.get("pressure_kind"))


def context_of(rec):
    return {
        "mode": rec.get("mode"), "alarm": rec.get("alarm"), "action": rec.get("action"),
        "inhibit": "YES" if rec.get("inhibit") else "NO",
        "configured": "YES" if rec.get("configured") else "NO",
        "validity": rec.get("validity"),
        "rpm": rec.get("rpm"), "temp_c": rec.get("temp_c"),
        "current_raw": rec.get("current_raw"), "pressure_ok": rec.get("pressure_ok"),
        "current_a": rec.get("current_a"), "pressure_pa": rec.get("pressure_pa"),
        "current_kind": rec.get("current_kind"), "pressure_kind": rec.get("pressure_kind"),
        "frame_state": rec.get("frame_state"), "quality": rec.get("quality"),
        "quality_reasons": rec.get("quality_reasons"),
        "faults_active": rec.get("faults") or [],
        "faults_latched": rec.get("latched") or [],
        "queue": rec.get("queue"), "drops": rec.get("drops"),
        "uptime_ms": rec.get("uptime_ms"),
    }


def to_record(rec, ts):
    feats = rec.get("features")
    return {
        "ts": ts, "ts_iso": store._iso(ts),
        "sequence": rec.get("sequence"),
        "link_ok": rec.get("link_ok") or 0,
        "message": rec.get("message"),
        "mode": rec.get("mode"),
        "alarm": rec.get("alarm"),
        "action": rec.get("action"),
        "inhibit": rec.get("inhibit"),
        "configured": rec.get("configured"),
        "uptime_ms": rec.get("uptime_ms"),
        # ★ 无效值保持 None → 存 NULL
        "rpm": rec.get("rpm"),
        "temp_c": rec.get("temp_c"),
        "current_raw": rec.get("current_raw"),
        "current_a": rec.get("current_a"),
        "pressure_pa": rec.get("pressure_pa"),
        "current_kind": rec.get("current_kind"),
        "pressure_kind": rec.get("pressure_kind"),
        "pwm": rec.get("pwm"),
        "pressure_ok": rec.get("pressure_ok"),
        "validity": rec.get("validity"),
        "faults": ", ".join(rec.get("faults") or []) or None,
        "latched": ", ".join(rec.get("latched") or []) or None,
        "queue": rec.get("queue"),
        "drops": rec.get("drops"),
        "frame_id": rec.get("frame_id"),
        "frame_age_ms": rec.get("frame_age_ms"),
        "frame_state": rec.get("frame_state"),
        "quality": rec.get("quality"),
        "quality_reasons": rec.get("quality_reasons"),
        "feature_count": rec.get("feature_count") or 0,
        "features_json": (json.dumps(feats, ensure_ascii=False) if feats else None),
    }


class Collector(object):
    def __init__(self, con):
        self.con = con
        self.boot_id = None
        self.prev_faults = None      # None = 还没建立基线
        self.prev_disc = None
        self.prev_meas = {}
        self.last_write = 0.0
        self.last_purge = time.time()
        self.prev_uptime = None
        self.n_snap = 0
        self.n_evt = 0

    # ------------------------------------------------------------ 入库判定
    def _should_store(self, rec, ts):
        mode = CCOL.get("store_mode", "deadband")
        if mode == "every":
            return True
        if self.prev_disc is None:
            return True

        disc = discrete_values(rec)
        if disc != self.prev_disc:
            # 状态变化必须记录，不受下面的最小间隔限制
            return True

        # Rate-limit measurement changes; discrete/validity changes bypass it.
        min_gap = float(CCOL.get("min_write_interval_s", 0) or 0)
        if min_gap > 0 and (ts - self.last_write) < min_gap:
            return False

        db = CCOL.get("deadband") or {}
        for field, thr in db.items():
            # 跳过配置里用下划线写的注释键
            if field.startswith("_") or not isinstance(thr, (int, float)):
                continue
            cur, prev = rec.get(field), self.prev_meas.get(field)
            if cur is None and prev is None:
                continue
            if cur is None or prev is None:
                return True
            if abs(float(cur) - float(prev)) >= float(thr):
                return True

        if (ts - self.last_write) >= CCOL.get("heartbeat_s", 10):
            return True
        return False

    # ------------------------------------------------------------ 事件检测
    def _detect_events(self, rec, ts):
        cur = set(rec.get("faults") or [])
        if self.prev_faults is None:
            self.prev_faults = cur
            log.info("建立故障基线: %s" % (sorted(cur) or "无"))
            return

        new = cur - self.prev_faults
        gone = self.prev_faults - cur

        ctx = context_of(rec)
        for code in sorted(new):
            sev = FAULT_LEVEL.get(code, 1)
            key = event_key(self.boot_id, code)
            eid, created = store.upsert_event_open(
                self.con, key, self.boot_id, code, "PL", sev, ts, ctx)
            if created:
                self.n_evt += 1
                log.info("新事件 #%d %s (severity=%d)" % (eid, code, sev))
        for code in sorted(gone):
            key = event_key(self.boot_id, code)
            if store.recover_event(self.con, key, ts):
                log.info("事件恢复 %s" % code)

        self.prev_faults = cur

    # ------------------------------------------------------------ 主循环
    def tick(self):
        ts = time.time()
        rec, age, err = state_reader.read_state(STATE_JSON)

        # An outage is a gap, not another measurement with a new timestamp.
        # Store one NULL marker so historical carry-forward stops at the gap.
        # Do not infer fault recovery from an unavailable source.
        if err or not rec.get("link_ok") or not 0 <= age < state_reader.MAX_STATE_AGE_MS:
            if self.prev_disc is None or self.prev_disc[0] != 0:
                missing = state_reader.derive(None)
                missing["message"] = err or "SOURCE_UNAVAILABLE"
                missing["validity"] = "RPM:0 ADC:0 TEMP:0 PRESS:0"
                store.insert_snapshot(self.con, to_record(missing, ts))
                self.n_snap += 1
                self.last_write = ts
                self.prev_disc = discrete_values(missing)
                self.prev_meas = {}
                log.warning("Source unavailable; one NULL gap recorded")
            return

        # 上电周期检测：uptime 回退说明对方重启了
        up = rec.get("uptime_ms")
        if up is not None and self.prev_uptime is not None and up < self.prev_uptime - 2000:
            self.boot_id = new_boot_id(up)
            store.set_meta(self.con, "boot_id", self.boot_id)
            self.prev_faults = None
            log.info("检测到上电周期变化 → 新 boot_id=%s" % self.boot_id)
        self.prev_uptime = up

        if err:
            if self.prev_disc is None or self.prev_disc[0] != 0:
                log.warning("state.json 不可用: %s" % err)

        if self._should_store(rec, ts):
            rid = store.insert_snapshot(self.con, to_record(rec, ts))
            self.n_snap += 1
            self.last_write = ts
            # Compare deadband to the last stored sample so slow drift accumulates.
            self.prev_meas = {field: rec.get(field)
                              for field in (CCOL.get("deadband") or {})}
            store.set_meta(self.con, "last_snapshot_at", store._iso(ts))
            if self.n_snap <= 3 or self.n_snap % 60 == 0:
                log.info("快照 #%d (id=%s) mode=%s rpm=%s temp=%s faults=%s" % (
                    self.n_snap, rid, rec.get("mode"), rec.get("rpm"),
                    rec.get("temp_c"), rec.get("faults")))

        self._detect_events(rec, ts)

        self.prev_disc = discrete_values(rec)

        # 过期清理
        if (ts - self.last_purge) >= CCOL.get("purge_check_interval_s", 600):
            self.do_purge(ts)
            self.last_purge = ts

    def do_purge(self, ts):
        days = CCOL.get("retain_days", 7)
        ev_days = CCOL.get("retain_events_days", 30)
        before = ts - days * 86400.0
        try:
            deleted = store.purge(self.con, before, ["snapshots"], "system",
                                  "auto retention %d days" % days)

            # ★ retain_events_days 之前只是写在配置里、从没被用过。
            #   事件单独按更长的周期保留（它是故障证据，比快照重要）。
            try:
                ev_deleted = store.purge(self.con, ts - ev_days * 86400.0, ["events"],
                                         "system", "auto retention events %d days" % ev_days)
                for k, v in ev_deleted.items():
                    deleted[k] = deleted.get(k, 0) + v
            except Exception as e:
                log.warning("事件清理失败: %s" % e)

            store.set_meta(self.con, "last_purge_at", store._iso(ts))
            if any(deleted.values()):
                log.info("自动清理: %s" % deleted)
                # ★ 删完必须 VACUUM，否则 auto_vacuum=0 下文件永远不缩，
                #   只会留下一堆 freelist 空洞（板子上实测 98% 是空的）。
                did, b, a = store.compact(
                    self.con,
                    free_ratio=float(CCOL.get("compact_free_ratio", 0.25)),
                    min_bytes=int(CCOL.get("compact_min_bytes", 524288)))
                if did:
                    log.info("压缩数据库: %.2f MB -> %.2f MB（省 %.2f MB）"
                             % (b / 1048576.0, a / 1048576.0, (b - a) / 1048576.0))
        except Exception as e:
            log.warning("自动清理失败: %s" % e)


def main():
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    setup_logging()

    con = store.connect(DB_PATH)
    if not store.integrity_ok(con):
        con.close()
        bad = DB_PATH + ".corrupt.%d" % int(time.time())
        os.rename(DB_PATH, bad)
        log.error("数据库完整性校验失败 → 已改名为 %s 并重建空库" % bad)
        con = store.connect(DB_PATH)
    store.init_schema(con)

    boot_id = store.get_meta(con, "boot_id")
    col = Collector(con)
    col.boot_id = boot_id or new_boot_id(None)
    store.set_meta(con, "boot_id", col.boot_id)
    store.set_meta(con, "collector_started_at", store._iso(time.time()))

    log.info("采集器启动 pid=%d boot_id=%s db=%s mode=%s interval=%.1fs" % (
        os.getpid(), col.boot_id, DB_PATH, CCOL.get("store_mode"),
        CCOL.get("sample_interval_s", 1.0)))

    interval = float(CCOL.get("sample_interval_s", 1.0))
    n = 0
    while _running:
        t0 = time.time()
        try:
            col.tick()
            n += 1
        except Exception:
            log.exception("tick 异常")
        dt = time.time() - t0
        time.sleep(max(0.05, interval - dt))

    log.info("采集器停止，共 %d 轮 / %d 快照 / %d 新事件" % (n, col.n_snap, col.n_evt))
    con.close()


if __name__ == "__main__":
    main()
