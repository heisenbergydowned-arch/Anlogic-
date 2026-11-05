# 机柜风冷边缘智能测控系统 · Web 面板（lighttpd + mod_proxy）

> 本地 Linux 原型 · Debian 13 x86_64 · Python 3.13 运行，代码按 **Python 3.6 兼容** 写
> 目标板（安路 DR1M90G / Ubuntu 18.04 / Python 3.6.9）可直接复用，无需改代码
> 内部代号仍为 `cabinet-web`（systemd 单元名、路径前缀）

---

## 一、这是什么

一套**只读监控 + 审计动作**的机柜风冷 Web 面板，本地跑在 lighttpd 上：

- **监控**：实时状态、4 项测量值、39 维特征、趋势图、诊断块、故障事件
- **控制**：报警确认（ACK，只写自己的库）+ 数据库导出/清理；**原型阶段额外提供模拟器控制**
- **本地数据库**：SQLite（WAL 模式），降采样快照 + 事件表 + 审计表

### 安全边界（红线，一条都没碰）

| 不做 | 原因 |
|---|---|
| 打开 UIO 设备节点 / 任何 MMIO | 收帧会消费邮箱，不能与读帧进程共存 |
| SET_TARGET / STOP / RESET / SILENCE | 网页无这些入口 |
| 改阈值 / PWM / 目标转速 / 继电器 | 不修改保护参数 |
| 透传寄存器写入 | 网站不得直接透传寄存器写入 |

**唯一允许的写动作**：把 ACK 记进自己的 SQLite（纯审计标记，不回写硬件）。
验收硬指标：`grep -rn '/dev/uio' <源码目录>` 必须无命中。

---

## 二、架构

```
┌──────────────────── 采集侧（现有，不改动）────────────────────┐
│  PL 寄存器 FCB1/EDG1  →  reader.py --live  →  state.json      │
│                          (flock 独占)         (原子重写 ~100ms)│
└───────────────────────────┬───────────────────────────────────┘
                            │ 只读 open().read()，不加锁不写
┌───────────────────────────▼────────── Web 侧（本项目）────────┐
│                                                                │
│   mock_device.py ──┐                                           │
│  （原型期替代 reader）│  collector.py ──→ SQLite ◀──┐            │
│                     └─→ state.json                │            │
│                                                   │            │
│   浏览器 ──▶ lighttpd :80 ──/api/*──▶ apiserver ─┘            │
│            （静态文件 sendfile）        （:8081 常驻，单线程）    │
└────────────────────────────────────────────────────────────────┘
```

**为什么这么分**：采集进程独占硬件、Web 进程只读本地数据 —— 这是工业网关的标准做法，
也正是本项目必须遵守的约束。

---

## 三、路由方案（lighttpd 的关键设计，已实测）

静态文件由 lighttpd 直接送；`/api/*` 反代到常驻后端 `apiserver.py`：

```lighttpd
$HTTP["url"] =~ "^/api/" {
    proxy.server = ( "" => ( ( "host" => "127.0.0.1", "port" => 8081 ) ) )
    proxy.forwarded = ( "for" => 1, "proto" => 1 )
}
```

效果（实测）：

| 请求 | 结果 |
|---|---|
| `/` | 静态文件，200 |
| `/api/status` | 反代到 apiserver，200，query string 完整传递 |
| `/api/status?from=1&to=2` | query 完整传递 |
| `/lib/store.py` | **403**（`url.access-deny` 拦下） |
| `/config.json` | **404**（在 docroot 外） |
| `/api/nonexist` | **404**（apiserver 返回 JSON 错误） |

**三个踩坑记录**：

1. **`proxy.header` 不是用来加转发头的** —— 它是做 URL / Host 重映射的。
   写成 `proxy.header = ( "add-x-forwarded-for" => "enable" )` 会让 lighttpd
   启动失败：`unexpected value for proxy.header; expected ( "param" => (...) )`。
   正确做法是 `proxy.forwarded = ( "for" => 1, "proto" => 1 )`（RFC 7239 的
   `Forwarded` 头），后端再从中解析客户端 IP。

