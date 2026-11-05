# Anlogic 机柜风冷监测与控制项目

本仓库收录 2026-11-04 完整源码包，对应 R46 / P52 工程。2026-11-05 上传准备时，已核对本机 FPGA、Linux 和训练源码没有新增实质改动；TD 工程的 `Project Path` 已改为相对路径，便于换电脑。

## 目录

| 目录 | 内容与入口 |
| --- | --- |
| `01_TD_Project` | FPGA RTL、IP、引脚和时序约束、布线数据库、比特流与 BootGen 输入；主工程 `fpga/cooling_link.al` |
| `02_Board_Runtime/linux` | 从板端读取的运行代码：采集、温度/PWM 控制、NPU、HDMI 显示、网页接口和服务模板 |
| `03_NPU` | 当前及保留模型、NPU 动态库、C++ 源码、训练主机代码、运行依赖和驱动适配 |
| `04_Website` | 观测网站、自动学习网页、接口代码及本机授权网关 |
| `05_Config` | 脱敏配置、systemd 服务、本机启动配置和网页令牌模板 |
| `06_Version_Records` | 快照、构建与验证记录、版本哈希、板端与本机代码差异 |
| `07_Local_Source` | 本机开发源码和训练主机运行副本，保留其与板端的差异 |

完整文件索引和换电脑说明见 [README_先读我.txt](README_先读我.txt)。文件完整性清单见 [SHA256SUMS.txt](SHA256SUMS.txt)；该清单覆盖原始交付快照，不含 GitHub 上传时增加的本 README 和 `.gitignore`。

## 使用入口

- **FPGA**：在兼容版本安路 TD 中打开 `01_TD_Project/fpga/cooling_link.al`。器件 `DR1M90GEG400`，速度等级 `-2`。历史版本 `TD 6.2.200067`。
- **板端代码**：主入口 `02_Board_Runtime/linux/run_edge.py`，服务依赖见 `05_Config/systemd/`。复制代码之前应核对硬件、内核和配置；本仓库不会自动烧录设备。
- **NPU 训练主机**：代码与依赖列表位于 `03_NPU/host_running/`。按 `requirements.txt` 重建环境，并调整目标设备地址及本机路径。
- **学习与配置网页**：`04_Website/commissioning_8766/`；完整 Python 运行依赖在 `02_Board_Runtime/linux/`。
- **观测网页**：`04_Website/monitor_8080/`，包含前端、API、数据采集器和安装脚本。

## 版本与验证边界

本仓库是源码和已有构建产物的存档，上传操作不等于重新综合、重新训练或部署。已收录的 `build_008` 历史记录仍为 setup WNS `-0.008 ns`、`timing_pass=false`；请保留这一事实，勿将代码上传表述为时序重新通过。

板端运行版本与本机开发副本分别保存；以 `06_Version_Records/board_snapshot.json` 和 `05_Config/etc_cabinet/normal-npu.env` 确定快照时的模型选择。其他模型目录的存在不表示已经启用。

## 配置与数据

- 未包含真实网页令牌、SSH 私钥或登录密码；`web.env.example` 需要在目标机器配置。
- 未包含全量原始采集、运行数据库、虚拟环境、商业 TD/FD 安装器或完整 Linux 内核源码。
- 原始采集数据仍保存在原设备；此仓库的导出和上传不会删除这些数据。
- 部分 Arm NN 等第三方运行依赖和供应商 IP 按原项目目录保留，其权利归原作者所有；本仓库未对第三方内容重新授权。
