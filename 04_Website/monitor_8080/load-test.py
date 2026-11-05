#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测量面板真实轮询负载对服务器 CPU 的消耗。

原理：读 /proc/<pid>/stat
      - utime + stime        = 进程自身 CPU
      - cutime + cstime      = 已回收子进程的 CPU（CGI 模式下就是那些 python3）
      跑负载前后各取一次，差值就是这批请求真实吃掉的 CPU。

★ 必须同时统计 lighttpd 和 apiserver 两个进程：
  mod_proxy 模式下后端是独立进程，它的 CPU 不在 lighttpd 的 cutime 里。
"""
import os
import time
import urllib.request

BASE = "http://127.0.0.1:8080"
DURATION = 30.0
RATE = 2.4          # 面板在「1 分钟窗口」下的实际请求率

REQS = ["/api/status", "/api/status", "/api/history?max_points=600",
        "/api/history?max_points=600", "/api/events?limit=50",
        "/api/health", "/api/stats", "/api/audit?limit=50"]

MARKERS = ["/home/uisrc/web/lighttpd.conf", "/home/uisrc/web/apiserver.py"]


def find_groups(marker):
    """
    按 cmdline 里的标记找进程，返回 {tgid: [tid, ...]}。

    ★ 坑：多线程进程在 /proc 下每个线程一个目录，直接遍历会重复累加 CPU。
      必须按 Tgid 归组。
    """
    groups = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                cl = f.read().decode("utf-8", "ignore")
        except OSError:
            continue
        if marker not in cl:
            continue
        try:
            with open("/proc/%s/status" % pid) as f:
                tgid = None
                for line in f:
                    if line.startswith("Tgid:"):
                        tgid = int(line.split()[1])
                        break
        except OSError:
            continue
        if tgid is None:
            continue
        groups.setdefault(tgid, []).append(int(pid))
    return groups


def cpu_of_group(tids):
    self_cpu = 0
    child_cpu = None
    for tid in tids:
        try:
            with open("/proc/%d/stat" % tid) as f:
                s = f.read()
            rest = s[s.rindex(")") + 2:].split()
            self_cpu += int(rest[11]) + int(rest[12])
            if child_cpu is None:
                child_cpu = int(rest[13]) + int(rest[14])
        except (OSError, ValueError, IndexError):
            continue
    return self_cpu + (child_cpu or 0)


def main():
    hz = os.sysconf("SC_CLK_TCK")
    groups = {}
    for m in MARKERS:
        groups.update(find_groups(m))
    print("被统计的进程组: %s" % sorted(groups.keys()))
    if not groups:
        print("找不到 cabinet-web 相关进程")
        return

    c0 = sum(cpu_of_group(t) for t in groups.values())
    t0 = time.time()
    n_req = n_err = 0
    i = 0
    interval = 1.0 / RATE
    while time.time() - t0 < DURATION:
        url = BASE + REQS[i % len(REQS)]
        i += 1
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                r.read()
            n_req += 1
        except Exception:
            n_err += 1
        d = (t0 + i * interval) - time.time()
        if d > 0:
            time.sleep(d)
    el = time.time() - t0
    c1 = sum(cpu_of_group(t) for t in groups.values())

    cpu_s = (c1 - c0) / float(hz)
    per = cpu_s / max(1, n_req)
    print()
    print("=== 实测（x86 Debian 13 / Python 3.13）===")
    print("  时长            %.1f s" % el)
    print("  成功请求        %d  (失败 %d)  → %.2f req/s" % (n_req, n_err, n_req / el))
    print("  服务器 CPU 消耗 %.3f s" % cpu_s)
    print("  每请求 CPU      %.2f ms" % (per * 1000))
    print("  占单核比例      %.1f%%" % (cpu_s / el * 100))
    print()
    print("=== 换算到开发板（Cortex-A35）===")
    print("  mod_proxy 模式下已无解释器启动开销，倍数只作用于业务逻辑那部分，")
    print("  所以实际占用会明显低于 CGI 时期的估算值。")
    print("  每秒 CPU ≈ %.1f ms = 单核的 %.1f%%"
          % (per * RATE * 1000, per * RATE * 100))


if __name__ == "__main__":
    main()