2. **`setenv.add-response-header` 依赖 `mod_setenv`** —— 换模块列表时如果漏了它，
   lighttpd 只打一行 `WARNING: unknown config-key` 就继续跑，**安全响应头会静默失效**。

3. **`server.modules` 里删模块要连带删配置** —— 改成 mod_proxy 时我删了 `mod_cgi`
   和 `mod_alias`，但忘了 `mod_setenv` 仍在用，导致上面的静默失效。

> 历史：最初用 `mod_cgi` + `alias.url`（CGI 脚本放 docroot 外，仅 `/api/` 暴露）。
> 后来实测 CGI 每请求 **60.7 ms CPU、占单核 14.6%**，才迁到 `mod_proxy`
> —— 迁移前后对比见第十节。

---

## 四、文件结构

```
/home/uisrc/web/
├── lighttpd.conf         lighttpd 配置（:80，mod_proxy）
├── install.sh            一键安装 / 卸载
├── test-e2e.sh           端到端功能测试（16 项）
├── load-test.py          实测轮询负载对服务器 CPU 的消耗
├── apiserver.py          ★ 常驻 API 后端（:8081，单线程，无第三方依赖）
├── public/
│   ├── index.html        前端单文件（内联 CSS+JS，无 CDN）
│   ├── chart-compare.html 四种图表实现并排对比页
│   ├── self-test.html    防闪自检（DOM 节点是否跨更新存活）
│   └── vendor/           uPlot 1.6.32（51 KB + 1.9 KB CSS）
│                         + Chart.js / ECharts（仅对比页用）
├── api/                  ★ 端点模块（纯函数，可被 apiserver 导入）
│   ├── __init__.py       注册表：ENDPOINTS = {name: module}
│   ├── health.py  status.py   history.py  events.py  ack.py
│   └── audit.py   stats.py    purge.py    export.py  mock.py
├── lib/                  共享库（不可 Web 访问）
│   ├── store.py          SQLite 层：建表/写入/查询/清理
│   ├── state_reader.py   state.json 读取 + 解析（TTL 缓存）
│   └── apicommon.py      API 公共层：请求解析/响应/异常兜底/安全
├── mock_device.py        模拟数据源（原型期；真机换成 reader.py）
├── collector.py          常驻采集：降采样入库 + 事件检测 + 过期清理
├── config.json           配置
├── data/                 SQLite 库（ext4 持久）
└── logs/                 应用日志 + lighttpd 日志
```

**新增端点只需**：在 `api/` 里加一个模块（提供 `handle()` 和 `METHODS`），
再到 `api/__init__.py` 加一行导入 —— **不用改 lighttpd 配置**。

命名避开了 `policy.py` / `model.py` / `service.py` / `load.py` —— 这些在板子
stdlib 路径下有同名文件，容易混淆。

---

## 五、安装与运行

```bash
# 安装（建目录 + 语法自检 + 写 systemd 单元 + 启动）
sudo bash /home/uisrc/web/install.sh

# 卸载（停服务，保留代码与数据）
sudo bash /home/uisrc/web/install.sh uninstall

# 端到端测试
bash /home/uisrc/web/test-e2e.sh
```

三个 systemd 单元：`cabinet-web-lighttpd` / `cabinet-web-collector` / `cabinet-web-mock`

```bash
systemctl status cabinet-web-lighttpd cabinet-web-collector cabinet-web-mock
journalctl -u cabinet-web-collector -f
```

访问：`http://<VM_IP>`（本机实测 `http://192.168.234.129`）

> ⚠️ VM 上 UFW 默认拒绝入站，需要放行：
> `sudo ufw allow 80/tcp`
> 撤销：`sudo ufw delete allow 80/tcp`

---

