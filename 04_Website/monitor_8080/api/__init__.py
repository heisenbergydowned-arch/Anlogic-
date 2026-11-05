# -*- coding: utf-8 -*-
"""
api —— 端点模块注册表。

每个模块提供：
    handle()          -> dict / (dict, status) / apicommon.Raw
    METHODS           -> 允许的 HTTP 方法元组

新增端点只要在本文件里加一行导入，不需要改 lighttpd 配置。
"""

from . import (ack, audit, compact, events, export, health, history, mock,
               purge, snapshots, stats, status)

_MODULES = (ack, audit, compact, events, export, health, history, mock,
            purge, snapshots, stats, status)

# 端点名 -> 模块
ENDPOINTS = dict((m.__name__.rsplit(".", 1)[-1], m) for m in _MODULES)

__all__ = ["ENDPOINTS"]
