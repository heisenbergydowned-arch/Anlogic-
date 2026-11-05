#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apiserver.py —— 常驻 API 后端（替代 CGI）

    lighttpd  --mod_proxy-->  127.0.0.1:8081  -->  api/<endpoint>.py

为什么是常驻进程：
    CGI 每请求都要 fork + 启动解释器 + 导入模块，实测占 97% 的开销
    （真正的业务逻辑只有 3%）。常驻进程把这块全部省掉。

★ 单线程（HTTPServer 而非 ThreadingHTTPServer）：
  - 每请求 1~5 ms，面板稳态 2.4 req/s，串行完全够用
  - 单线程 = 只有一条 SQLite 写路径，也不存在共享状态竞态
★ 零第三方依赖：http.server / sqlite3 都是标准库。
★ Python 3.6 兼容（板子是 3.6.9）：不用 f-string 以外的 3.7+ 语法。
"""

import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
sys.path.insert(0, HERE)

import apicommon   # noqa: E402
import api         # noqa: E402

HOST = os.environ.get("CABINET_API_HOST") or "127.0.0.1"
PORT = int(os.environ.get("CABINET_API_PORT") or 8081)
# 硬上限：超过直接 413，不读进内存。业务层还有更小的可配置上限
# （config.json 的 api.max_body_bytes），两者分工不同，别把这里当业务上限。
HARD_MAX_BODY = 1024 * 1024

JSON_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def _err(code, detail, status):
    return status, JSON_HEADERS, apicommon.json_bytes(
        {"ok": False, "error": code, "detail": detail})


class Handler(BaseHTTPRequestHandler):
    server_version = "cabinet-api/1.0"
    protocol_version = "HTTP/1.1"      # keep-alive，省掉重复建连

    def log_message(self, fmt, *args):
        # 每请求打一行进 journald 太吵，默认静默
        if os.environ.get("CABINET_API_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_HEAD(self):
        self._dispatch("HEAD")

    # ------------------------------------------------------------ 内部

    def _read_body(self):
        raw = self.headers.get("Content-Length")
        if not raw:
            return b""
        try:
            length = int(raw)
        except ValueError:
            return b""
        if length <= 0:
            return b""
        try:
            return self.rfile.read(length)
        except (OSError, ValueError):
            return b""

    def _send(self, status, headers, body):
        try:
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _dispatch(self, method):
        parts = urlsplit(self.path)
        path = parts.path

        if not path.startswith("/api/"):
            self._send(*_err("not_found", "只提供 /api/<endpoint>", 404))
            return
        name = path[5:].strip("/")
        if not name or "/" in name:
            self._send(*_err("not_found", "未知端点", 404))
            return
        mod = api.ENDPOINTS.get(name)
        if mod is None:
            self._send(*_err("not_found", "未知端点：%s" % name, 404))
            return

        # 硬上限在服务器层挡掉，避免把超大 body 读进内存；
        # 业务层（config 的 api.max_body_bytes）再挡一次，返回 413
        raw_cl = self.headers.get("Content-Length")
        if raw_cl:
            try:
                cl = int(raw_cl)
            except ValueError:
                self._send(*_err("bad_request", "Content-Length 非法", 400))
                return
            if cl > HARD_MAX_BODY:
                self._send(*_err("too_large",
                                 "请求体超过 %d 字节硬上限" % HARD_MAX_BODY, 413))
                return

        headers = dict((k.lower(), v) for k, v in self.headers.items())
        req = apicommon.Request(method, path, parts.query, headers,
                                self._read_body(), self.client_address[0])
        apicommon.set_request(req)
        try:
            apicommon.require_method(*mod.METHODS)
            result = mod.handle()

            if isinstance(result, apicommon.Raw):
                h = {
                    "Content-Type": result.content_type,
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                }
                if result.filename:
                    h["Content-Disposition"] = 'attachment; filename="%s"' % result.filename
                self._send(result.status, h, result.data)
            elif isinstance(result, tuple):
                payload, status = result
                self._send(status, JSON_HEADERS, apicommon.json_bytes(payload))
            else:
                self._send(200, JSON_HEADERS, apicommon.json_bytes(result))

        except apicommon.HttpError as e:
            self._send(e.status, JSON_HEADERS,
                       apicommon.json_bytes({"ok": False, "error": e.code,
                                             "detail": e.detail}))
        except apicommon.store.StoreError:
            apicommon.log_exc(traceback.format_exc())
            self._send(*_err("store_error",
                             "数据库初始化校验失败，服务拒绝降级运行", 500))
        except Exception:
            apicommon.log_exc(traceback.format_exc())
            self._send(*_err("internal_error",
                             "服务内部错误，详情见 logs/web.log", 500))
        finally:
            apicommon.set_request(None)


def main():
    srv = HTTPServer((HOST, PORT), Handler)
    print("[api] listening on %s:%d  endpoints=%s"
          % (HOST, PORT, ",".join(sorted(api.ENDPOINTS))), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        print("[api] stopped", flush=True)


if __name__ == "__main__":
    main()
