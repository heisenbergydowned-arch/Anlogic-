# -*- coding: utf-8 -*-
"""
apicommon.py —— API 公共层：配置、查询串、请求体、方法白名单、统一响应、异常兜底。

★ 只服务「常驻模式」：
      lighttpd  --mod_proxy-->  apiserver.py  -->  api/<endpoint>.py  -->  这里

  请求信息由 apiserver 通过 Request 对象注入，不再读 os.environ / stdin。
  （单线程服务器，模块级 _REQ 不存在竞态。）

★ 所有输出都是显式 UTF-8 字节，不依赖环境里的 LANG。
"""

import os
import sys
import json
import time
import traceback
from urllib.parse import parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import store          # noqa: E402
import state_reader   # noqa: E402

_CACHE = {}
_REQ = None          # 当前请求（单线程，无竞态）


class HttpError(Exception):
    def __init__(self, status, code, detail):
        Exception.__init__(self, detail)
        self.status = status
        self.code = code
        self.detail = detail


class Raw(object):
    """非 JSON 响应（CSV / 文件下载）。"""

    def __init__(self, data, content_type, filename=None, status=200):
        self.data = data
        self.content_type = content_type
        self.filename = filename
        self.status = status


class Request(object):
    """apiserver 解析好的一次 HTTP 请求。"""

    def __init__(self, method, path, query, headers, body, client):
        self.method = (method or "GET").upper()
        self.path = path or "/"
        self.query = query or ""
        self.headers = headers or {}      # key 一律小写
        self.body = body or b""
        self.client = client or "unknown"


def set_request(req):
    global _REQ
    _REQ = req


def request():
    return _REQ


# ---------------------------------------------------------------- 配置

def config_path():
    # 进程级配置路径：systemd 的 Environment= 指定，不属于请求作用域
    p = os.environ.get("CABINET_WEB_CONFIG")
    if p:
        return p
    return os.path.join(ROOT, "config.json")


def cfg():
    if "cfg" not in _CACHE:
        _CACHE["cfg"] = state_reader.load_config(config_path())
    return _CACHE["cfg"]


def db_path():
    return cfg()["paths"]["db"]


def open_store():
    return store.connect(db_path())


# ---------------------------------------------------------------- 请求解析

def query():
    return parse_qs((_REQ.query if _REQ else ""), keep_blank_values=True)


def q1(qs, name, default=None):
    v = qs.get(name)
    if not v:
        return default
    return v[0]


def qint(qs, name, default, lo=None, hi=None):
    v = q1(qs, name)
    if v is None or v == "":
        return default
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        raise HttpError(400, "bad_param", "参数 %s 必须是整数" % name)
    if lo is not None and n < lo:
        n = lo
    if hi is not None and n > hi:
        n = hi
    return n


def body_json():
    """读取并解析 JSON 请求体，带大小上限。"""
    req = _REQ
    method = req.method if req else "GET"
    if method not in ("POST", "PUT", "PATCH"):
        return {}
    body = req.body if req else b""
    limit = int(cfg()["api"]["max_body_bytes"])
    if len(body) > limit:
        raise HttpError(413, "too_large", "请求体超过 %d 字节上限" % limit)
    ctype = (req.headers.get("content-type", "") if req else "").lower()
    if "application/json" not in ctype:
        raise HttpError(415, "unsupported_media_type", "请求体必须是 application/json")
    if not body:
        return {}
    try:
        obj = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise HttpError(400, "bad_json", "请求体不是合法 JSON")
    if not isinstance(obj, dict):
        raise HttpError(400, "bad_json", "请求体必须是 JSON 对象")
    return obj


def actor():
    """
    来源标识。lighttpd mod_proxy 会带 RFC 7239 的 Forwarded 头：
        Forwarded: for=192.168.234.1;proto=http
        Forwarded: for="[2001:db8::1]:1234";proto=http
    解析出客户端 IP；拿不到就退回 X-Forwarded-For，再退回 TCP 对端地址
    （反代场景下对端恒为 127.0.0.1，所以前两者优先）。
    """
    if not _REQ:
        return "unknown"

    fwd = _REQ.headers.get("forwarded")
    if fwd:
        for part in fwd.split(";"):
            part = part.strip()
            if not part.lower().startswith("for="):
                continue
            v = part[4:].strip().strip('"')
            if v.startswith("["):            # [ipv6]:port
                v = v[1:].split("]")[0]
            elif v.count(":") == 1:          # ipv4:port
                v = v.split(":")[0]
            if v and v.lower() != "unknown":
                return v

    xff = _REQ.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()

    return _REQ.client or "unknown"


def require_method(*allowed):
    m = _REQ.method if _REQ else "GET"
    if m not in allowed:
        raise HttpError(405, "method_not_allowed",
                        "只允许 %s，收到 %s" % ("/".join(allowed), m))
    return m


# ---------------------------------------------------------------- 响应

def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def log_exc(text):
    try:
        d = cfg()["paths"]["log"]
        if not os.path.isdir(d):
            os.makedirs(d)
        p = os.path.join(d, "web.log")
        if os.path.exists(p) and os.path.getsize(p) > 1024 * 1024:
            if os.path.exists(p + ".1"):
                os.remove(p + ".1")
            os.rename(p, p + ".1")
        with open(p, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n%s\n" % (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                (_REQ.path if _REQ else "?"), text))
    except Exception:
        pass


def csv_bytes(rows, columns=None):
    """写 UTF-8 带 BOM 的 CSV，便于 Excel 打开中文。"""
    import csv
    import io
    if not rows:
        return b"\xef\xbb\xbf"
    if columns is None:
        columns = list(rows[0].keys())
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
