# FPGA 控制、保护与报警实现（FCB1 v1）

> **2026-10-23 当前功能边界修正：取消自动断电。** 不再提供风机供电使能、热负载降额/停机执行器、执行回执或 LOAD_STATUS 命令。保留 PWM 调速/限幅/禁止、独立硬保护、锁存、声光/RS485/网站告警及人工处置提示。J12-22/W8 改为高阻备用，弱下拉。PWM=0 不等于停转，更不等于断电。健康基线自适应不能覆盖保护、清锁存或学习故障为正常。最新候选和验证状态见 `46_取消断电逻辑与清理验收_2026-10-23.md`；旧交付包与板上固件不会自动改变。

> 2026-10-09收口更新：39维特征缓存/频带共享累加、WAV1与PS完整链路已接入；本轮仿真和独立综合、完整TEST/REAL位流状态分开验收，见 [FPGA交付记录](../edge/FPGA_DELIVERY_20261009.md)。下文旧未接入/资源数据按其日期理解。


**2026-10-08接入更新**：FCB1已通过整组CDC和GP0 AXI扩展连入PS的0x80400000页；PL UART与PS共用CSR，维护流程必须唯一写者。完整39维、Linux事件/上报与只读RS485见 [edge README](../edge/README.md)。原控制11组回归通过，物理标定与本轮整机/实板状态仍按最终证据验收。下文10月7日“AXI/PS未接入”是历史说明。

日期：2026-10-07。活动工程：`D:\Desktop\FU_Code\soc_merge\soc_merge\soc_prj.al`，顶层 `system_top`。

本目录按 [07_功能边界与报警控制README](D:/Desktop/选题四_机柜风冷边缘智能测控/07_功能边界与报警控制README.md) 实现 PL 的转速内环、快速保护、故障恢复、声光报警及控制寄存器，并已接入 `src/acq/subsys_acq.v`。GPIO、传感器接口与 `design_0` 的视频/NPU连接不变。具体验证结果见末节。

**源码与 RTL 验证已完成；物理阈值、整机布线与实板验收尚未完成。当前 SD 卡/旧 bitstream 不包含这些新逻辑。** 本目录不代表 39 维重叠窗口、PS 数据通路、模型调度或网站已完成。

## 1. 已接入的逻辑

| 文件 | 作用 |
|---|---|
| `cooling_control.v` | 控制顶层、独立租约、控制权限、目标斜坡、事件队列、传感器与保护串接 |
| `safety_monitor.v` / `fault_filter.v` | 新样本判定、ADC/温度年龄、原始码保护、持续确认与恢复迟滞 |
| `rpm_measure.v` / `rpm_pi.v` | 周期换 RPM；Q8 PI、输出限幅、抗积分饱和、实际输出跟踪、旧样本不重复积分 |
| `protect_fsm.v` / `control_arbiter.v` | 有限起动与暂态；严重原因锁存；仅仲裁 PWM 动作，不控制供电 |
| `alarm_outputs.v` / `cooling_buttons.v` | L2/L3 间歇蜂鸣、新故障打破消音、按键去抖、本地复位与维护许可 |
| `cooling_regs.v` / `cooling_uart.v` | 版本化寄存器、原子配置、幂等命令、115200/8N1/CRC16串口收发 |
| `cooling_axi_lite.v` | 可选同域 AXI-Lite 从接口，独立验证；尚未连入 `design_0` |

实际入口：AD7606 CH1电流 / CH2压差、DS18B20-B器件温度、FG周期与脉冲数、双 ICM 六轴及质量状态。ADC 采样仍为 50kS/s/通道，PI 默认每10ms尝试更新一次，仅在该周期有新的有效 RPM 时积分；不等待 FFT、PS、串口或网络。

实际输出：20kHz PWM、蜂鸣器使能、外部红绿灯与 LED4报警闪烁。FCB1 占空比保持 0..4000 归一化单位，输出端映射到 5000 拍周期，手动档位和 PI 量纲不变。绿灯改为“合格、无报警的自动稳态RUN”，WHO_AM_I通过不能使其亮绿。板载LED3仍为采集心跳，原调试串口帧格式保留。

