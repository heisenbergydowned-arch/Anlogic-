# 原始波形事件捕获：edge_waveform

独立文件 `rtl/edge_waveform.v`，自测 `sim/tb_edge_waveform.v`，脚本 `tools/run_waveform_tests.py`。未修改现有顶层、mailbox、CSR或工程注册文件。父顶层完成接线、地址译码和工程注册。本模块只捕获事件波形，不做FFT、不做连续DMA、不阻塞采集/保护。

## 容量与时序

默认 `CLK_HZ=100000000`、`SAMPLE_HZ=4000`、`PRE_SAMPLES=128`、`POST_SAMPLES=128`、`POST_TIMEOUT_CYCLES=CLK_HZ/2`、`CSR_BASE=16'h2000`、`TEST_MODE=0`。PRE/POST是综合参数，均可为0，但总和须为1–1024；支持非2幂深度。CSR_BASE须4KiB对齐且不超过0xf000。

每测点独立保存PRE个触发前有效样本和POST个触发后有效样本。默认名义时间为32ms前+32ms后，**64ms事件窗口，不是完整1024点振动特征帧**。首末样本实际跨度比点数/Fs少一个采样间隔，缺样时还会增长，必须使用保存的时间戳。512+512配置是每测点1024点，名义256ms。

每片同步RAM每点144位：XYZ原码48位、`now_cycles` 64位、接收序号16位、质量16位。两片默认RAM有效位数为73728bit（9KiB）；512+512时为294912bit（36KiB）。这是逻辑容量，**不是实测ERAM数量或综合资源结果**。RAM及RAM输出没有复位，也不清零数组；只有指针、计数和控制状态复位。预触发环持续覆盖；触发后冻结基址，各片独立追加POST个有效样本，先完成的一片立即停止写入。扫描保留样本产生摘要后置READY；扫描约为`2*max(count_a,count_b)+1`个clk周期。

## 同域接口（所有输入由clk上升沿采样）

| 端口 | 宽度/方向 | 合同 |
|---|---|---|
| clk / rst_n | 输入1/1 | 采集域时钟/低有效异步控制复位；RAM不复位 |
| now_cycles / now_ms | 输入64/32 | 与edge_window同一单调时间；前者每点保存，后者只保存触发时刻 |
| enable / stop | 输入1/1 | enable为电平预采集许可；stop为外部停止电平，优先于触发和样本写入 |
| a_new / b_new | 输入1/1 | 各片真实新有效样本脉冲，禁止从4kHz节拍或旧保持值伪造 |
| ax,ay,az,bx,by,bz | 输入6×signed16 | 原始加速度XYZ；只在本片new且!bad时写入 |
| a_seq / b_seq | 输入16/16 | 各片自己的接收序号，不能共享；自然16位回绕 |
| a_bad / b_bad | 输入1/1 | 本片质量错误电平；new&&bad拒收，绝不复制上一点或补零 |
| trigger | 输入1 | 自动事件触发脉冲；父顶层根据control_active/latched的故障沿产生 |
| trigger_reason | 输入32 | 本次自动触发原因快照，冻结保存 |
| trigger_frame_id | 输入32 | 父顶层最新已完成feature_frame_id，关联信息，不保证该完整特征窗在本短波形中 |
| trigger_frame_start/end | 输入64/64 | 对应最新已完成特征窗的window_start/end，原值保存 |
| release_req / release_id | 输入1/32 | 可选外部释放脉冲与精确事件ID；只释放READY事件，不用于保护RESET |
| release_ack | 输出1 | 成功释放当拍后的一周期脉冲；CSR成功释放也产生此脉冲 |
| armed / capturing / event_available | 输出1/1/1 | 预采集 / 后采集或摘要扫描 / READY冻结所有权 |
| event_id / dropped_triggers | 输出32/32 | 接受事件递增ID / 未接受触发次数；均自然32位回绕，rst_n清零 |
| req / write_en / address / wdata | 输入1/1/16/32 | 现有CSR目标域请求；**绝对16位字节地址**，不传低12位；req单周期，一次只允许一个未完成事务 |
| response / rdata / error | 输出1/32/8 | response单周期；普通寄存器在接受请求的时钟沿后返回；DATA在下一个时钟沿后返回（同步RAM两阶段） |

不包含CDC。应接在现有`edge_csr_cdc.d_*`之后的100MHz CSR域。75MHz AXI侧继续使用原握手路径，不能把AXI地址或release_req直接跨域送入模块。父译码只把`0x2000 <= csr_address < 0x3000`送到本模块，EDG1请求必须缩到`0x1000–0x1fff`，避免两个模块同时response。

`enable=1`且`stop=0`时复位后下一拍自动进入ARMED。CSR STOP有独立软件锁存，须CSR ARM解除；ARM不绕过外部enable/stop。硬件stop/enable下降在预采集时清空有效历史；恢复后重新积累。捕获期间停止或超时提交部分事件并标记短POST，已READY事件停止后仍保留。外部reset丢弃整个事件和ID，不清RAM；PS必须重新检查READY，不能把PL复位前的ID当新事件身份。