## 六、HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查（DB / 采集器 / state.json 三项） |
| GET | `/api/status` | 实时状态：state.json 原文 + `derived` 派生字段 |
| GET | `/api/history` | 历史聚合（`from`/`to`/`max_points`/`fields`/`bucket`） |
| GET | `/api/events` | 事件列表（`limit`/`offset`/`state`/`unack_only`） |
| POST | `/api/ack` | **唯一写动作**：确认事件 |
| GET | `/api/audit` | 审计日志 |
| GET | `/api/stats` | 数据库统计 |
| POST | `/api/purge` | 删除过期数据（必须 `confirm="PURGE"`） |
| GET | `/api/export` | 导出 CSV（UTF-8 带 BOM）/ JSON |
| GET/POST | `/api/mock` | 模拟器控制（`mock.enabled=false` 时返回 403） |

统一响应：`Content-Type: application/json; charset=utf-8`、`Cache-Control: no-store`。
错误一律 `{"ok": false, "error": "<code>", "detail": "<人话>"}`，**不泄漏堆栈**。

---

## 七、数据库设计

三张表：`snapshots`（降采样快照）/ `events`（故障事件）/ `audit`（审计），另有 `meta` 键值表。

### 从嵌入式 SQLite 最佳实践吸收的 10 条（全部已落地）

| # | 实践 | 落地位置 |
|---|---|---|
| 1 | `WAL + synchronous=NORMAL + busy_timeout=5000 + foreign_keys=ON + temp_store=MEMORY` | `store.PRAGMA_EXPECT` |
| 2 | `wal_autocheckpoint=256`（≈1MB）+ `mmap_size=16MB` | 同上 |
| 3 | **PRAGMA 读回校验，不一致直接抛错退出** | `store.connect()` |
| 4 | 聚合查询同时返回 `sample_count` | `store.query_history()` → `*_n` 数组 |
| 5 | 无效值一律 NULL，绝不用 0 代替 | `state_reader.derive()` |
| 6 | 清理后显式 `wal_checkpoint(TRUNCATE)` | `store.purge()` |
| 7 | 批量插入（`executemany` + 单事务） | `store.insert_snapshots_batch()` |
| 8 | API 层安全加固 4 项 | `apicommon`：方法白名单 / 体积上限 / 路径校验 / 不泄漏堆栈 |
| 9 | 备份用 `VACUUM INTO` 而非 `cp` | `store.backup_to()` |
| 10 | 事件按 `(boot_id, code)` 去重 | `collector.event_key()` |

> 第 3 条最关键：**如果另一个连接占着库，`journal_mode=WAL` 会静默失败**，
> 退化成 rollback 模式（全库锁），直到断电才发现数据丢了。所以必须读回校验。

### ★★ deadband 查询语义（最容易搞错的一点）

`deadband` 模式下快照是「**数值变化才写 + 每 10 秒心跳**」，所以平均几秒才有一条记录。
于是「某个时间桶里没有行」的真实含义是 —— **那段时间数值没有变化**，
**不是「没有数据」**。

一开始我把空桶当成缺失值输出 `null`，前端按约定断线绘制 → **趋势图变成满屏虚线**，
看起来像传感器一直在掉线（实测 301 个桶里只有 42 个有行）。

正确做法是 **carry forward（沿用上一个已知值）**，只有两种情况才输出 `null`：

| 情况 | 含义 |
|---|---|
| 该桶有行、但该字段全是 `NULL` | 那一刻传感器确实无效（`validity=0`，掉线） |
| 距上一个有行的时刻 > `max_hold_s`（默认 3× 心跳 = 30 s） | 数据中断太久，沿用不可信 |

实现要点（`store.query_history`）：

- 空桶沿用 `last_vals`，并在 `*_held` 数组里标 `1`；`*_n = 0` 表示不是实测样本
- 沿用基准取「桶内**最后一行**」的值，而不是桶内均值 —— 语义更准
- **遇到「有行但全 NULL」的桶，必须把沿用基准清成 `None`**，否则掉线结束后
  会继续沿用掉线前的旧值，把真实的传感器故障抹掉
- `*_n=0 且 *_held=1` → 沿用值；`值=null` → 真的没数据。前端据此提示，两者不能混
- **窗口起点要「预热」**：额外查一条 `ts < ts_from` 的最近行作为沿用起点。
  否则窗口最左边几个桶既没有行、也没有历史可沿用 → 输出 null →
  趋势图**左侧出现一段空白**，看起来像数据丢了一段（1 分钟窗口实测会出现 5 个空桶）

