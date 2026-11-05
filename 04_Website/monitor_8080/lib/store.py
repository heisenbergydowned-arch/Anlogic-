# -*- coding: utf-8 -*-
"""
store.py —— SQLite 存储层（建表 / 写入 / 查询 / 清理）

约束：
  * Python 3.6 兼容（不用 walrus / dataclasses / asyncio）
  * SQLite 3.22 兼容（不用 UPSERT / 窗口函数 / RETURNING）
  * 无效值一律存 NULL —— "Zero is a measurement. No measurement is a different condition."

设计要点（来自嵌入式 SQLite 最佳实践）：
  1. WAL + synchronous=NORMAL + busy_timeout，兼顾并发与掉电安全
  2. wal_autocheckpoint 调小到 256 页（≈1MB），防大量 DELETE 后 WAL 撑爆分区
  3. ★ PRAGMA 执行后必须「读回校验」，不一致直接抛错 —— 否则 WAL 会静默退化，
     直到掉电才发现数据丢了
  4. 聚合查询同时返回 sample_count —— 否则「1 分钟只有 4 个采样」和「60 个采样」看起来一样
  5. 备份/导出用 VACUUM INTO，不用 cp（WAL 有 -wal / -shm 伴生文件）
"""

import os
import json
import math
import time
import sqlite3
import datetime

SCHEMA_VERSION = "1.1.0"

# ---------------------------------------------------------------- PRAGMA