接受触发那一拍的真实样本归POST，不归PRE；POST=0时该拍样本不写入。触发时间独立记录，无需伪造“触发样本”。在ARMED以外的触发丢弃并计数，不重启捕获，不覆盖已有事件。trigger须边沿脉冲，持续拉高会按周期累计丢弃。PS精确ID释放后重新ARMED并清空历史，因此紧接着再触发可能短PRE。无第二事件队列。

## 0x2000–0x2fff CSR

以下为默认绝对地址。除INDEX及四个命令外全部只读。状态和诊断计数可随时读取，**事件头及DATA只有READY时才视为完整有效**；头在捕获/扫描期间会变化，释放后部分旧头值保留，但计数清零。READY期间事件头/样本冻结，实时状态、INDEX和dropped_triggers除外。

| 地址 | 内容 |
|---|---|
| 2000 / 2004 | WAV1=`0x57415631` / ABI=`0x00010000` |
| 2008 | bit0 ARMED、bit1 CAPTURE/SCAN、bit2 READY、bit3 HALTED、bit4软件STOP、**bit5 TEST_MODE** |
| 200c / 2010 | event_id / dropped_triggers |
| 2014 / 2018 / 201c | SAMPLE_HZ / PRE_SAMPLES / POST_SAMPLES |
| 2020 / 2024 / 2028 / 202c | 事件quality / reason / 最新完成特征frame_id / trigger_ms |
| 2030 / 2034 | trigger_cycles低/高32位 |
| 2038 / 203c / 2040 / 2044 | feature window_start低/高、window_end低/高 |
| 2048 / 204c | A / B保留样本总数 |
| 2050 / 2054 / 2058 / 205c | A_PRE / B_PRE / A_POST / B_POST实际点数 |
| 2060 / 2064 / 2068 / 206c | A首样本cycles低/高、末样本cycles低/高 |
| 2070 / 2074 / 2078 / 207c | B首样本cycles低/高、末样本cycles低/高 |
| 2080 / 2084 | A / B的`{末seq16,首seq16}`；零点时为0 |
| 2088 / 208c | A / B触发到该片完成/停止/超时之间拒收的`new&&bad`次数 |
| 2090 / 2094 | A / B保留点中seq或时间间隔异常的点数（同点两种异常只计一次） |
| 2098 / 209c / 20a0 | CLK_HZ / POST_TIMEOUT_CYCLES低/高 |
| 20a4 | trigger_source：bit0外部自动trigger、bit1 CSR手动；同时发生为3 |
| **20a8** | **TEST_MODE只读标识：0实测输入合同、1 TEST源；不得用于正式诊断证据** |
| 20b0 | ARM：只写1；解除软件STOP，需enable&&!stop且当前HALTED/ARMED；不清READY |
| 20b4 | STOP：只写1；锁存软件停止，捕获中提交部分事件，READY保持 |
| 20b8 | RELEASE：写event_id，只释放匹配的READY事件；重复或错ID返回error=4 |
| 20bc | MANUAL_TRIGGER：只写1且必须ARMED；reason=`0x80000000`，source=2；与自动触发同拍时保留自动reason，source=3 |
| 20c0 | INDEX读写：bit31选片（0 A/1 B），bit12:3点索引0–1023，bit2:0字索引0–4；其余位必须0 |
| 20c4 | DATA只读：读取INDEX所选的一个32位字，不自增、不隐含POP |

父顶层必须把TEST源选择与`TEST_MODE`绑定到同一综合配置；仅靠模块无法辨认上游是否送入模拟码值。TEST标识是静态ABI信息，即使停止/复位也可读。手动事件是否实测由TEST_MODE决定，不能用manual source代替TEST标识。

DATA每点五字：word0=`{ay,ax}`，word1=`{seq,az}`，word2=cycles[31:0]，word3=cycles[63:32]，word4=`{16'd0,sample_quality}`；B同理。XYZ须在PS分别解析为signed16。A/B各自按接收顺序导出，**点索引相等不表示物理同步**，按两组真实cycles分析时差；禁止排序、拼接或补样冒充同步六轴帧。

错误：1非法/未定义/未对齐地址、只读字段写入、READY中非法DATA点/字；2非法命令值/INDEX保留位；4无匹配READY所有权的RELEASE；5未READY的DATA、当前状态不允许的ARM/手动触发。非法数据返回0。被接收的DATA事务先锁存选片/字，随后返回该同步RAM读取结果；下一事务须等response。外部释放与新DATA请求同拍时DATA返回5；先接受的DATA与后一拍外部释放重合时仍返回原已锁定点，PS不应并发释放/读取。

PS流程：等READY→读TEST_MODE、event_id和完整头→逐片按count读取（每字写INDEX、读DATA）→本地持久化/消费完成→RELEASE写同一个event_id。读取INDEX后再读DATA须保证同一CSR写者独占；AXI/UART仍遵守现有唯一写者合同。

## 质量合同