**副产物**：一开始我试过「把桶宽放大到平均采样间隔」来消掉空桶，但那只是让虚线变粗，
而且牺牲了时间分辨率。carry forward 才是对的 —— 保留 1 秒分辨率的同时曲线连续。

### 时间分辨率（`bucket` 参数）

**时间范围**和**时间分辨率**是两个独立维度，面板上分开控制：

| 维度 | 控件 | 说明 |
|---|---|---|
| 时间范围 | 1 分钟 / 5 分钟 / 1 小时 / 24 小时 | 看多长的一段 |
| 时间分辨率 | 自动 / 1s / 5s / 10s / **1 分钟** / 5 分钟 / 1 小时 | 每个点代表多长时间 |

`/api/history?bucket=<秒数|auto>`：

- `auto`（默认）→ 桶宽 = 窗口 ÷ `max_points`（受 API 的 2000 上限约束）
- 显式秒数 → 按指定值聚合；**但点数上限 5000**，超出会自动放宽并在
  `bucket_note` 里说明（例如 24 小时窗口要 1 秒分辨率 → 放宽到 17.3 秒）

实测各档（`max_points=600`）：

| 档位 | 窗口 | 实际桶宽 | 点数 |
|---|---|---|---|
| 自动 | 5 分钟 / 1 小时 / 24 小时 | 1.0s / 6.0s / 144s | 301 / 601 / 601 |
| **1 分钟** | 5 分钟 | 60s | **6** |
| **1 分钟** | 1 小时 | 60s | **61** |
| **1 分钟** | 24 小时 | 60s | **1441** |
| 1 小时 | 24 小时 | 3600s | 25 |
| 1 秒 | 24 小时 | 17.3s（自动放宽） | 5001 + 提示 |
| 非法值 | — | — | HTTP 400 |

**URL 参数**：`?min=1440&bucket=60` 可直达某个特定视图（便于分享 / 书签）。

### 数据量与实测

`deadband` 模式（变化才写 + 10 秒心跳）：

| 场景 | 写入率 | 推算 |
|---|---|---|
| **稳态**（正常运行幕） | **5.33 条/分钟** | **1.8 MB/天** |
| 过渡幕（转速爬升中） | 31 条/分钟 | 约 10 MB/天 |

> 过渡期写入率升高是**正确行为** —— 转速每秒变化远超 deadband 阈值（10 rpm），
> 说明数据真的在变。稳态才是常态。

**关键经验：模拟的抖动幅度必须小于 deadband 阈值**，否则噪声会被当成真实变化，
每秒都触发入库 → SD 卡写入放大。这是嵌入式采集最容易踩的坑之一。

---

## 八、前端

单文件 `public/index.html`（内联 CSS+JS，**无 CDN、无构建步骤**）。

| 区域 | 内容 |
|---|---|
| 标题栏 | 时钟 + 数据年龄 |
| 健康条 | 在线/失联 + 报警等级徽标 + Inhibit/Configured/故障数 |
| 消息横幅 | 按语义着色（正常绿 / 警告黄 / 故障红 / 离线灰） |
| 指标卡片 ×4 | 转速 / 温度 / 电流 / 压差；无效时显示 `--` + `INVALID` 徽标并变灰 |
| 运行元信息 | uptime / mode / alarm / action / inhibit / configured / 有效性位 / 序号 |
| 趋势图 | uPlot 双轴折线；**时间范围**（1 分钟 / 5 分钟 / 1 小时 / 24 小时）+ **时间分辨率**可独立选择；`null` 区间**断线绘制不补 0** |
| 诊断 | 帧状态 / 帧年龄 / 质量 / 队列 / 丢弃 / 活动与锁存故障 |
| 39 维特征 | `<details>` 折叠，`frame_state=EMPTY` 时显示提示 |
| 事件表 | 带"确认"按钮 + 只看未确认 + 上下文摘要 |
| 审计日志 | `<details>` 折叠 |
| 数据库工具 | 统计 / 导出 CSV·JSON / 清理（需输入 `PURGE`） |
| 模拟器控制 | 跳幕 / 注入故障 / 传感器上下线 / 设模式 / 设目标转速（**仅原型**） |
| 页脚 | 边界声明（照项目文档口径） |

