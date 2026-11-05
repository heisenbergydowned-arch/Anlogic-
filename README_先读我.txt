安路机柜风冷项目：当前代码完整导出
打包日期：2026-11-04T01:53:34.007873-08:00
板端快照：192.168.0.107，/opt/cabinet/releases/r46_alarm_only_pwm_p52_20261103/linux

目录与入口
01_TD_Project/fpga/cooling_link.al：TD 主工程，包含全部 123 个文件引用、RTL、IP、引脚约束、时序约束。
01_TD_Project/build_008：已完成布线数据库 alarm_only.pr.db、比特流和构建验证记录。
01_TD_Project/build_parent：增量修改所用的父数据库。
01_TD_Project/BootGen：BOOT.bin、cooling_link.bit、两份 ELF 和 BIF，构成完整打包输入。
01_TD_Project/build_tools：原始构建/验证/安装脚本。历史脚本中有原电脑绝对路径，需要根据新电脑路径调整；不要直接批量运行。
02_Board_Runtime/linux：本次从板子读回的实际运行代码，含 NPU 服务、采集、控制、HDMI、网站后台和 systemd 模板。
03_NPU/host_running：本机实际运行的训练 worker、网关、编译器封装、依赖列表和启动器。
03_NPU/models_and_native：SD 卡现有模型及动态库，包含当前选中版本和其他保留模型。
03_NPU/board_sdk：板端 Arm NN/ONNX 解析器运行库与 SDK 文件。
03_NPU/native_source：正常工况 NPU C++ 源码、构建记录和动态库；native_offline_r2/validation.json 记录了与运行动态库对应的 SHA-256。
03_NPU/driver_candidate4：NPU 驱动适配源码补丁、模块和原生接口。
03_NPU/saved_training：已保存的训练候选文件；是否处于启用状态以当前选择文件为准。
04_Website/commissioning_8766：自动学习页面及网站接口；完整后端依赖在 02_Board_Runtime/linux。
04_Website/monitor_8080：观测网站的当前前端、API、采集器、配置和安装脚本。
04_Website/gateway.py：本机 18768 授权网关代码，与 host_running 中版本相同。
05_Config：板端配置、服务文件和本机启动配置。敏感字段脱敏，web.env 仅提供模板。
06_Version_Records：本次板端快照、文件哈希、TD 构建记录和板端/本机差异清单。
07_Local_Source：当前本机开发代码及本机 host runtime 副本，保留与板端的差异，未自动合并。

当前模型选择（只记录，不执行部署）
BUNDLE=/opt/cabinet/npu/learned/baseline_20261104_5c119_001/bundle
BUNDLE_SHA256=4edf2cc5d189cd50aa8710167313bb39c2c67725f3fbea9b5562e3b6b474f0a8
LIBRARY_SHA256=70256ce5a102eff026be96876b2a9ae8f1df75699cdff0d3bdcadc0078aa9069
当前选择文件以 05_Config/etc_cabinet/normal-npu.env 为准；请勿把其他模型文件夹的存在当成已部署。

换电脑使用
- TD：建议将整个 01_TD_Project 解压到英文路径。打开 fpga/cooling_link.al，选择 DR1M90GEG400、速度等级 -2，原版本为 TD 6.2.200067。
- .al 内源文件相对路径完整；仅将主工程里的旧 Project Path 规范化为 '.'，RTL 未为打包改动。
- regenerate_bit_from_saved_db.tcl 可在兼容版本 TD 命令环境中从随包数据库生成比特流；此包没有进行新的综合/布线。
- 当前 build_008 的历史 setup WNS 为 -0.008 ns，原验证记录 timing_pass=false；打包不代表时序重新通过。
- Linux/NPU：保留原目录依赖和模型哈希。Python 板端为 3.6；不要把 macOS .venv 复制到板子或 Windows，按 host_running/requirements.txt 重建主机环境。
- NPU 驱动补丁对应既有 candidate4 内核环境，不是完整 Linux 内核源码或 TD/FD 安装器。
- 18768 是本机网关；8766 是板端调试/学习网站；8080 是独立观测网站。
- 部署前按实际电脑和网络调整 LaunchAgent 的绝对路径、板子地址；账号密钥和网页令牌需在目标机器自行配置。

范围
这是代码/模型/依赖的只读导出，没有写 SD、没有切换模型、没有启动新训练、没有重启板子。
未包含全量原始训练采集、历史运行数据库、日志、旧备份、macOS 虚拟环境，以及商业 TD/FD 安装器；这些原数据仍留在原位置。
原始历史 WORK_STATUS/installation/manifest 收在版本记录中，可能早于当前状态，当前状态优先看 board_snapshot.json。
全包文件 SHA-256 见 SHA256SUMS.txt，验证结果见 06_Version_Records/package_validation.json。