每点quality：bit0本片接收seq不连续（16位回绕正常）；bit1本片相邻有效点时间间隔小于PERIOD/4或大于7*PERIOD/4；bit2任一轴达到0x7fff/0x8000轨限（真实码值仍保存）；bit3自上一保留有效点以来观察到本片bad。只在new&&!bad时保存样本。无new时输入码值变化不会形成样本。

事件quality：bit0–3 OR全部保留A点quality，bit4–7 OR全部保留B点quality；bit8/9短A/B PRE；bit10/11短A/B POST；bit12停止（stop、enable下降、CSR STOP）；bit13后采集超时；bit14/15触发时或各片后采集期间观察到A/B bad，包括触发前尚未由下一有效样本携带的pending bad。质量摘要扫描仅覆盖保留点，不把整个预采集历史中的已覆盖错误永久粘到新事件上。

gap计数包含保留首点带入的前序间隔标记，表示异常观察次数，**不是精确丢失物理样本数**。接收seq不是ICM内部样本计数；seq连续不能证明器件零丢样。实际缺样证据由各片时间间隔、有效点数、bad及超时共同表达。缺样时既不补零也不复制，count与PRE/POST实际点数必须和数据一起导出。

## 独立验证/综合

运行：`python3 src/edge/tools/run_waveform_tests.py`。默认寻找`fpga_work/toolchain/bin/iverilog`及同目录vvp；Mac自动给子进程设置对应toolchain/lib的DYLD_LIBRARY_PATH，不改工具链文件。支持`--iverilog /绝对路径 --vvp /绝对路径 --output /独立输出目录`；缺工具返回TEST_REQUIRED/退出码2，不装包、不启动虚拟机。

输出在`sim/waveform_results/validation.json`及逐组compile/run日志。独立展开顶层直接选 **`edge_waveform`**，源文件仅`rtl/edge_waveform.v`；Icarus用`-g2012 -Wall -s edge_waveform`。TD独立综合同样选该top（所有端口保留、clk=100MHz/10ns），不使用edge_eval_top/FFT/NPU包装，参数默认128+128；再另评估512+512。同步RAM能否落ERAM、实际ERAM/LUT/FF及100MHz Setup需以TD报告确认。仿真/展开通过不代表已综合、布线或实板验收。

父顶层集成建议：连接真实vld_icm_a/b、sns_seq_a/b、sns_err_a/b及原始XYZ；故障上升沿构造trigger_reason；最新已完成feature_frame_id/window_start/end仅作关联快照；采集时钟now_cycles与edge_window共享。新的故障位/升级沿是否再次触发由父顶层决定，模块满时只计dropped_triggers。模块不会修改控制、锁存、报警FIFO或mailbox所有权。

## 2026-10-09本地实测结果

Icarus 11.0本地工具，最终源码展开及10组仿真全部PASS，编译日志无warning。报告记录RTL、bench和既有CSR CDC的SHA256；未运行TD综合、布线或实板。

| PRE / POST / TEST | 通过的CSR事务检查 |
|---|---:|
| 3 / 2 / 0（非2幂深度） | 584 |
| 128 / 128 / 0（默认） | 16904 |
| 512 / 512 / 0 | 66824 |
| 0 / 1 / 0 | 169 |
| 1 / 0 / 0 | 166 |
| 1 / 1 / 0 | 229 |
| 0 / 1024 / 0 | 61549 |
| 1024 / 0 / 0 | 61546 |
| 128 / 128 / 1（TEST标识） | 16904 |
| 既有edge_csr_cdc，75MHz↔100MHz | 34 |

共224909次CSR事务检查，另有样本原码/时间/序号/质量逐字对拍、所有权及状态断言。覆盖环多次回绕、16位序号和64位时间回绕、错时A/B、触发同拍真实样本、A/B分别坏样本/seq跳变/时间异常/轨限、早触发、单片停采、超时、外部stop/enable与CSR STOP、冻结背压/retrigger丢弃、错ID/重复/捕获中释放、INDEX保留位及非法DATA、RESET和TEST状态位。CDC组通过现有四阶段握手读取同步RAM、INDEX/DATA、手动触发、STOP及RELEASE；未引入新CDC逻辑。

## 合并工程接线（本轮已实现）

PS GP0基址`0x80400000`，WAV1物理地址`0x80402000–0x80402fff`，沿用AXI适配、75↔100MHz CDC及UART/PS唯一写者仲裁。完整feature顶层连接真实/TEST同一选择的六轴样本、采集时钟计数、最新已完成特征窗口。自动触发原因掩码`0x0002cfff`涵盖现有物理规则、关键数据失效、辅助/振动传感器诊断及跟踪故障的新上升位；不把模型单次置信度或PS离线自动当作物理故障。模型确认事件由PS手动请求，仍标记manual。READY占用期间新触发可丢弃并计数，不阻塞硬保护；PS必须及时落盘并按ID释放。

最新frame_id只是关联快照，不保证其窗口包含触发点。若启动早期尚无完成帧则ID=0；必须结合真实起止cycles判断关系。默认64ms六轴原始记录不等于1024点FFT帧；过程量保留在既有FCB1事件/FRM1同期摘要，不在WAV1重复逐点采样。连续原始DMA和长时波形流不属于本模块。