原改动已备份到 `backups/control_before_20261007/`，含哈希清单。此次未编写 SD 卡启动程序，未替换已有位流。

## 2. 启动与标定边界

- `CONTROL_BENCH_ENABLE=1` 保留原台架启动50%（2000/4000计数）和KEY1分档，标记 `test_mode`，默认配置ID与所有合格位为0，拒绝自动目标转速请求。它是演示输出，不是已验收的安全占空比。
- `CONTROL_BENCH_ENABLE=0` 且配置不合格时抑制PWM并提示配置未合格，不用默认占空比冒充已验证回退；未合格时不启动起转失败计时。**PWM抑制仍不等于电源断开**。
- 电流阈值单位是 `abs(ADC原始有符号码 - 标定零点)`，采用17位无符号幅值，未假定A/码增益。短路、轨限或数据超时按质量失效处理。
- 温度使用有符号 `1/16℃`，只接受新有效转换；有效0℃正常，短路/断线/陈旧值不能成为恢复证据。
- 可选振动规则使用安装状态下的原始三轴绝对幅值峰值。它包含直流/重力，不是窗口FFT能量或去均值RMS；只有该口径经过实测验证才能置振动合格位。
- PPR、最低可用转速、PWM极性/最小起转值/回退值、过流码、温度边界和PI增益都必须实测后填写；购买页面的6000RPM不等于PPR或安全阈值证据。

模板 [config_unqualified.template.json](config_unqualified.template.json) 不含已标定的阈值。仿真的数值仅为验证向量，严禁复制到实板配置作为安全值。合格自动控制需配置位0–3全部为1，且配置ID非0；振动规则另由位4启用。

## 3. 故障、动作和恢复

`active` 表示当前确认原因，`latched` 表示尚未完成本地解除的严重原因。多个原因按位并存。

| 位 | 原因 | 级别 | 行为 |
|---:|---|---|---|
| 0 | `OC_HARD` 快速过流 | L3，锁存 | 抑制PWM；L3声光告警 |
| 1 | `CURRENT_HIGH` 持续高电流 | L2 | 限制风扇占空比；分级告警 |
| 2 | `TEMP_WARN` 持续高温 | L2 | 增风；分级告警 |
| 3 | `TEMP_HARD` 严重过热 | L3，锁存 | 保留增风；L3声光告警 |
| 4 | `CURRENT_PROTECTION_LOST` 运行所需保护失效 | L3，锁存 | 回退占空比；L3声光告警；不宣称仍有过流保护 |
| 5 | `TEMP_LOSS` 器件温度无效 | L2 | 退出PI、回退；分级告警 |
| 6 | `FG_LOSS` 反馈无效 | L2 | 退出PI、回退；不单凭FG丢失证明机械卡死 |
| 7 | `START_FAIL` 起转截止时间内无有效反馈 | L2，锁存 | 抑制PWM；无自动无限重试 |
| 8 | `STALL_CORROBORATED` FG丢失且持续高电流 | L3，锁存 | 抑制PWM；L3声光告警 |
| 9 | `OVERSPEED` 合格反馈超速 | L3，锁存 | 抑制PWM；L3声光告警 |
| 10 / 11 | `VIB_WARN` / `VIB_HARD` 合格独立振动规则 | L2 / L3锁存 | 限制 / 抑制PWM；分级声光告警 |
| 12 / 13 | `PS_LOSS` / `CMD_EXPIRED` | L2 | 已交出控制权后心跳或目标租约超时，或本地手动租约过期；回退 |
| 14 / 15 | `DIAG_LOSS` / `AUX_LOSS` | L1 | ICM/压差质量或辅助环境传感器失效；维护事件，保留独立控制 |
| 16 | `CONFIG_UNQUALIFIED` | L1 | 未标定/台架；不进入AUTO |
| 17 | `TRACK_ERROR` 饱和且持续跟踪失败 | L2 | 持续跟踪失败告警；正常暂态不算故障 |
| 18 | `STOP_UNCONFIRMED` 规定时间内FG不安静 | L1 | 记录停止未确认；不以PWM=0代替停转证据 |
| 19 / 20 | `SOFT_PS` / `SOFT_EXPIRED` | PS融合级别 / L1 | 有期限的上层证据；过期标为未知；不能改变风扇动作或清硬故障 |