**趋势图：uPlot（本地自带）+ 手写 SVG 双路径**

主用 **uPlot 1.6.32**，文件放在 `public/vendor/`（**无 CDN**，离线可用）；
若 uPlot 未加载或渲染抛错，自动回退到原来那套手写 SVG，**功能不降级**。

选型依据（从 CDN 实测下载体积 + 本机无头 Chrome 实测渲染耗时）：

| 实现 | 体积(raw) | 渲染耗时 | null 断线 | 时间轴 | 缩放/游标 |
|---|---|---|---|---|---|
| 手写 SVG（回退路径） | 0 | 3.3 ms | ✅ | 自己写 | ❌ |
| **uPlot 1.6.32** | **52.9 KB** | **2.9 ms** | ✅ | 内置 | ✅ 内置 |
| Chart.js 4.5.1 | 259 KB | 30.2 ms | ✅ | 需 +51 KB date 适配器 | 需插件 |
| ECharts 5 | 1034 KB | 57.2 ms | ✅ | 内置 | ✅ 内置 |

关键约束（本项目特有）：

1. **无构建步骤** —— 板子上没有 node，所以只能用现成的单文件 UMD/IIFE 构建
2. **离线可用** —— 项目刻意不用 CDN，库必须落到 `public/vendor/` 由 lighttpd 自己送
3. **`null` 必须断线** —— 这是硬需求，四个库都支持，但配置项各不相同：
   - uPlot：`spanGaps: false`（默认值，代码里显式写出以防被改）
   - Chart.js：`spanGaps: false`（默认值）
   - ECharts：`connectNulls: false`（默认值）
4. **双 y 轴** —— 转速走左轴、温度走右轴，四者都支持

**为什么是 uPlot 而不是 Chart.js**：体积小 5 倍、渲染快 10 倍，而且时间轴、游标、
拖拽缩放、图例全部内置 —— Chart.js 光时间轴就要额外挂 51 KB 的 date-fns 适配器，
缩放还要再装插件。ECharts 用 1 MB 做这一件事太浪费，而且默认 y 轴从 0 起会把波动压扁。

**y 轴取值范围**：`padExtent()` 按数据范围 ±12% 留白，uPlot 与回退 SVG 用**同一套算法**，
避免两条路径画出来的图不一致。注意数据本身如果确实从 0 附近开始（例如启动爬升段），
轴覆盖到 0 是正确的，不要误当成 bug。

**对比演示页**：`/chart-compare.html` —— 同一份带两处 `null` 缺口的数据，
四种实现并排渲染 + 实测渲染耗时，用来验证「缺口断线」这条需求。

**关于体积的一个澄清**：图表是在**你的浏览器**里渲染的，不是板子上。
所以 Chart.js 的 259 KB 并不会消耗板子的资源 —— 选 uPlot 的理由是**离线分发体积**、
**首屏速度**和**少依赖**，不是板子 CPU。

**轮询**：status 1s / events 5s / health·stats·audit 15s；
history **随窗口自适应**（1 分钟窗口 → 1s，5 分钟 → 2s，1 小时 → 5s，24 小时 → 15s）。

每次 `fetch` 带 `AbortController`（2.5s 超时）+ `cache: 'no-store'`。
断连时健康条转红、实时值清空、按钮禁用，恢复后自动重连。

### ★ 防闪：只在「值真的变了」时才动 DOM

第一版每次轮询都 `innerHTML = ...` 重建卡片 / 元信息 / 诊断 / 徽标，
DOM 被销毁重建 → **每次刷新都闪一下**。而且 uPlot 每秒 `destroy()` + `new`，
整个 canvas 重建，闪得更厉害。

改法：

