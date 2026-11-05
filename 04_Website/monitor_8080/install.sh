#!/bin/bash
# ============================================================
#  cabinet-web 安装脚本
#  用法：sudo bash install.sh            （安装 + 启动）
#        sudo bash install.sh uninstall  （停服务，保留数据）
#
#  架构：lighttpd(:80) --mod_proxy--> apiserver(:8081) --SQLite
#                                    collector(:-) --> SQLite
# ============================================================
set -e

APP=/home/uisrc/web
PY=/usr/bin/python3
SERVICES="cabinet-web-mock cabinet-web-collector cabinet-web-api cabinet-web-lighttpd"

if [ "$1" = "uninstall" ]; then
    echo "==> 停止并禁用服务"
    for u in $SERVICES; do
        systemctl stop "$u" 2>/dev/null || true
        systemctl disable "$u" 2>/dev/null || true
        rm -f "/etc/systemd/system/$u.service"
    done
    systemctl daemon-reload
    echo "已卸载（$APP 下的代码与数据保留）"
    exit 0
fi

echo "==> 1/6 检查目录"
for d in public api lib data logs; do
    mkdir -p "$APP/$d"
done
chmod 755 "$APP" "$APP/public" "$APP/api" "$APP/lib"
chmod 700 "$APP/data" "$APP/logs"

echo "==> 2/6 准备 state.json 目录（tmpfs，与真机一致）"
mkdir -p /run/cabinet-live
chmod 755 /run/cabinet-live

echo "==> 3/6 Python 语法自检（3.6 兼容写法）"
cd "$APP"
for f in collector.py mock_device.py apiserver.py \
         lib/store.py lib/state_reader.py lib/apicommon.py; do
    "$PY" -m py_compile "$f" && echo "    OK  $f"