动作优先级：严重风扇电气/机械风险 > 有依据的风扇限幅 > 温度增风 > 失效回退 > 合法停风/正常控制。比如过热与过流同时出现，记录两个原因，抑制风扇驱动并提示人工处置热源；单独严重过热保持增风。

新样本快速过流通路在样本有效与数据稳定后的两个时钟上升沿内使PWM输出为低（100MHz时不超过20ns，不计ADC采样/模拟前端/管脚传播）。温度、振动、超速也通过高速保护通路；需要持续确认的L2规则计时单位为ms。输入在轨限时转为质量失效，不能据此证明真实机械故障。

模式编码：0 BOOT，1 READY_OFF，2 STARTING，3 RUN，4 TRANSIENT，5 STOPPING，6 MAINTENANCE，7 LOCKED，8 FALLBACK。连续START/改变目标不能延长同一次起转/暂态截止时间；FG失效冻结PI。ADC或器件温度无效时，退出合格RUN/MAINT状态，显示FALLBACK或已有严重锁存对应的LOCKED，不能一边回退一边报稳态正常。

严重原因恢复后，锁存不自动解除；必须有当前有效、低于恢复界限且持续稳定的关键输入，再用KEY2本地长按请求。无效数据、远程ACK、模型“正常”、心跳都不能清锁存。热锁存解除前继续增风；故障风扇锁存解除前继续抑制PWM。

`fan_action`：0 PI、1 BOOST、2 LIMIT、3 INHIBIT、4 FALLBACK、5 OFF、6 MANUAL、7 STARTUP。
旧负载请求字段已移除；事件 meta[10:9] 和状态字31的原负载相关位保留为0，不改变其他字段偏移。opcode 6 始终拒绝（错误3）。

## 4. 蜂鸣、确认与本地权限

L1静默；L2需现场处置原因按200ms/2s间歇；L3物理故障每2s内四次200ms鸣叫。普通诊断/模型维护默认不鸣叫。PS已融合物理证据可请求声光，不能否决本地保护。

KEY1去抖后分档：0→25%→50%→75%→100%→0；上电分档为50%。已由PS控制时需本地维护许可才能抢占。手动模式有租约，超时回退；重新提交合法PS目标可交还自动控制。

KEY2短按：限时本地消音。新原因、鸣叫等级升高或消音到期恢复蜂鸣；红灯/事件/保护不变。KEY2长按2s：一次本地复位请求，同时授予60s本地维护/配置许可；不持续重复复位。远程ACK仅标记已确认，远程接口没有RESET或SILENCE命令。

停止请求要求有效器件温度、本地许可、无温度增风原因且无严重热锁存；不等待外部负载回执。FG所有脉冲计数用于停止安静确认；起转第一脉冲也计入，不把“没有完整周期”误当安静。

蜂鸣器模块已由用户确认**低电平响**。内部 `alarm_outputs.buzzer` 保持高有效鸣叫请求，`system_top` 在 Y13 物理输出端反相：正常、一级提示、消音和逻辑复位期间输出高电平；需要鸣叫时输出低电平。FPGA 尚未完成配置时的引脚电平仍取决于板端上拉与模块电路；修复后的实际声音须上板验证。PWM=0对四线风扇的实际含义必须按该风扇实测，不能宣称已切断风扇12V或被散热负载电源。

## 5. 寄存器协议

32位字，地址按4字节对齐。读取/配置在同一100MHz采集时钟域内，寄存器一周期响应，合法控制副作用在随后一个时钟执行。