| 区域 | 做法 |
|---|---|
| 4 张指标卡片 | 建一次骨架，保留 `{card, pill, num, unit}` 引用，之后只改 `textContent` / `className` |
| 运行元信息 / 诊断 | 键集固定 → 建一次，按 key 取到 `<b>` 元素再改文本 |
| 健康徽标 | 4 个固定槽位，用 `display` 显隐 + 改文字，不重建 |
| 39 维特征 | 建一次 39 个格子，只改每格的数值 |
| uPlot | **只有首次创建；之后 `setData()`**，窗口尺寸变了才 `setSize()` |
| 事件表 / 审计 / 统计 | 把生成的 HTML 串缓存起来，**内容没变就整个跳过** |

关键工具（3 个 3 行的函数）：

```js
function setText(el, v){ if (el && el.__t !== v){ el.textContent = v; el.__t = v; } }
function setClass(el, c){ if (el && el.__c !== c){ el.className = c; el.__c = c; } }
function setHTML(el, h){ if (el && el.__h !== h){ el.innerHTML = h; el.__h = h; } }
```

⚠️ **事件表有个坑**：如果用 `setHTML` 跳过重建，但后面仍然重新
`querySelectorAll(".ackbtn").forEach(b => b.addEventListener(...))`，
保留下来的按钮会**重复绑定**，点一次发多次 ACK。
所以事件表是「HTML 没变就直接 `return`」，连绑定一起跳过。

**自检页** `/self-test.html`：在 iframe 里加载面板，给 DOM 节点打 JS 标记，
3 秒后检查标记是否还在 —— 节点被重建的话标记会丢。实测全部 ✅：

```
卡片节点存活    : ✅ 同一个节点（未重建）
meta 行存活     : ✅
徽标存活        : ✅
特征格子存活    : ✅
uPlot 实例存活  : ✅ 同一个实例（只 setData）
采样序号 5109 → 5111  ✅ 数据仍在实时更新
```

另外把「有效性位」这类长值改成占满整行（`grid-column:1/-1`）——
否则它换行会让行高变化，把下方内容顶一下，也是种视觉抖动。

### ⚠️ 踩过的坑：同一个元素不能有两个写入者

「数据年龄」这个位置一开始有两个写入者，结果每秒先闪一个假值再掉回来：

| 写入点 | 写的值 |
|---|---|
| `renderStatus`（/api/status 返回时） | 真实值 `数据年龄 28 ms` |
| `tick()`（每 1 秒） | 外推假值 `LAST.state_age_ms + 1000` → `数据年龄 1028 ms` |

用户看到的就是 `28 → 1028 → 31 → 1031 → …`。

而且这个外推**物理上就是错的**：`state_age_ms` 是「服务器读 state.json 那一刻文件有多旧」，
采集端每 100 ms 就重写一次文件，**年龄不会线性增长**，加 1000 ms 毫无意义。

→ 删掉 `tick()` 的年龄写入，`renderStatus` 作为唯一写入者；`tick()` 只管时钟。

> **后续按用户要求，「数据年龄」这个显示已整体移除**（顶栏那个和 `hmeta` 里的都去掉了）。
> 健康条的「在线 / 失联」已经足够表达数据新鲜度 —— 判定条件是
> `state_age_ms < 5000`，不需要把毫秒数暴露给用户看。

**更普遍的一条规则**：凡是用了 `setText` / `setClass` 的值缓存，**所有写入都必须走同一个封装**。
`setOnline()` 里原本直接 `classList.add("invalid")`，缓存 `__c` 仍是 `"card"`，
恢复连接后 `setClass(card, "card")` 会误判「没变化」而跳过 → 卡片永久变灰。
改成走 `setClass` 后缓存与实际才一致。

---

## 九、端到端测试结果（16 项）

