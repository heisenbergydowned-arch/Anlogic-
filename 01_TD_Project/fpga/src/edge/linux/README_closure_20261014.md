# 单采集器 Linux 源码交付（2026-10-14）

完整树交付，不是 HMI 文件夹单独覆盖，也不是 SD/BOOT 镜像。保留既有设备配置、数据库、凭据、SDK 和模型，不从示例生成假标定资格。

- `run_edge.py --live --no-http --local-display` 是唯一硬件消费者，分发到模型、日志、显示与网页学习。
- `cabinet/local_display.py` 仅处理有界、不可变观察副本，SQLite/RPC/显示不阻塞硬件线程；丢包、积压、模型失效与陈旧结果均安全拒绝/中止学习。
- `hmi_daily/run_live.py` 默认只监督 LVGL，不打开 UIO、不另启采集器。只有显式 `--managed-collector` 开发模式管理同一个整合后端。
- `hmi_daily/reader.py --live` 须再显式指定 `--standalone-diagnostic`；诊断前停掉正式采集，不取消原生独占锁让两个消费者抢帧。
- 标准库运行路径按 Python 3.6 兼容；主机语法/API 和回归通过不等于板端运行已验收。外部 NPU/ONNX 依赖仍按实际 BSP 确认。
- 在 ARM Linux 用 `make -C native` 构建 .so；LVGL 用 hmi_daily Makefile 与核验过的 9.4.0 源码编译。当前屏幕 C 源码只读按钮与文件年龄检查已更新，新 ARM UI 二进制未构建/验收。
- 正式部署由 `systemd/cabinet-edge.service` 管采集/本地发布，`cabinet-local-display.service` 管只读显示；先停旧显示采集服务，再核对配置与唯一所有者。本交付不自动安装/enable 服务。
- 部署配置使用 `/etc/cabinet/edge.json` 与 `/etc/cabinet/learning.json`，设备与合同必须匹配，基线 `/var/lib/cabinet/baselines.sqlite3`；缺失或不合格保持拒绝。
- 默认模型、外环、控制所有权与外部负载执行保持禁用/未合格；没有真实模型和证据，不把 CPU、mock 或缺失结果冒充 NPU 正式结论。
- 网页学习仍是出站 HTTPS，不暴露 root socket；具体信封/exchange 见项目 24/25 文档。真实后台、凭据和校时未具备前不启用代理。

本轮主机门禁：Linux 46 项、HMI/学习代理 108 项全部通过，含原生独占锁；33 个运行文件通过 Python 3.6 语法检查。单独 `--mock --no-http --local-display` 子进程只验证程序链，TEST 保持隐藏/拒绝学习。

FPGA 当前 TEST 完整新构建与 REAL 同源综合检查点＋r5 新物理实现均通过工程门禁，包含 SDP810 源码。TEST Setup/Hold +0.018/+0.022ns，REAL 0.000/+0.020ns，双角 routed、STA 99.97%；REAL 报告无违例端点，但处于临界裕量，不能承诺生产可靠性。当前权威记录为交付包 `evidence/td/test/validation.json` 与 `evidence/td/real/validation.json`，不引用旧位流正时序。没有烧录、替换 SD 或制作新的 BOOT.bin。真实传感器、PI、NPU 和整机验收仍需台架及对应负责人，详见随包 26 收口文档与验证清单。