| 字节地址 | 访问 | 内容 |
|---|---|---|
| `0000` / `0004` | R | `0x46434231`（FCB1）/ `0x00010000` ABI |
| `0008` | R | `[15:8]`配置错误，`[7:0]`命令错误 |
| `000c` / `0010` | RW | 暂存命令ID / payload |
| `0014` | W/R | 写命令低8位执行（高24位0）；读上次opcode |
| `0018` | W/R | 写`0x434f4d54`（COMT）原子提交；读24位已写位图 |
| `001c` / `0020` / `0024` | R | 能力状态 / 上次命令ID / 活动配置ID |
| `0080..009c` | R | 队首事件8字；CMD8按序号弹出 |
| `0100..017c` | R | 实时状态32字 |
| `0300..035c` | RW | 配置暂存24字，所有字须重新写入才能提交 |
| `0500..055c` | R | 当前配置24字 |
| `0700..077c` | R | CMD7在一个时钟冻结的状态快照 |

错误码：0成功，1地址/格式，2配置/范围，3本地许可，4序号不匹配，5关键输入无效，6严重锁存，7心跳超时，8本地手动租约拥有控制权。

命令写法：先`000c=新ID`，再`0010=payload`，最后`0014=opcode`。同一命令ID、opcode、payload重试返回原结果，不重新执行、不续租、不再次弹出事件。相同ID改payload和重放旧ID返回4。新ID按32位半环范围递增；单次跳跃小于2³¹。

| opcode | 命令 / payload |
|---:|---|
| 1 | SET_TARGET：uint16 RPM，高16位0；须已标定、心跳新鲜、关键输入合格且无锁存；刷新目标租约 |
| 2 | STOP：0；还需有效停止许可，刷新目标租约 |
| 3 | HEARTBEAT：0；只刷新心跳，不刷新目标 |
| 4 | ACK：当前 `event_seq`；确认不能消音/复位 |
| 5 | SOFT_ALARM：byte0低2位等级，bit4已确认物理证据可鸣叫，其余0；byte1=消息版本1；高16位source_code（非零等级需非零来源） |
| 6 | 已撤销；任何 payload 均拒绝，错误3，不执行任何动作 |
| 7 | SNAPSHOT：0；冻结全部32个状态字 |
| 8 | POP_EVENT：当前队首事件序号，精确匹配才弹出 |

SOFT_ALARM的版本1是**消息ABI版本**，不是已验证的模型版本。PS必须先验证真实39维输入的frame_seq、时间、配置/频带/模型版本、质量与工况，然后下发融合后的软事件。PL不能在尚未接通的特征帧上替PS完成这些校验。

配置先写暂存，边界/格式全部验证后整体生效；失败保留最后有效配置。初次未合格台架可凭本地许可提交；一旦任一规则合格，替换配置需当前本地拥有控制、无锁存、负载已关许可、已确认OFF，禁止维护许可在运行中禁用现有保护。配置ID必须非0且不同于当前ID，复位后需要重新加载，PL无持久化Flash承诺。

### 配置24字

除标明32位/符号者，每字低16位、高16位依次如下，定时单位ms，占空比归一化单位0..4000（4000 为 100%，不是新周期的原始拍数）。

| 字索引 | 低位 | 高位 |
|---:|---|---|
| 0 | 合格位：bit0电流、1温度、2执行器/回退/FG、3 PI、4振动，其他0 | — |
| 1 | 配置/标定ID（32位） | — |
| 2 | startup_duty | fallback_duty |
| 3 | boost_duty | limit_duty |
| 4 | duty_min | duty_max |
| 5 | rpm_min | rpm_max |
| 6 | kp_q8 | ki_q8 |
| 7 | current_zero（int16） | current_high（绝对码差） |
| 8 | current_hard | current_recover |
| 9 | temp_warning（int16，1/16℃） | temp_hard（int16，1/16℃） |
| 10 | temp_recover（int16） | vibration_limit |
| 11 | vibration_hard | byte2 PPR=1..8，byte3=0 |
| 12 | target_slew（RPM/控制更新） | tracking_error（RPM） |
| 13 | adc_age_max | device_temp_age_max |
| 14 | fg_age_max | recovery_ms |
| 15 | startup_ms | transient_ms |
| 16 | stop_ms | manual_lease_ms |
| 17 | heartbeat_ms | target_lease_ms（也用于负载声明） |
| 18 | current_confirm_ms | temp_confirm_ms |
| 19 | tracking_confirm_ms | vibration_confirm_ms |
| 20 | silence_ms | soft_lease_ms |
| 21 / 22 | FG最小/最大周期（32位时钟计数） | — |
| 23 | overspeed_hard_rpm | 0 |