done
for f in api/*.py; do
    "$PY" -m py_compile "$f" && echo "    OK  $f"
done
# ★ open() 必须显式 encoding：板子 locale 是 C，默认按 ASCII 解码，中文配置会崩
"$PY" -c "import json; json.load(open('config.json', encoding='utf-8')); print('    OK  config.json')"
# ★ print 里也不要出现中文：板子 stdout 是 ANSI_X3.4-1968(ASCII)，打印中文会 UnicodeEncodeError
"$PY" -c "import sys; sys.path.insert(0,'.'); import api; print('    OK  endpoint registry: %d' % len(api.ENDPOINTS))"
find "$APP" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

echo "==> 4/6 写 systemd 单元"

# ---- 按 lighttpd 版本决定怎么透传客户端 IP ----
# proxy.forwarded 是 1.4.51 才加的；板子（Ubuntu 18.04）自带的是 1.4.45，没有这个机制。
# 1.4.45 的 mod_setenv 不支持 remoteip 占位符（会原样把字符串 "remoteip" 发出去，
# 导致 actor 记成 remoteip —— 比记 127.0.0.1 更糟），所以老版本只能放弃透传。
"$PY" - <<'PYEOF'
import subprocess
conf = "lighttpd.conf"
src = open(conf, encoding="utf-8").read()
try:
    out = subprocess.check_output(["/usr/sbin/lighttpd", "-v"],
                                  stderr=subprocess.STDOUT).decode("utf-8", "ignore")
    ver = out.split("lighttpd/")[1].split()[0]
    nums = [int(x) for x in ver.split(".")[:3] if x.isdigit()]
    is_ge_51 = tuple(nums) >= (1, 4, 51)
except Exception:
    ver, is_ge_51 = "?", False
if is_ge_51:
    repl = ('    proxy.forwarded = ( "for" => 1, "proto" => 1 )\n'
            '    # 1.4.51+ : RFC 7239 Forwarded header (proxy.header is for URL remap, do not use)')
    note = "proxy.forwarded enabled"
else:
    repl = ('    # lighttpd %s < 1.4.51 : no way to pass client IP to backend.\n'
            '    # audit actor will be recorded as 127.0.0.1 (the proxy address).' % ver)
    note = "no client-IP forwarding"
open(conf, "w", encoding="utf-8").write(src.replace("# @@CLIENT_IP_FORWARD@@", repl))
print("    lighttpd %s -> %s" % (ver, note))
PYEOF

cat > /etc/systemd/system/cabinet-web-mock.service <<'EOF'
[Unit]
Description=Cabinet web MOCK device (local prototype only)
Documentation=file:/home/uisrc/web/README.md
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/uisrc/web
Environment=CABINET_WEB_CONFIG=/home/uisrc/web/config.json
Environment=PYTHONIOENCODING=utf-8
ExecStart=/usr/bin/python3 -u /home/uisrc/web/mock_device.py
Restart=on-failure
RestartSec=3
User=root
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cabinet-web-mock

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/cabinet-web-collector.service <<'EOF'
[Unit]
Description=Cabinet web collector (state.json -> SQLite, read-only)
Documentation=file:/home/uisrc/web/README.md
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/uisrc/web
Environment=CABINET_WEB_CONFIG=/home/uisrc/web/config.json
Environment=PYTHONIOENCODING=utf-8
ExecStart=/usr/bin/python3 -u /home/uisrc/web/collector.py
Restart=on-failure
RestartSec=3
User=root
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cabinet-web-collector

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/cabinet-web-api.service <<'EOF'
[Unit]
Description=Cabinet web API (resident FastCGI-less backend, mod_proxy target)
Documentation=file:/home/uisrc/web/README.md
After=network.target cabinet-web-collector.service
Wants=cabinet-web-collector.service

[Service]
Type=simple
WorkingDirectory=/home/uisrc/web
Environment=CABINET_WEB_CONFIG=/home/uisrc/web/config.json
Environment=PYTHONIOENCODING=utf-8
Environment=CABINET_API_HOST=127.0.0.1
Environment=CABINET_API_PORT=8081
ExecStart=/usr/bin/python3 -u /home/uisrc/web/apiserver.py
Restart=on-failure
RestartSec=3
User=root
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cabinet-web-api
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/cabinet-web-lighttpd.service <<'EOF'
[Unit]
Description=Cabinet web panel (lighttpd front-end + mod_proxy API)
Documentation=file:/home/uisrc/web/README.md
After=network.target cabinet-web-api.service
Wants=cabinet-web-api.service

[Service]
Type=simple
ExecStart=/usr/sbin/lighttpd -D -f /home/uisrc/web/lighttpd.conf
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=2
User=root
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cabinet-web-lighttpd
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

echo "==> 5/6 启用服务"
systemctl daemon-reload

# ★ 端口 80 默认被 apt 装的 lighttpd.service 占着（它服务 /var/www/html）。
#   不停掉它，cabinet-web-lighttpd 会因端口冲突起不来。
if systemctl is-enabled lighttpd >/dev/null 2>&1; then
    echo "    停用系统自带 lighttpd.service（它占着 80 端口）"
    systemctl disable lighttpd >/dev/null 2>&1 || true
    systemctl stop lighttpd 2>/dev/null || true
fi

# 模拟器只在 mock.enabled=true 时启用。
# 真机（板子上有 reader.py 产真实 state.json）必须设 false，
# 否则模拟器会覆盖 /run/cabinet-live/state.json，把真实数据冲掉。
MOCK_ON=$("$PY" -c "import json;print(1 if json.load(open('config.json', encoding='utf-8'))['mock'].get('enabled') else 0)")
if [ "$MOCK_ON" = "1" ]; then
    echo "    mock.enabled=true  → 启用模拟器"
    systemctl enable cabinet-web-mock >/dev/null 2>&1 || true
    systemctl restart cabinet-web-mock
else
    echo "    mock.enabled=false → 停用模拟器，使用真实 state.json"
    systemctl disable cabinet-web-mock >/dev/null 2>&1 || true
    systemctl stop cabinet-web-mock 2>/dev/null || true
fi

systemctl enable cabinet-web-collector cabinet-web-api cabinet-web-lighttpd >/dev/null
systemctl restart cabinet-web-collector
systemctl restart cabinet-web-api
sleep 1
systemctl restart cabinet-web-lighttpd
sleep 3

echo "==> 6/6 状态"
for u in cabinet-web-mock cabinet-web-collector cabinet-web-api cabinet-web-lighttpd; do
    if [ "$u" = "cabinet-web-mock" ] && [ "$MOCK_ON" != "1" ]; then
        printf "    %-28s %s\n" "$u" "disabled (mock.enabled=false)"
        continue
    fi
    printf "    %-28s %s\n" "$u" "$(systemctl is-active $u)"
done
echo
echo "端口："
ss -lnt 2>/dev/null | grep -E ':80 |:8081' | sed 's/^/    /' \
    || echo "    (未监听，看 journalctl -u cabinet-web-lighttpd / -u cabinet-web-api)"
echo
# 取「默认路由的源地址」才是真正能访问的 IP。
# 用 hostname -I | awk '{$1}' 会先拿到 eth0 的静态地址（板子上通常 linkdown，是死地址）。
IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -1)
[ -z "$IP" ] && IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "访问： http://${IP:-127.0.0.1}/"
echo "自检： curl -s http://127.0.0.1/api/health"
echo "本机各网卡地址："
ip -4 -o addr show scope global 2>/dev/null | awk '{printf "    %s\n", $4}' | sed 's|/.*||'
