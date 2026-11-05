#!/bin/bash
# ============================================================
#  cabinet-web 端到端功能测试
# ============================================================
set -u
B=http://127.0.0.1:8080
P=python3

say() { echo; echo "########## $* ##########"; }
J() { $P -c "import sys,json;d=json.load(sys.stdin);print(json.dumps($1,ensure_ascii=False,indent=2))"; }
post() { curl -s -m 8 -X POST -H 'Content-Type: application/json' -d "$2" "$B$1"; }

say "1) 健康检查"
curl -s -m 5 "$B/api/health"

say "2) 跳到第 3 幕「传感器上线 · 启动」"
post /api/mock '{"action":"jump_phase","phase":2}'
sleep 4
echo "--- status.derived ---"
curl -s -m 5 "$B/api/status" | J "d['derived']"

say "3) 跳到第 6 幕「温度硬故障」"
post /api/mock '{"action":"jump_phase","phase":5}'
sleep 5
echo "--- status.derived ---"
curl -s -m 5 "$B/api/status" | J "d['derived']"

say "4) 事件表"
curl -s -m 5 "$B/api/events?limit=10" | J "{'total':d['total'],'active':d['active'],'unack':d['unacknowledged'],'items':[{'code':i['code'],'sev':i['severity'],'state':i['state'],'ack':i['acknowledged'],'key':i['event_key']} for i in d['items']]}"

say "5) 确认第一条事件（全站唯一写动作）"
KEY=$(curl -s -m 5 "$B/api/events?limit=1" | $P -c "import sys,json;print(json.load(sys.stdin)['items'][0]['event_key'])")
echo "event_key = $KEY"
post /api/ack "{\"event_key\":\"$KEY\",\"note\":\"测试确认\"}"

say "6) 确认不存在的事件（应 404）"
curl -s -m 5 -o /tmp/o -w "http=%{http_code} " -X POST -H 'Content-Type: application/json' \
     -d '{"event_key":"deadbeef"}' "$B/api/ack"; J "d" < /tmp/o

say "7) 审计日志"
curl -s -m 5 "$B/api/audit?limit=8" | J "[{'ts':i['ts_iso'],'actor':i['actor'],'action':i['action'],'target':i['target']} for i in d['items']]"

say "8) 历史聚合（10 个桶）"
curl -s -m 5 "$B/api/history?max_points=10" | $P -c "
import sys,json
d=json.load(sys.stdin); s=d['series']
print('bucket_s=%.1f  count=%d  fields=%s' % (d['bucket_s'], d['count'], d['fields']))
print('rpm    ', s['rpm'])
print('rpm_n  ', s['rpm_n'])
print('temp_c ', s['temp_c'])
print('alarm  ', s['alarm'])
nulls=sum(1 for v in s['rpm'] if v is None)
print('rpm 为 null 的桶: %d / %d  <-- 无数据处是 null，不是 0' % (nulls, len(s['rpm'])))
"

say "9) 数据库统计"
curl -s -m 5 "$B/api/stats" | J "{k:d[k] for k in ('snapshots','events','events_active','events_unack','audit','db_bytes','wal_bytes')}"

say "10) 导出 CSV"
curl -s -m 8 -D /tmp/h "$B/api/export?format=csv&what=snapshots" -o /tmp/e.csv
grep -i 'content-disposition' /tmp/h || true
head -c 260 /tmp/e.csv | head -3
echo "..."
echo "CSV 行数: $(wc -l < /tmp/e.csv)   BOM(hex): $(head -c 3 /tmp/e.csv | od -An -tx1 | tr -d ' ')"

say "11) purge 未带 confirm（应 400）"
curl -s -m 5 -o /tmp/o -w "http=%{http_code} " -X POST -H 'Content-Type: application/json' \
     -d '{"what":["snapshots"],"before_days":30}' "$B/api/purge"; J "d" < /tmp/o

say "12) 方法白名单：GET /api/ack（应 405）"
curl -s -m 5 -o /tmp/o -w "http=%{http_code} " "$B/api/ack"; J "d" < /tmp/o

say "13) 请求体超限 70KB（应 413）"
head -c 70000 /dev/zero | tr '\0' 'a' > /tmp/big.json
curl -s -m 8 -o /tmp/o -w "http=%{http_code} " -X POST -H 'Content-Type: application/json' \
     --data-binary @/tmp/big.json "$B/api/ack"; J "d" < /tmp/o

say "14) 路径穿越与脚本直访（应全 404）"
for u in "/../cgi/status" "/cgi/status" "/lib/store.py" "/config.json"; do
  printf "  %-22s " "$u"
  curl -s -m 5 -o /dev/null -w "http=%{http_code}\n" "$B$u"
done

say "15) ★ 硬性验收：源码里不得出现 UIO 设备路径（只扫源码，不扫本测试脚本）"
HITS=$(grep -rn '/dev/uio' /home/uisrc/web/lib /home/uisrc/web/api \
       /home/uisrc/web/public /home/uisrc/web/collector.py \
       /home/uisrc/web/mock_device.py /home/uisrc/web/apiserver.py 2>/dev/null || true)
if [ -n "$HITS" ]; then
  echo "$HITS"
  echo "★★★ 命中！违反硬性约束"
else
  echo "✅ 无命中"
fi

say "16) 确认后事件仍为 ACTIVE（ACK 不改变硬件状态）"
curl -s -m 5 "$B/api/events?limit=5" | $P -c "
import sys,json
d=json.load(sys.stdin)
for i in d['items'][:5]:
    print('  %-22s sev=%d state=%-9s ack=%s' % (i['code'], i['severity'], i['state'], i['acknowledged']))
"

echo
echo "########## 测试结束 ##########"