PI定义：`P=error*kp_q8`，`I+=error*ki_q8`，最终PWM为Q8右移8位后限幅。ki对应**每次有新FG信息的控制更新**，不是固定连续时间积分常数；先验证实际FG刷新周期再整定。

### 状态与事件

status0位0..18：silenced、acknowledged、pi_saturated、cooling_lost、hard_inhibit、stable_run、soft_good、manual_live、target_good、hb_good、rpm_valid、adc_valid、temp_valid、pressure_valid、configured、local_permit、reset_accepted、reset_rejected、test_mode。复位结果是单时钟脉冲，不是永久日志。

status1 uptime；2 meta；3 active；4 latched；5开机以来seen_sources；6峰值等级；7低/高=实际/手动PWM；8实际/请求RPM；9 PI输出/斜坡RPM；10..14 ADC/温度/RPM/心跳/目标年龄；15事件序号；16丢事件计数；17队长；18配置ID；19上次命令ID；20错误码；21电流绝对码差；22原始电流/压差；23温度原始int16；24 FG周期；25 FG脉冲计数；26FG安静年龄；27被拒周期计数；28串口坏帧；29串口忙丢帧；30软结果年龄；31低2位负载声明、bit2软物理证据、bit3新鲜负载已关、高16位软来源。

meta低16位：bit1:0等级，5:2模式，8:6风扇动作，10:9保留为0，11消音，12确认，13台架/本地模式，15:14保留。

每个事件8字：序号、uptime_ms、active、latched、meta、变化原因位图、配置ID、入队时累计丢事件数。FIFO深度8，L1最多占6格、L2最多7格，给更严重事件预留空间。高等级连续变化仍可能填满；序号、饱和丢事件计数、当前锁存/seen_sources/峰值等级一直可读。PS需及时抽取并持久化；PL复位后清空，不承诺掉电保存。

## 6. 串口与后续PS接入

当前活动顶层已接通的是**PL调试UART管脚**，115200、8N1、无流控。它不是PS启动日志串口，也不代表ARM到PL的AXI映射已经存在。

- 请求14字节：`C3 51 01 op seq16 addr16 data32 crc16`；op=0读/1写。
- 回复16字节：`C3 52 01 err seq16 addr16 data32 echoed_op 00 crc16`。
- 多字节小端；CRC16-CCITT-FALSE，init=FFFF、poly=1021、不反射、xorout=0；CRC覆盖此前字节，低字节先发。
- 20ms字节间超时、错误停止位、坏CRC不执行请求；忙时丢请求并计数。调用端需等完整回复，再发下一帧。
- 与旧`55 A5/A6`调试帧按整帧仲裁，不能按字节拼接。旧解码器需识别或跳过控制回复。
- CRC用于发现传输错误，没有身份鉴别能力；网站不得直接透传寄存器写入。本地台架可用串口调试，生产权限应由PS服务管理。

CLI：[tools/control_cli.py](tools/control_cli.py)，`selftest`/`packet`不连接设备。实际串口操作需Python环境安装pyserial，且明确PL UART盘符/接口；本次未打开串口或烧板。