# (名字, 期望读回值)
PRAGMA_EXPECT = [
    ("journal_mode", "wal"),
    ("synchronous", 1),          # 1 = NORMAL
    ("busy_timeout", 5000),
    ("foreign_keys", 1),         # 注意：默认是 OFF，必须显式开
    ("temp_store", 2),           # 2 = MEMORY
    ("wal_autocheckpoint", 256),  # 256 页 ≈ 1 MB（默认 1000 页 ≈ 4 MB）
    ("mmap_size", 16777216),     # 16 MB
]


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value):
    """接受 ISO8601（带 Z 或 +00:00）或 Unix 秒，返回 float。失败返回 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    try:
        return float(s)
    except ValueError:
        pass
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(t, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return None


DDL = [
    """
    CREATE TABLE IF NOT EXISTS snapshots (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        ts               REAL    NOT NULL,
        ts_iso           TEXT    NOT NULL,
        sequence         INTEGER,
        link_ok          INTEGER NOT NULL,
        message          TEXT,
        mode             TEXT,
        alarm            INTEGER,
        action           TEXT,
        inhibit          INTEGER,
        configured       INTEGER,
        uptime_ms        INTEGER,
        rpm              INTEGER,
        temp_c           REAL,
        current_raw      INTEGER,
        current_a        REAL,
        pressure_pa      REAL,
        current_kind     TEXT,
        pressure_kind    TEXT,
        pwm              REAL,
        pressure_ok      INTEGER,
        validity         TEXT,
        faults           TEXT,
        latched          TEXT,
        queue            INTEGER,
        drops            INTEGER,
        frame_id         INTEGER,
        frame_age_ms     INTEGER,
        frame_state      TEXT,
        quality          TEXT,
        quality_reasons  TEXT,
        feature_count    INTEGER,
        features_json    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_snap_ts   ON snapshots(ts)",
    "CREATE INDEX IF NOT EXISTS idx_snap_link ON snapshots(link_ok, ts)",

    """
    CREATE TABLE IF NOT EXISTS events (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        event_key         TEXT    NOT NULL UNIQUE,
        boot_id           TEXT,
        code              TEXT    NOT NULL,
        source            TEXT    NOT NULL DEFAULT 'PL',
        severity          INTEGER NOT NULL,
        state             TEXT    NOT NULL,
        first_seen        REAL    NOT NULL,
        first_seen_iso    TEXT    NOT NULL,
        last_seen         REAL    NOT NULL,
        last_seen_iso     TEXT    NOT NULL,
        recovered_at      REAL,
        recovered_at_iso  TEXT,
        acknowledged      INTEGER NOT NULL DEFAULT 0,
        acknowledged_at   REAL,
        acknowledged_by   TEXT,
        ack_note          TEXT,
        context_json      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ev_first ON events(first_seen DESC)",
    "CREATE INDEX IF NOT EXISTS idx_ev_code  ON events(code)",
    "CREATE INDEX IF NOT EXISTS idx_ev_ack   ON events(acknowledged, state)",

    """
    CREATE TABLE IF NOT EXISTS audit (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      REAL NOT NULL,
        ts_iso  TEXT NOT NULL,
        actor   TEXT NOT NULL,
        action  TEXT NOT NULL,
        target  TEXT,
        detail  TEXT,
        ok      INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit(ts DESC)",

    """
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
]


class StoreError(Exception):
    pass


def connect(db_path, create=True):
    """打开数据库，设 PRAGMA 并读回校验。校验失败抛 StoreError（绝不静默降级）。"""
    if create:
        d = os.path.dirname(db_path)
        if d and not os.path.isdir(d):
            os.makedirs(d)

    con = sqlite3.connect(db_path, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.isolation_level = None  # 自己管事务

    bad = []
    for name, expect in PRAGMA_EXPECT:
        if name == "journal_mode":
            row = con.execute("PRAGMA journal_mode=WAL").fetchone()
            got = row[0] if row else None
        else:
            con.execute("PRAGMA %s=%s" % (name, expect if not isinstance(expect, str) else expect))
            row = con.execute("PRAGMA %s" % name).fetchone()
            got = row[0] if row else None
        if str(got).lower() != str(expect).lower():
            bad.append("%s: 期望 %r 实得 %r" % (name, expect, got))

    if bad:
        con.close()
        raise StoreError("PRAGMA 读回校验失败，拒绝继续（防静默降级）：" + "; ".join(bad))
    return con


def init_schema(con):
    # Serialize migration and commit columns/version together. Legacy rows stay
    # NULL: raw ADC and a validity flag cannot reconstruct historical A / Pa.
    con.execute("BEGIN IMMEDIATE")
    try:
        for stmt in DDL:
            con.execute(stmt)
        cols = set(r[1] for r in con.execute("PRAGMA table_info(snapshots)"))
        for name, sql_type in (("pwm", "REAL"), ("current_a", "REAL"),
                               ("pressure_pa", "REAL"), ("current_kind", "TEXT"),
                               ("pressure_kind", "TEXT")):
            if name not in cols:
                con.execute("ALTER TABLE snapshots ADD COLUMN %s %s" % (name, sql_type))
        set_meta(con, "schema_version", SCHEMA_VERSION)
        set_meta_if_absent(con, "created_at", _iso(time.time()))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return con


def integrity_ok(con):
    row = con.execute("PRAGMA integrity_check").fetchone()
    return bool(row) and str(row[0]).lower() == "ok"


# ---------------------------------------------------------------- meta

def get_meta(con, key, default=None):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(con, key, value):
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(value)))


def set_meta_if_absent(con, key, value):
    con.execute("INSERT OR IGNORE INTO meta(key,value) VALUES(?,?)", (key, str(value)))


# ---------------------------------------------------------------- snapshots

SNAPSHOT_COLS = [
    "ts", "ts_iso", "sequence", "link_ok", "message", "mode", "alarm", "action",
    "inhibit", "configured", "uptime_ms", "rpm", "temp_c", "current_raw", "pwm",
    "current_a", "pressure_pa", "current_kind", "pressure_kind",
    "pressure_ok", "validity", "faults", "latched", "queue", "drops",
    "frame_id", "frame_age_ms", "frame_state", "quality", "quality_reasons",
    "feature_count", "features_json",
]


def insert_snapshot(con, rec):
    """rec 是 dict；缺失的键写 NULL。无效测量值调用方应传 None。"""
    vals = [rec.get(c) for c in SNAPSHOT_COLS]
    sql = "INSERT INTO snapshots (%s) VALUES (%s)" % (
        ",".join(SNAPSHOT_COLS), ",".join(["?"] * len(SNAPSHOT_COLS)))
    cur = con.execute(sql, vals)
    return cur.lastrowid


def insert_snapshots_batch(con, recs):
    """批量插入 + 单事务 —— 减少 SD 卡写入次数，防漏采样。"""
    if not recs:
        return 0
    sql = "INSERT INTO snapshots (%s) VALUES (%s)" % (
        ",".join(SNAPSHOT_COLS), ",".join(["?"] * len(SNAPSHOT_COLS)))
    rows = [[r.get(c) for c in SNAPSHOT_COLS] for r in recs]
    con.execute("BEGIN IMMEDIATE")
    try:
        con.executemany(sql, rows)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(rows)


# 聚合字段白名单：字段名 -> (列, 聚合函数)
AGG_FIELDS = {
    "rpm":         ("rpm", "AVG"),
    "pwm":         ("pwm", "AVG"),
    "temp_c":      ("temp_c", "AVG"),
    "current_raw": ("current_raw", "AVG"),
    "current_a":   ("current_a", "AVG"),
    "pressure_pa": ("pressure_pa", "AVG"),
    "alarm":       ("alarm", "MAX"),
    "link_ok":     ("link_ok", "MIN"),
    "queue":       ("queue", "MAX"),
    "drops":       ("drops", "MAX"),
}


def query_history(con, ts_from, ts_to, max_points=600, fields=None,
                  max_hold_s=30.0, bucket_s=None):
    """
    按时间桶聚合（SQLite 3.22 无窗口函数，用 GROUP BY 思路在 Python 侧实现）。

    ★ 关键语义：本库是 deadband 存储 —— 「桶里没有行」表示「数值没有变化」，
      不是「没有数据」。所以空桶必须沿用上一个已知值（carry forward），
      否则趋势图会被画成满屏虚线，看起来像传感器一直在掉线。

      只有两种情况才输出 null：
        ① 该桶有行、但该字段全是 NULL —— 那一刻传感器确实无效（掉线）
        ② 距离上一个有行的时刻超过 max_hold_s —— 数据中断太久，沿用不可信

    ★ 同时返回 sample_count：*_n = 0 且 *_held = 1 的点是「沿用值」，不是实测样本。
    """
    if fields is None:
        # pwm 与 HDMI 界面的 PWM 曲线同源（applied_pwm_counts / 4000 * 100）
        fields = ["pwm", "temp_c", "rpm", "current_a", "pressure_pa", "current_raw", "alarm"]
    fields = [f for f in fields if f in AGG_FIELDS]
    if not fields:
        fields = ["rpm"]

    span = max(1.0, ts_to - ts_from)

    # 桶宽：默认按「窗口 / max_points」自动算；也可由调用方显式指定（分辨率选择器）
    MAX_BUCKETS = 5000          # 显式分辨率下的点数上限，防一次拉爆内存
    bucket_note = None
    if bucket_s and float(bucket_s) > 0:
        bucket = max(1.0, float(bucket_s))
        bucket_mode = "explicit"
        if (span / bucket) > MAX_BUCKETS:
            bucket = span / float(MAX_BUCKETS)
            bucket_note = ("指定的 %gs 分辨率会产生超过 %d 个点，已自动放宽到 %.1fs"
                           % (float(bucket_s), MAX_BUCKETS, bucket))
    else:
        bucket = max(1.0, span / float(max(1, max_points)))
        bucket_mode = "auto"

    cols = sorted(set(AGG_FIELDS[f][0] for f in fields))
    collist = ",".join(cols)

    # 行数上限保护：超长区间（例如手工请求 90 天）不能把百万行读进内存
    MAX_ROWS = 100000
    n_total = con.execute(
        "SELECT COUNT(*) AS n FROM snapshots WHERE ts >= ? AND ts <= ?",
        (ts_from, ts_to)).fetchone()["n"]
    stride = 1
    if n_total > MAX_ROWS:
        stride = int(math.ceil(n_total / float(MAX_ROWS)))

    if stride > 1:
        sql = ("SELECT ts,%s FROM snapshots WHERE ts>=? AND ts<=? AND (id %% ?)=0 "
               "ORDER BY ts") % collist
        rows = con.execute(sql, (ts_from, ts_to, stride)).fetchall()
    else:
        sql = ("SELECT ts,%s FROM snapshots WHERE ts>=? AND ts<=? ORDER BY ts"
               % collist)
        rows = con.execute(sql, (ts_from, ts_to)).fetchall()
    n_rows = len(rows)

    nb = int(span / bucket) + 1
    series = {"ts": []}
    for f in fields:
        series[f] = []
        series[f + "_n"] = []
        series[f + "_held"] = []

    by_bucket = {}
    for r in rows:
        idx = int((r["ts"] - ts_from) / bucket)
        if idx < 0:
            idx = 0
        elif idx >= nb:
            idx = nb - 1
        by_bucket.setdefault(idx, []).append(r)

    last_vals = dict((f, None) for f in fields)
    last_ts = None

    # ★ 用「窗口之前最后一行」作为沿用的起点。
    #   否则窗口最左边几个桶既没有行、也没有可沿用的历史 → 输出 null，
    #   趋势图左侧就出现一段空白，看起来像数据丢了一段。
    if stride == 1:
        seed = con.execute(
            "SELECT ts,%s FROM snapshots WHERE ts < ? ORDER BY ts DESC LIMIT 1"
            % collist, (ts_from,)).fetchone()
        if seed and (ts_from - seed["ts"]) <= max_hold_s:
            last_ts = seed["ts"]
            for f in fields:
                lv = seed[AGG_FIELDS[f][0]]
                last_vals[f] = (round(float(lv), 4) if lv is not None else None)

    for i in range(nb):
        bts = ts_from + i * bucket
        series["ts"].append(round(bts, 3))
        rs = by_bucket.get(i)

        if rs:
            for f in fields:
                col = AGG_FIELDS[f][0]
                vs = [x[col] for x in rs if x[col] is not None]
                if vs:
                    series[f].append(round(sum(vs) / float(len(vs)), 4))
                    series[f + "_n"].append(len(vs))
                    series[f + "_held"].append(0)
                else:
                    # 该桶确实测到「无效」→ 输出 null，并清空沿用基准
                    series[f].append(None)
                    series[f + "_n"].append(0)
                    series[f + "_held"].append(0)
                # 沿用基准取「桶内最后一行」，语义比均值更准
                lv = rs[-1][col]
                last_vals[f] = (round(float(lv), 4) if lv is not None else None)
            last_ts = rs[-1]["ts"]
        else:
            hold_ok = (last_ts is not None) and ((bts - last_ts) <= max_hold_s)
            for f in fields:
                v = last_vals.get(f)
                if hold_ok and v is not None:
                    series[f].append(v)
                    series[f + "_n"].append(0)
                    series[f + "_held"].append(1)
                else:
                    series[f].append(None)
                    series[f + "_n"].append(0)
                    series[f + "_held"].append(0)

    return {
        "bucket_s": round(bucket, 3),
        "bucket_mode": bucket_mode,
        "bucket_note": bucket_note,
        "count": nb,
        "rows": n_rows,
        "rows_total": n_total,
        "stride": stride,
        "max_hold_s": max_hold_s,
        "held_note": ("*_n=0 且 *_held=1 的点是 deadband 沿用值（该时段数值未变化），"
                      "不是实测样本；值为 null 才是真的没有数据"),
        "fields": fields,
        "series": series,
    }


def snapshot_bounds(con):
    row = con.execute("SELECT MIN(ts) AS a, MAX(ts) AS b, COUNT(*) AS n FROM snapshots").fetchone()
    if not row or not row["n"]:
        return None
    return {"first": row["a"], "last": row["b"], "count": row["n"],
            "first_iso": _iso(row["a"]), "last_iso": _iso(row["b"])}


# ---------------------------------------------------------------- events

def find_event(con, event_key):
    return con.execute("SELECT * FROM events WHERE event_key=?", (event_key,)).fetchone()


def upsert_event_open(con, event_key, boot_id, code, source, severity, ts, context):
    """故障出现：已存在则只更新 last_seen，否则新建 ACTIVE 事件。"""
    row = find_event(con, event_key)
    if row:
        con.execute("UPDATE events SET last_seen=?, last_seen_iso=?, state='ACTIVE', "
                    "recovered_at=NULL, recovered_at_iso=NULL WHERE event_key=?",
                    (ts, _iso(ts), event_key))
        return row["id"], False
    con.execute(
        "INSERT INTO events (event_key,boot_id,code,source,severity,state,"
        "first_seen,first_seen_iso,last_seen,last_seen_iso,context_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (event_key, boot_id, code, source, severity, "ACTIVE",
         ts, _iso(ts), ts, _iso(ts), json.dumps(context, ensure_ascii=False)))
    return con.execute("SELECT last_insert_rowid() AS i").fetchone()["i"], True


def recover_event(con, event_key, ts):
    row = find_event(con, event_key)
    if not row or row["state"] != "ACTIVE":
        return False
    con.execute("UPDATE events SET state='RECOVERED', recovered_at=?, recovered_at_iso=? "
                "WHERE event_key=?", (ts, _iso(ts), event_key))
    return True


def list_events(con, limit=50, offset=0, state=None, unack_only=False):
    where, params = [], []
    if state and state != "all":
        where.append("state=?")
        params.append(state)
    if unack_only:
        where.append("acknowledged=0")
    w = ("WHERE " + " AND ".join(where)) if where else ""

    total = con.execute("SELECT COUNT(*) AS n FROM events %s" % w, params).fetchone()["n"]
    rows = con.execute(
        "SELECT * FROM events %s ORDER BY first_seen DESC LIMIT ? OFFSET ?" % w,
        params + [limit, offset]).fetchall()

    items = []
    for r in rows:
        ctx = None
        if r["context_json"]:
            try:
                ctx = json.loads(r["context_json"])
            except ValueError:
                ctx = None
        items.append({
            "event_key": r["event_key"],
            "boot_id": r["boot_id"],
            "code": r["code"],
            "source": r["source"],
            "severity": r["severity"],
            "state": r["state"],
            "first_seen_iso": r["first_seen_iso"],
            "last_seen_iso": r["last_seen_iso"],
            "recovered_at_iso": r["recovered_at_iso"],
            "acknowledged": bool(r["acknowledged"]),
            "acknowledged_at_iso": (_iso(r["acknowledged_at"]) if r["acknowledged_at"] else None),
            "acknowledged_by": r["acknowledged_by"],
            "ack_note": r["ack_note"],
            "context": ctx,
        })
    return total, items


def ack_event(con, event_key, actor, note):
    row = find_event(con, event_key)
    if not row:
        return False
    ts = time.time()
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("UPDATE events SET acknowledged=1, acknowledged_at=?, "
                    "acknowledged_by=?, ack_note=? WHERE event_key=?",
                    (ts, actor, note, event_key))
        add_audit(con, actor, "ack", event_key, note or "", 1, commit=False)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return True


def count_active_events(con):
    return con.execute("SELECT COUNT(*) AS n FROM events WHERE state='ACTIVE'").fetchone()["n"]


def count_unack_events(con):
    return con.execute("SELECT COUNT(*) AS n FROM events WHERE acknowledged=0").fetchone()["n"]


# ---------------------------------------------------------------- audit

def add_audit(con, actor, action, target, detail, ok, commit=True):
    ts = time.time()
    if commit:
        con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("INSERT INTO audit (ts,ts_iso,actor,action,target,detail,ok) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (ts, _iso(ts), actor, action, target, detail, 1 if ok else 0))
        if commit:
            con.execute("COMMIT")
    except Exception:
        if commit:
            con.execute("ROLLBACK")
        raise


def list_audit(con, limit=50, offset=0):
    total = con.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"]
    rows = con.execute("SELECT * FROM audit ORDER BY ts DESC LIMIT ? OFFSET ?",
                       (limit, offset)).fetchall()
    return total, [dict(r) for r in rows]


# ---------------------------------------------------------------- stats / purge

def db_stats(con, db_path):
    out = {
        "db_path": db_path,
        "db_bytes": os.path.getsize(db_path) if os.path.exists(db_path) else 0,
        "wal_bytes": os.path.getsize(db_path + "-wal") if os.path.exists(db_path + "-wal") else 0,
        "shm_bytes": os.path.getsize(db_path + "-shm") if os.path.exists(db_path + "-shm") else 0,
    }
    out["snapshots"] = con.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
    out["events"] = con.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    out["events_active"] = count_active_events(con)
    out["events_unack"] = count_unack_events(con)
    out["audit"] = con.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"]
    out["bounds"] = snapshot_bounds(con)
    out["schema_version"] = get_meta(con, "schema_version")
    return out


def purge(con, before_ts, what, actor, note=""):
    """
    删除过期数据。what 里可含 snapshots / audit / events。
    events 只删「已恢复且早于 before_ts」的。
    ★ 大量 DELETE 会让 WAL 膨胀 → 之后显式 checkpoint(TRUNCATE)。
    """
    deleted = {}
    con.execute("BEGIN IMMEDIATE")
    try:
        if "snapshots" in what:
            cur = con.execute("DELETE FROM snapshots WHERE ts < ?", (before_ts,))
            deleted["snapshots"] = cur.rowcount
        if "audit" in what:
            cur = con.execute("DELETE FROM audit WHERE ts < ?", (before_ts,))
            deleted["audit"] = cur.rowcount
        if "events_all" in what:
            cur = con.execute("DELETE FROM events WHERE first_seen < ? OR last_seen < ?",
                              (before_ts, before_ts))
            deleted["events"] = cur.rowcount
        elif "events" in what:
            cur = con.execute("DELETE FROM events WHERE state='RECOVERED' AND last_seen < ?",
                              (before_ts,))
            deleted["events"] = cur.rowcount
        add_audit(con, actor, "purge", ",".join(what),
                  "before=%s %s" % (_iso(before_ts), note), 1, commit=False)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    # 清理后截断 WAL，防止文件持续膨胀
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
    return deleted


def page_stats(con):
    """
    返回 (文件字节, 空闲页数, 空闲字节, 空闲占比)。

    ★ 与上面的 db_stats(con, db_path) 区分：那个是给 API 用的统计汇总，
      这个只算页面层面的"文件里有多少是空的"。
    ★ auto_vacuum=0 时 DELETE 只是把页放进 freelist，文件不会缩 ——
      所以必须看 freelist_count 才知道空洞有多大。
    """
    page_size = con.execute("PRAGMA page_size").fetchone()[0]
    page_count = con.execute("PRAGMA page_count").fetchone()[0]
    free_pages = con.execute("PRAGMA freelist_count").fetchone()[0]
    total = page_size * page_count
    free = page_size * free_pages
    ratio = (free_pages / float(page_count)) if page_count else 0.0
    return total, free_pages, free, ratio


def compact(con, free_ratio=0.25, min_bytes=524288):
    """
    空闲页占比超过阈值时执行 VACUUM，把文件真正缩小。

    ★ VACUUM 不能在事务内执行 —— 调用前必须已 COMMIT（purge 内部会 commit）。
    ★ VACUUM 期间需要约 2 倍库大小的临时磁盘空间。
    ★ 压缩后 WAL 也要 truncate，否则 -wal 文件留着。

    返回 (是否执行, 压缩前字节, 压缩后字节)。
    """
    before, free_pages, free_bytes, ratio = page_stats(con)
    if ratio < free_ratio or free_bytes < min_bytes:
        return False, before, before

    con.execute("VACUUM")
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass
    after = page_stats(con)[0]
    return True, before, after


def export_rows(con, what, ts_from, ts_to, limit):
    if what == "snapshots":
        sql = ("SELECT * FROM snapshots WHERE ts>=? AND ts<=? ORDER BY ts LIMIT ?")
        return [dict(r) for r in con.execute(sql, (ts_from, ts_to, limit)).fetchall()]
    if what == "events":
        sql = ("SELECT * FROM events WHERE first_seen>=? AND first_seen<=? "
               "ORDER BY first_seen LIMIT ?")
        return [dict(r) for r in con.execute(sql, (ts_from, ts_to, limit)).fetchall()]
    if what == "audit":
        sql = "SELECT * FROM audit WHERE ts>=? AND ts<=? ORDER BY ts LIMIT ?"
        return [dict(r) for r in con.execute(sql, (ts_from, ts_to, limit)).fetchall()]
    return []


def backup_to(con, dest_path):
    """★ WAL 模式下不能用 cp 备份（有 -wal/-shm 伴生文件）。"""
    con.execute("VACUUM INTO ?", (dest_path,))
    return dest_path