| # | 项 | 结果 |
|---|---|---|
| 1 | `/api/health` | `ok:true, db_ok:true, collector_running:true` |
| 2 | 模拟器跳到「传感器上线」 | 测量值从 `null` 变为有效 |
| 3 | 模拟器跳到「温度硬故障」 | `alarm=3, action=INHIBIT` |
| 4 | 事件检测 | `TEMP_WARN`(L2) + `TEMP_HARD`(L3) 正确生成 |
| 5 | ACK | 成功，写审计 |
| 6 | ACK 不存在的 key | **404** |
| 7 | 审计日志 | `ack` / `mock:*` 都留痕 |
| 8 | 历史聚合 | 无数据桶为 `null` 而非 0 |
| 9 | 数据库统计 | 行数/文件大小/WAL 正常 |
| 10 | 导出 CSV | 带 UTF-8 BOM、`Content-Disposition` 正确 |
| 11 | purge 未带 confirm | **400** |
| 12 | `GET /api/ack` | **405** |
| 13 | 70KB 请求体 | **413** |
| 14 | 路径穿越 / 脚本直访 | 404 / 403 |
| 15 | **源码无 UIO 设备路径** | **✅ 无命中** |
| 16 | ACK 后事件仍 ACTIVE | 确认（不改变硬件状态） |

---

## 十、搬到开发板（DR1M90G）要做的事

### 轮询负载与 CGI → mod_proxy 迁移（已实测）

面板的轮询率（「1 分钟窗口」下）：

| 端点 | 周期 | 频率 |
|---|---|---|
| `/api/status` | 1 s | 1.00 req/s |
| `/api/history` | 1 s（1 分钟窗口） | 1.00 req/s |
| `/api/events` | 5 s | 0.20 req/s |
| `/api/health` `/api/stats` `/api/audit` | 15 s | 各 0.07 req/s |
| **合计** | | **≈ 2.4 req/s** |

#### 迁移前：CGI

用 `/proc/<pid>/stat` 的 `utime+stime+cutime+cstime` 实测
（含 lighttpd 与所有 CGI 子进程）：

```
60.7 ms CPU / 请求  →  2.4 req/s 占单核 14.6%
```

拆开看，**97% 是固定开销**：

| 层 | 耗时 | 占比 |
|---|---|---|
| 解释器启动 | 16.5 ms | 56% |
| 导入模块 | 12.0 ms | 41% |
| 真正的业务逻辑 | 0.9 ms | 3% |

> 60.7 ms 是**混合流量的平均**，不是单端点值。单测 `/api/status` 只有 29.4 ms；
> `/api/history`（601 个桶 × 8 条数组）和 `/api/stats`（多个 COUNT）都更重。

换算到 Cortex-A35，按解释器启动慢 5~12 倍估：**单核 73% ~ 175%**。
板子只有 2 核且 LVGL 软渲染本身就吃满一个核 —— 照 CGI 上板帧率大概率会掉。

#### 迁移后：mod_proxy + 常驻后端

```
4.86 ms CPU / 请求  →  2.4 req/s 占单核 1.2%
```

| 模式 | 每请求 CPU | 2.4 req/s 占单核（x86 实测） |
|---|---|---|
| `mod_cgi` | 60.7 ms | 14.6% |
| **`mod_proxy` + 常驻** | **4.86 ms** | **1.2%** |

**快了 12.5 倍。** 而且板子上不再有「解释器启动」这一项，8 倍外推不再适用于主要开销，
实际占用会比 CGI 时期的估算低一个数量级。

> 测量脚本 `load-test.py` 会**同时统计 lighttpd 和 apiserver 两个进程** ——
> mod_proxy 模式下后端是独立进程，它的 CPU 不在 lighttpd 的 `cutime` 里，
> 只测 lighttpd 会严重低估。

### 为什么不选 FastCGI

FastCGI 能达到同样的效果（进程常驻），但：

- **`python3-flup` 在 Debian 13 已无候选版本**（实测从仓库移除）
- `fcgiwrap` 只是「FastCGI 包一层 CGI」，**每请求照样 fork**，固定开销一分不省
- 手写 FastCGI 记录协议要 ~200 行，而 `mod_proxy` **零协议实现**（`http.server` 是标准库）