```powershell
python .\src\control\tools\control_cli.py selftest
python .\src\control\tools\control_cli.py packet 0x0000
python .\src\control\tools\control_cli.py --port COM实际PL串口 status
# 编辑标定配置后，板上KEY2长按进入许可；正在运行的合格系统还需合法确认OFF。
python .\src\control\tools\control_cli.py --port COM实际PL串口 configure .\我的标定配置.json
python .\src\control\tools\control_cli.py --port COM实际PL串口 target 6000 --hold-seconds 10
python .\src\control\tools\control_cli.py --port COM实际PL串口 events
```

target示例中的6000仅演示命令，不是此风扇已验收目标。连续测试期间分别刷新心跳/目标，退出后租约到期回退。控制阶段只允许一个客户端占有命令暂存寄存器；同帧重发不续租。短于100ms的租约应走后续AXI方案，不用当前串口CLI持续控制。

AXI适配器支持AW/W独立顺序、R/B背压和读写公平仲裁，仅接受WSTRB=F整字写。它不含CDC；接PS时须另加时钟转换、确认地址/复位/错误处理。不能直接将PS 50MHz握手线接到采集100MHz。当前`design_0`、设备树、地址映射均未为它修改。

## 7. 验证与后续验收

从工程根目录运行 `powershell -ExecutionPolicy Bypass -File .\src\control\run_regression.ps1`。汇总 [sim/results/validation.json](sim/results/validation.json) 包含源文件哈希；失败、超时、缺少ALL PASS均非零退出，重新运行会先使旧PASS失效。

覆盖：正常PI、原子配置/禁运行中关保护、独立租约、重放与幂等、PS掉线、两时钟过流抑制、过热持续增风、复合原因优先级、无效输入禁止复位、稳定本地恢复、FG反馈失效/起转截止/超速/堵转佐证、振动轨限质量、软事件过期、本地消音、事件拥塞/精确弹出、一致快照、AXI顺序/背压、控制/调试串口完整帧共存。独立Python大整数对拍80组RPM、492组PI；实际`subsys_acq`仿真使用真实115200时序，仅压缩POR等待，不模拟实板成功。

综合脚本 `tools/run_td_synthesis.py --scope core` 评估完整控制/UART/PWM核；`--scope acq` 评估真实采集顶层/传感器驱动/控制/调试UART；`--scope soc` 评估合并的NPU/视频/采集工程。输出均在独立目录，保留源文件哈希。资源估计/Setup结果以对应源快照为准，综合阶段的HWNS=0不证明布线Hold通过；没有板级I/O延迟的独立报告不能代替实板协议裕量与布线验收。

本轮最终回归11组全部通过，核心场景1411次断言、UART566次、AXI146次、按键/新样本过滤13次、未合格非台架10次；RPM/PI另有80/492组独立参考向量。实际采集顶层验证了FCB1回包与PWM输出；另验证了温度失效退出合格稳态，以及缓存成功不能遮蔽命令保留位格式错误。

最终独立控制核报告 [sim/td_control_final/synthesis.json](sim/td_control_final/synthesis.json)：100MHz gate Setup **+0.989ns**，6713 LUT、5010寄存器、估计5800 slices、4 DSP、0 ERAM，STA覆盖89.55%。包装器保留全部可配置功能，其中包含仿真注入寄存器；该slice估计既不是新增到整机的精确增量，也不是最终布线资源。实际事件FIFO使用分布式RAM。

最终真实采集顶层报告 [sim/td_acq_release/synthesis.json](sim/td_acq_release/synthesis.json)：100MHz gate Setup **+0.805ns**，9550 LUT、7405寄存器、估计8023 slices、4 DSP、0 ERAM，STA覆盖99.97%。这包含现有传感器驱动和调试逻辑，不是纯控制模块的成本。上述两项与最终RTL哈希一致。

合并SoC资源评估快照 [sim/td_soc_release/synthesis.json](sim/td_soc_release/synthesis.json)：估计52049/52480 slices（99.18%）、259 ERAM、147 DSP；gate全局Setup **−2.909ns**，主要最差路径在现有Video_NPU的resize逻辑，该快照的100MHz采集域为+0.799ns。这份评估在最后两处状态/命令格式修正**之前**完成，保留其原始源哈希；最终RTL的全芯片综合/P&R仍需重跑。不能将gate估计余量431 slices当成可靠布线余量，更没有预算直接塞入约7727 slices的独立特征核/窗口逻辑。

统一证据清单见 [sim/implementation_validation.json](sim/implementation_validation.json)。其他`td_core*`/`td_control_release`目录为优化过程中间快照，不作为最终源码证据。

必须继续完成：合并资源预算、整机P&R的Setup/Hold/约束覆盖；风扇PPR、PWM与蜂鸣驱动、真实电流/温度/PI标定；受限台架验证失效/恢复与温升；PS AXI寄存器接入、热负载执行/回执；完整39维窗口/质量/PS帧、模型结果门控、事件持久化与上报。网页不会因这些RTL源码存在就自动收到报警。


## P27 初始配置与受限试验合同（本地候选）

首次远程提交权限与物理 `local_permit` 分离。只有控制配置 word0 全零、ID 为零，且无 PS/手动/BNC 占用或残留、无同拍手动请求、无控制命令管线、实际输出/请求/爬坡目标均为零、无锁存故障、ADC 和温度输入有效时，才提供 `initial_config_permit`。SNAP7 和事件 ACK 不压低该权限。FCB 首次免 KEY 提交仍要求完整 24 字、所有既有合法性检查及资格 word0 精确为 `0x1f`；已配置后的 KEY 维护语义保留。`cfg_changed` 拍拒绝 RUN/STOP/HB，旧心跳不得跨 COMMIT 启动输出。

独立权限沿 `subsys_acq -> edge_features -> edge_mailbox` 传递。EDG 还要求当前 calibration_id 与 qualified 均为零；完整 17 字、engine/building 空闲、新 ID、增益/PPR/频带合法性检查保留。未标定中间 ID 可接续正式初次提交；已标定 EDG 的不同配置仍需物理 KEY。

状态 word0 新增：bit19 为 `REMOTE_INITIAL_CONFIG_SUPPORTED`，bit20 为实时 `initial_config_eligible`，bit21 为 `output_zero_confirmed`；bit15 始终为真实物理许可。bit21 本身包含 `applied_duty==0`，非零输出会在同拍撤销。word26 继续表示原 FG quiet_age，word27 继续表示 FG rejected_periods。

对已配置正式控制，STOP/FSM 和维护提交的确认依据为实际 PWM 连续归零满 stop_ms；FG 仍旋转不能单独阻止确认。未配置诊断仍使用原 FG quiet 判据与 STOPPING/READY_OFF 合同，避免改变已存正常 NPU 模型的输入上下文。输出归零从不表示风机停转或 12V 已断开。STOP 的 KEY、温度保护与 owner 门禁仍保留；停止 PS 续期也不等于硬件 STOP 或控制权释放。

BNC ABI2 保留 `ARM2` 和六个原有门限。瞬时 healthy 不满足时立即关闭实际 PWM；连续不健康保持至少十个完整毫秒间隔后才永久 trip（任意起始相位对应 10–11 ms）。FG 判断保持最近一次 `fg_new` 的周期到下一次边沿，不能因脉冲只有一拍绕过确认。确认期间可续有效有限租约及更新限幅请求，但 healthy 恢复前实际输出仍为零。idle/owner 撤销、500 ms lease 和总期限仍立即停；它们不等待健康确认。

BNC `0x0908[31:24]` 为锁存原因：bit7 idle/owner、bit6 ADC 无效、bit5 温度无效、bit4 电流偏移越界、bit3 温度越界、bit2 FG 超速、bit1 lease 过期、bit0 总期限。健康确认期间出现的原因会累积；立即停时也记录当时并存的异常，所以掩码不是单一因果排序。`[23:3]` 仍为零，低三位仍为 valid_limits/tripped/armed。STOP、读回和失败 ARM 均不清除原因；只有复位或成功的明确新 ARM 清除。短暂异常恢复不会自动重新 ARM 已 trip 的试验。