lighttpd 的 `mod_fastcgi` 本身没被弃用、还支持 `bin-path` 自动拉起进程，
但 Python 侧没有现成库，性价比不如 `mod_proxy`。

> 如果要彻底去掉 Python 依赖，还有一条路：**后端用 C/C++ 链接 `libfcgi`**。
> 依赖都齐（gcc 14.2、libfcgi-dev 2.4.5、libsqlite3-dev、cjson），
> 但要重写约 1500 行业务逻辑 —— 收益是内存（~3 MB vs ~15 MB）和启动速度，
> **CPU 上和 mod_proxy 是同一档**。属于长期架构选择，不是当前的必要项。

### 其余步骤

代码本身**不用改**（Python 3.6 兼容、SQLite 3.22 兼容），只需：

1. **装 lighttpd**（板子 apt 可用，华为云源实测 373 kB/s）
   ```bash
   sudo apt-get install -y lighttpd
   ```
2. **关掉模拟器**：`config.json` 里 `mock.enabled = false`
   （`/api/mock` 会自动返回 403，前端也会自动隐藏模拟器控制面板）
3. **指向真实的 state.json**：`paths.state_json` 保持 `/run/cabinet-live/state.json`
   （由现有的 `reader.py --live` 产出）
4. **改访问地址**：板子 IP 见 `hostname -I`，直接用 `http://<板子IP>/`（80 端口，不用写端口号）
5. **删掉 `cabinet-web-mock.service`**（`install.sh` 里按需调整）

> ⚠️ 镜像同步按项目约定：**只在用户明确要求时才做**，不要主动同步。

### 已上板实录（2026-10-18，DR1M90G）

板子实测：aarch64 / **Python 3.6.9** / **lighttpd 1.4.45** / 989 MB 内存 / 29 G 磁盘。
部署在 `/home/uisrc/web/`，访问 `http://192.168.0.126/`（80 端口）。

**三个只在板子上才会踩到的坑**：

| 坑 | 现象 | 修法 |
|---|---|---|
| **locale 是 C** | `LANG` 为空、stdout = `ANSI_X3.4-1968`。`open()` 不带 encoding 会 `UnicodeDecodeError`；print 中文会 `UnicodeEncodeError` | 所有 `open()` 显式 `encoding="utf-8"`；print 只用 ASCII；systemd 单元加 `PYTHONIOENCODING=utf-8` |
| **lighttpd 1.4.45 无 `proxy.forwarded`** | 该选项 1.4.51 才有；写了只打一行 warning 被忽略 | `install.sh` 按版本生成配置（≥1.4.51 才启用） |
| **`setenv` 的 `remoteip` 不展开** | 1.4.45 把字面字符串 `"remoteip"` 原样传给后端，审计 actor 记成 `remoteip` —— **比 127.0.0.1 更糟（误导）** | 老版本直接放弃透传，actor 记 `127.0.0.1` |

> 结论：**lighttpd < 1.4.51 无法把客户端 IP 透传给后端**。板子上审计日志的 actor
> 会是 `127.0.0.1`；VM（1.4.79）能记到真实客户端 IP。

**真实数据源**：板子上 `cabinet-edge.service` + `cabinet-live-display.service`（`run_live.py`
→ `cabinet_dashboard`）产出 `/run/cabinet-live/state.json`，**210 个 display 字段**
（模拟器只有 62 个），`state_reader.derive()` 解析正常。

模拟器写的是**独立的** `mock_state.json`，不会污染真实 `state.json`；
但若把 `paths.state_json` 指过去，面板显示的就是模拟数据 —— 上真机务必改回。

---

## 十一、已知限制

- 原型期数据来自 `mock_device.py` 模拟器，**不是真实硬件数据**
- lighttpd / apiserver 均以 root 运行（与板子现有 `cabinet-live-display.service` 一致）；
  后续可建专用用户 + `setfacl` 让 `/run/cabinet-live/` 可读，然后去掉 `User=root`
- 无用户认证（内网、只读 + 审计场景下按设计可接受）
- 分级保留（原始 7 天 / 小时级 2 年）**尚未实现**，当前是单级 `retain_days=90`
