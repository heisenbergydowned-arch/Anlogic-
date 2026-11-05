//============================================================================
// sns_sync.v — 双 ICM-20602 振动同步采集核心（v0.7：加速度计 4kSps；
//             v0.8：有效样本超时监控）
//
// 器件（共 SPI 总线，2 条独立片选，SPI Mode0）：
//   ICM-20602 ×2（振动，各测一路风机/机架振动）
//
// 调度：上电 POWERUP_MS 后依次软复位、等待、WHO_AM_I 校验并初始化两片 ICM；
//       之后每个采样节拍（1/SAMPLE_HZ）内背靠背完成：
//       ICM_A 突发读 15 字节（0x3A 起：INT_STATUS + 14 数据字节）
//       → ICM_B 突发读 15 字节。
//       A/B 读出间隔随 SPI_DIV 改变（两片各自内部时钟自由采样，
//       采样时刻差需台架实测，本模块不虚构同步指标）。
//
// 新样本门控：INT_ENABLE.RAW_DATA_0_RDY_EN=1，每拍先读 INT_STATUS(0x3A)，
//       DRDY=bit0 为 1 才更新输出并置 vld（重复样本/丢拍不出 vld）。
//
// DRDY 清零语义（ICM-20602 手册，已核实）：INT_PIN_CFG(0x37) bit4
//       INT_RD_CLEAR 默认 0 —— 中断状态仅在读 INT_STATUS(0x3A) 时清零，
//       读数据寄存器(0x3B..0x48)不影响 DRDY（初始化表显式写 0x37=0x00
//       锁定此语义）。据此，节拍 8kHz > ODR 4kHz：相邻两次 INT_STATUS
//       读间隔 125µs < 样本周期 250µs → 每个样本的 DRDY 必然被下一次
//       节拍的 INT_STATUS 读捕获，vld 恰好发射一次。
//       口径分级：上述"零丢样、零重复"是**逻辑层**结论——前提
//       （DRDY 置位/清零与手册一致、突发读无撕裂）由仿真模型以同语义
//       断言 dup==0 / jump==0 保证；**真实器件是否满足须台架实测**，
//       在线审计手段：① seq 序号差分（丢样/跳号可见）；
//       ② dup_a/b_cnt——相邻两次 vld 的 14 数据字节逐位相同即计数，
//       真实传感器噪声下相邻样本 112bit 全同概率≈0，dup>0 即 DRDY 门控
//       失效或器件冻结输出（是后续改 FIFO 读的前置判据）。
//       （早期版本曾按"读任一数据寄存器清 DRDY"推算 3.8% 死窗丢样率，
//       该口径已废弃，仿真模型已同步修正。）
//       节拍-ODR 相位漂移的正常现象（非缺陷，逻辑分析仪抓总线勿误判）：
//       样本恰好落在"INT_STATUS 读毕 → 首个数据字节读毕"窗口内时，
//       其字节在本拍突发读中露出（DRDY=0，不发射 vld）、下一拍才正式
//       消费——总线波形上同一样本字节连续两拍出现（"重复一拍"）；ODR
//       与节拍存在频差时消费拍型周期性滑移，出现连续两拍 DRDY=0 的
//       "跳过一拍"。两者均不影响"每个样本恰好一次 vld"，dup 计数
//       只比对已消费样本，不受影响。
//       残余风险（如实记录）：手册未保证 0x3B..0x48 突发读原子性，
//       跨样本字节一致性仍需实测，不用模型中的冻结行为冒充实物证据。
//       A/B 两片 ODR 各自独立（内部时钟晶振偏差），seq_a/seq_b 相互
//       漂移——下游 ratio_ab / 联合 FFT 必须按时间窗（帧内 tick）配对，
//       禁止按序号 1:1 配对。
//
// 容错（三层）：
//   1) 上电 WHO_AM_I 失败 → err 置位，跳过该片，不阻塞对侧；
//   2) 运行期看门狗：突发读 15 字节全 0x00/全 0xFF 连续 3 帧 → err 置位；
//      在线片持续 SAMPLE_TIMEOUT_MS（默认 300ms）无有效新样本也置 err
//      （v0.8）——SPI 应答正常但 DRDY 恒 0（内部采样停摆/时钟异常）时
//      数据字节为陈旧值、旧看门狗失明，此路补漏；wd_a/b_cnt 语义为
//      "数据看门狗触发次数"（坏帧+超时两类共用计数）；
//   3) 周期重试（RETRY_MS）：对 err 侧重发 复位→等待→WHO→重初始化，
//      恢复后自动清 err（自愈）。两片交替重试，互不饿死。
//      注意：retry_tmr 仅在 ST_RUN_TICK（节拍等待态）计时，节拍内的
//      突发读期间不累加 → 实效周期 ≈ RETRY_MS × 节拍周期/(节拍周期−读窗)
//      不是精确 1 s，实际间隔随 SPI_DIV 和在线片数量改变。
//   init_done 语义 = 初始化流程已走完 且 至少一片在线。
//
// 寄存器初始化表集中在本文件 init_rom()，改量程/DLPF 只改 localparam。
// （电流/压差等模拟量采集由 ads7606_if 独立完成，不占本总线。）
//============================================================================
module sns_sync #(
    parameter CLK_FREQ     = 100_000_000,  // 输入时钟
    parameter SAMPLE_HZ    = 8000,         // 采样节拍（> ODR 4kHz：零丢样论证见头注释）
    parameter SPI_DIV      = 4,            // SCLK = CLK_FREQ / (4*SPI_DIV) = 6.25MHz（ICM-20602 SPI 上限 10MHz）
    parameter REGISTER_SPI_DIV = SPI_DIV,
    parameter STATUS_SPI_DIV = SPI_DIV,
    parameter POWERUP_MS   = 100,          // 上电等待（传感器供电稳定）
    parameter RESET_MS     = 50,           // ICM 复位后等待
    parameter POSTINIT_MS  = 50,           // 初始化后等待
    parameter RETRY_MS     = 1000,         // 掉线片重试周期（ST_RUN_TICK 驻留时间口径；实效 ≈1.5s，见头注释）
    parameter SAMPLE_TIMEOUT_MS = 300,
    parameter [7:0]  WHO_ID     = 8'h12,   // ICM-20602 WHO_AM_I
    parameter ACCEPT_WHO_2E = 0,
    parameter [7:0]  ACCEL_FS_REG = 8'h10, // ACCEL_CONFIG: ±8g  (bits[4:3], 2<<3)
    parameter [7:0]  GYRO_FS_REG  = 8'h10  // GYRO_CONFIG:  ±1000dps
)(
    input  wire        clk,
    input  wire        rst_n,

    // SPI 共总线（Mode0，仅 ICM）
    output wire        spi_sclk,
    output wire        spi_mosi,
    input  wire        spi_miso,
    output wire        cs_icm_a_n,
    output wire        cs_icm_b_n,

    // ICM-A 采样输出（ax/ay/az 加速度，t 温度，gx/gy/gz 角速度，原始码）
    output reg  signed [15:0] icm_a_ax, icm_a_ay, icm_a_az,
                              icm_a_t,  icm_a_gx, icm_a_gy, icm_a_gz,
    output reg                vld_icm_a,
    // ICM-B
    output reg  signed [15:0] icm_b_ax, icm_b_ay, icm_b_az,
                              icm_b_t,  icm_b_gx, icm_b_gy, icm_b_gz,
    output reg                vld_icm_b,

    output wire        init_done,     // 初始化完成 且 至少一片在线
    output reg         err_icm_a,     // WHO 校验失败 / 运行期看门狗触发（周期重试）
    output reg         err_icm_b,

    // 诊断/序号输出（dbg_uart 转发：防综合裁剪 + 下游丢样审计）
    output wire [15:0] seq_a,          // A 有效样本序号（每次 vld +1，16 位回绕 ~65s）
    output wire [15:0] seq_b,          // B 有效样本序号
    output wire [15:0] tick_cnt,       // 采样节拍累计（8kHz 回绕 ~8.2s）
    output wire [15:0] vld_a_cnt,      // A 有效样本累计
    output wire [15:0] vld_b_cnt,      // B 有效样本累计
    output wire [15:0] drdy0_a_cnt,    // A 在线但本拍 DRDY=0 次数（正常 ≈ 节拍数-有效数）
    output wire [15:0] drdy0_b_cnt,    // B 同上
    output wire [7:0]  wd_a_cnt,      // A 掉线看门狗触发次数
    output wire [7:0]  wd_b_cnt,      // B 同上
    output wire [15:0] dup_a_cnt,     // A 相邻两次 vld 的 14 字节全同计数（重复消费/器件冻结审计，正常≈0）
    output wire [15:0] dup_b_cnt,
    output reg [7:0] who_a, who_b,
    output reg [9:0] config_bad_a, config_bad_b,
    output reg [23:0] config_failure_a, config_failure_b,
    output reg [7:0] status_a, status_b,
    output reg [15:0] retries_a, retries_b,
    output wire [31:0] diagnostic_state
);

    //------------------------------------------------------------------------
    // 初始化寄存器表（ICM-20602，两片共用）
    // 地址/位域依据：ICM-20602 寄存器手册 + PX4 MPU6000 兼容驱动定义
    //   4kSps 配方（v0.7，寄存器手册 Register 29 表）：
    //     ACCEL_CONFIG2.ACCEL_FCHOICE_B=1(bit3) → DLPF 旁路，3dB BW 1046Hz，
    //       加速度计 4kHz Low-Noise 档；ODR 再被 1/(1+SMPLRT_DIV) 分频，
    //       SMPLRT_DIV=0 → 4kSps 满速（1×/2×/叶频 700Hz 全部带内）。
    //     PWR_MGMT_2=0x07 陀螺 standby（Accelerometer-Only 模式）——
    //       陀螺 ODR(≈1.125kHz)≠加速度计 ODR(4kHz) 时 DRDY 语义不确定，
    //       陀螺 standby 后 DRDY 确定跟随加速度计；陀螺数据不参与特征，
    //       14 字节突发读中陀螺字节在真实器件上为陈旧值（模型仍输出
    //       审计样式，仅作数据通路校验用）。
    //   保留：CONFIG.DLPF_CFG=1（陀螺 DLPF——standby 后无实效，保持
    //         与 v0.6.1 一致减少变量）；ACCEL_CONFIG 量程 ±8g 不变。
    //------------------------------------------------------------------------
    function [15:0] init_rom;  // {addr, value}
        input [3:0] i;
        begin
            case (i)
                4'd0:    init_rom = {8'h70, 8'h40};       // I2C_IF: bit6 disables I2C (ICM-20602 DS-000176 section 9.39)
                4'd1:    init_rom = {8'h6B, 8'h01};       // PWR_MGMT_1:     自动时钟，唤醒
                4'd2:    init_rom = {8'h6C, 8'h07};       // PWR_MGMT_2:     陀螺 standby（DRDY 跟随加速度计）
                4'd3:    init_rom = {8'h19, 8'h00};       // SMPLRT_DIV:     0（4kHz/(1+0)=满速）
                4'd4:    init_rom = {8'h1A, 8'h01};       // CONFIG:         陀螺 DLPF 176Hz（standby 后无实效）
                4'd5:    init_rom = {8'h1C, ACCEL_FS_REG};// ACCEL_CONFIG:   量程
                4'd6:    init_rom = {8'h1D, 8'h08};       // ACCEL_CONFIG2:  FCHOICE_B=1: 4kHz 档/BW 1046Hz
                4'd7:    init_rom = {8'h1B, GYRO_FS_REG}; // GYRO_CONFIG:    量程
                4'd8:    init_rom = {8'h38, 8'h01};       // INT_ENABLE:     RAW_DATA_0_RDY_EN
                4'd9:    init_rom = {8'h37, 8'h00};       // INT_PIN_CFG:    INT_RD_CLEAR=0（显式锁定默认：
                                                           //   仅读 INT_STATUS 清 DRDY，读数据寄存器不清）
                default: init_rom = {8'h6B, 8'h01};
            endcase
        end
    endfunction
    localparam INIT_LEN = 10;

    //------------------------------------------------------------------------
    // SPI 位引擎：每 bit 4 相位（低-沿-高-沿），SCLK 占空比 50%
    //   Mode0（ICM）: MOSI 在相位0末尾置位（上升沿前 1 个相位建立），
    //                  相位1拉高 SCLK，相位2采样 MISO（2FF 同步后）
    // 帧尾：保持CS帧立即 eng_done；否则再等 CS_TAIL 拍抬 CS 并 eng_done——
    //   保证最后下降沿之后 CS 仍维持一段时间（器件在最后下降沿锁存 DIN，
    //   且两事务间 CS 高电平有足够间隙）。
    //------------------------------------------------------------------------
    localparam DEV_A = 1'b0, DEV_B = 1'b1;

    reg        eng_busy;
    reg [3:0]  phase;
    reg [15:0] div_cnt;
    reg [3:0]  bit_cnt;
    reg [4:0]  nbits_l;      // 本帧位数（8 或 16）
    reg        xfer_dev;
    reg        hold_cs;      // 突发读期间保持 CS
    reg [15:0] tx_shift, rx_shift;
    reg        sclk_r, mosi_r;
    reg        cs_a_r, cs_b_r;
    reg        eng_done;
    reg [15:0] cs_tail;      // CS 延迟释放倒计时
    reg [15:0] active_div;
    wire [15:0] CS_TAIL = active_div * 16'd2;

    wire ph_fire = (div_cnt == active_div - 16'd1);

    // MISO 2FF 同步（外部异步输入进引擎前打两拍）
    reg [1:0] miso_sync;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) miso_sync <= 2'b00;
        else        miso_sync <= {miso_sync[0], spi_miso};
    end
    wire miso_s = miso_sync[1];

    // 引擎操作接口（由序列器驱动）
    reg        sop;          // 1 clk 启动脉冲
    reg        op_dev;
    reg [4:0]  op_nbits;
    reg [15:0] op_tx;
    reg        op_hold;
    reg        op_register;
    reg        op_status;
    reg        cs_release;   // 1 clk：强制释放全部 CS

    assign spi_sclk = sclk_r;
    assign spi_mosi = mosi_r;
    assign cs_icm_a_n = cs_a_r;
    assign cs_icm_b_n = cs_b_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            eng_busy <= 1'b0; phase <= 0; div_cnt <= 0; bit_cnt <= 0;
            sclk_r <= 1'b0; mosi_r <= 1'b0;
            cs_a_r <= 1'b1; cs_b_r <= 1'b1;
            eng_done <= 1'b0; rx_shift <= 16'h0; tx_shift <= 16'h0;
            nbits_l <= 5'd8; xfer_dev <= DEV_A; hold_cs <= 1'b0;
            cs_tail <= 16'd0;
            active_div <= SPI_DIV;
        end else begin
            eng_done <= 1'b0;
            if (cs_release) begin
                cs_a_r <= 1'b1; cs_b_r <= 1'b1;
                cs_tail <= 16'd0;
            end else if (sop) begin
                eng_busy <= 1'b1;
                phase <= 3'd0; div_cnt <= 16'd0; bit_cnt <= 4'd0;
                tx_shift <= (op_nbits == 5'd16) ? op_tx : {op_tx[7:0], 8'h00};
                rx_shift <= 16'h0;
                nbits_l  <= op_nbits;
                xfer_dev <= op_dev;
                hold_cs  <= op_hold;
                active_div <= op_status ? STATUS_SPI_DIV : op_register ? REGISTER_SPI_DIV : SPI_DIV;
                sclk_r   <= 1'b0;
                mosi_r   <= 1'b0;
                if (op_dev == DEV_A) cs_a_r <= 1'b0;
                else                 cs_b_r <= 1'b0;
            end else if (eng_busy) begin
                if (ph_fire) begin
                    div_cnt <= 16'd0;
                    case (phase)
                        3'd0: begin
                            mosi_r <= tx_shift[15];   // 上升沿前置数
                        end
                        3'd1: begin
                            sclk_r <= 1'b1;                        // 上升沿
                        end
                        3'd2: begin
                            rx_shift <= {rx_shift[14:0], miso_s};
                        end
                        3'd3: begin
                            sclk_r <= 1'b0;                        // 下降沿
                            tx_shift <= {tx_shift[14:0], 1'b0};
                            bit_cnt  <= bit_cnt + 4'd1;
                            if (bit_cnt == nbits_l - 4'd1) begin
                                eng_busy <= 1'b0;
                                if (hold_cs) begin
                                    eng_done <= 1'b1;              // 事务内：立即完成
                                end else begin
                                    cs_tail <= CS_TAIL;            // 延迟释放 CS
                                end
                            end
                        end
                        default: begin end
                    endcase
                    phase <= (phase == 3'd3) ? 3'd0 : phase + 3'd1;
                end else begin
                    div_cnt <= div_cnt + 16'd1;
                end
            end else if (cs_tail != 16'd0) begin
                // 帧已完成，CS 仍保持低：倒计时结束后抬 CS 才发 eng_done，
                // 确保下一事务开始前 CS 高电平间隙足够
                if (cs_tail == 16'd1) begin
                    cs_a_r <= 1'b1; cs_b_r <= 1'b1;
                    eng_done <= 1'b1;
                    cs_tail  <= 16'd0;
                end else begin
                    cs_tail <= cs_tail - 16'd1;
                end
            end else begin
                sclk_r <= 1'b0;
            end
        end
    end

    wire [15:0] eng_rx = rx_shift;

    //------------------------------------------------------------------------
    // 采样节拍发生器（自由运行）
    //------------------------------------------------------------------------
    localparam [16:0] TICK_MAX = CLK_FREQ / SAMPLE_HZ; // 50_000 @ 2kHz
    reg [16:0] tick_ph;
    wire       sample_tick = (tick_ph == TICK_MAX - 17'd1);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) tick_ph <= 17'd0;
        else        tick_ph <= (sample_tick) ? 17'd0 : tick_ph + 17'd1;
    end

    //------------------------------------------------------------------------
    // 毫秒等待器（wait_cnt 每时钟周期递减，装载数 = 毫秒数 × MS_TICKS）
    //------------------------------------------------------------------------
    localparam [23:0] MS_TICKS = CLK_FREQ / 1000;
    reg [26:0] wait_cnt;

    //------------------------------------------------------------------------
    // 毫秒节拍（有效样本超时监控用）
    //------------------------------------------------------------------------
    reg [16:0] ms_psc;
    reg        ms_tick;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ms_psc  <= 17'd0;
            ms_tick <= 1'b0;
        end else begin
            ms_tick <= 1'b0;
            if (ms_psc >= MS_TICKS[16:0] - 17'd1) begin
                ms_psc  <= 17'd0;
                ms_tick <= 1'b1;
            end else begin
                ms_psc  <= ms_psc + 17'd1;
            end
        end
    end

    //------------------------------------------------------------------------
    // 序列器
    //------------------------------------------------------------------------
    localparam [4:0]
        ST_PWRUP      = 5'd0,
        ST_WAIT       = 5'd1,   // 通用毫秒等待（wait_ret 决定去向）
        ST_WHO_ISS1   = 5'd2,   // WHO: 发地址字节
        ST_WHO_WAIT1  = 5'd3,
        ST_WHO_ISS2   = 5'd4,   // WHO: 发 dummy 读回
        ST_WHO_WAIT2  = 5'd5,
        ST_WHO_CHK    = 5'd6,
        ST_RST_ISS1   = 5'd7,   // 复位: 地址 0x6B
        ST_RST_ISS2   = 5'd8,   // 复位: 数据 0x80
        ST_RST_WAIT2  = 5'd9,
        ST_INIT_ISS1  = 5'd10,  // 初始化: 地址
        ST_INIT_ISS2  = 5'd11,  // 初始化: 数据
        ST_INIT_WAIT2 = 5'd12,
        ST_RUN_TICK   = 5'd13,  // 等采样节拍 / 掉线重试
        ST_B_ISS      = 5'd14,  // 突发读：发帧（帧0=地址，1..15=数据）
        ST_B_WAIT     = 5'd15,
        ST_B_ASSEM    = 5'd16,
        ST_VERIFY_ADDR=5'd17, ST_VERIFY_DATA=5'd18,
        ST_VERIFY_WAIT=5'd19, ST_VERIFY_CHECK=5'd20, ST_VERIFY_DONE=5'd21,
        ST_RECOVER_DONE=5'd22;

    reg verify_bad; reg [7:0] verify_value;
    reg [4:0]  st;
    reg        cur_b;          // 0=操作 ICM-A，1=ICM-B
    reg [3:0]  init_idx;
    reg [4:0]  burst_idx;      // 0..15（帧0 地址 + 帧1..15 数据）
    reg [7:0]  int_status;     // 0x3A INT_STATUS（DRDY=bit0）
    reg [7:0]  rx_buf_0,  rx_buf_1,  rx_buf_2,  rx_buf_3,
               rx_buf_4,  rx_buf_5,  rx_buf_6,  rx_buf_7,
               rx_buf_8,  rx_buf_9,  rx_buf_10, rx_buf_11,
               rx_buf_12, rx_buf_13;   // 0x3B..0x48 数据字节
    reg [7:0]  who_val;
    wire [15:0] init_word = init_rom(init_idx);   // 当前初始化表项 {addr, value}
    reg [2:0]  wait_ret;       // 等待返回目标
    reg        retry_run;      // 1 = 运行期重试（完成后回 RUN 而非全流程）
    reg        retry_sel;      // 双侧均掉线时交替选择重试对象
    reg        retry_pending, retry_device;
    reg [4:0]  retry_resume;
    reg [26:0] retry_wait;
    reg [31:0] retry_tmr;      // 掉线重试计时
    reg [1:0]  bad_a, bad_b;   // 掉线看门狗连续坏帧计数
    reg        init_flow_done; // 初始化流程（含失败容错）已走完

    // 诊断计数器/样本序号（只增计数，16 位回绕由上位机差分处理）
    reg [15:0] seq_a_r, seq_b_r;
    reg [15:0] tick_cnt_r, vld_a_r, vld_b_r, drdy0_a_r, drdy0_b_r;
    reg [7:0]  wd_a_r, wd_b_r;
    reg [15:0]   dup_a_r, dup_b_r;           // 相邻两次 vld 14 数据字节全同计数
    reg [111:0]  last_a_data, last_b_data;   // 上一次已消费样本的 14 数据字节
    reg          last_a_vld, last_b_vld;     // 影子有效门控（首样本/掉线恢复后不比对）
    reg [15:0]   ms_a_cnt, ms_b_cnt;         // 距上次有效样本的毫秒数（超时监控）
    reg          got_a_vld, got_b_vld;       // 毫秒窗内出现 vld 的粘滞标志
    assign seq_a       = seq_a_r;   assign seq_b       = seq_b_r;
    assign tick_cnt    = tick_cnt_r;
    assign vld_a_cnt   = vld_a_r;   assign vld_b_cnt   = vld_b_r;
    assign drdy0_a_cnt = drdy0_a_r; assign drdy0_b_cnt = drdy0_b_r;
    assign wd_a_cnt    = wd_a_r;    assign wd_b_cnt    = wd_b_r;
    assign dup_a_cnt   = dup_a_r;   assign dup_b_cnt   = dup_b_r;
    localparam [2:0] RET_PWRUP_A = 3'd0,  // 上电后 → WHO(A)
                     RET_RST_A   = 3'd1,  // A 复位后 → INIT(A)
                     RET_INIT_A  = 3'd2,  // A 初始化后 → WHO(B)
                     RET_RST_B   = 3'd3,
                     RET_INIT_B  = 3'd4,  // B 初始化后 → 进入运行
                     RET_RUN     = 3'd5;  // 重试初始化后 → 回运行
    localparam [31:0] T_RETRY = CLK_FREQ / 1000 * RETRY_MS;
    localparam REGISTER_BUDGET = REGISTER_SPI_DIV * 66 + 32;
    localparam REGISTER_START_LIMIT = TICK_MAX > REGISTER_BUDGET ? TICK_MAX - REGISTER_BUDGET : 0;
    assign diagnostic_state = {22'd0, retry_device, retry_pending, retry_run, init_flow_done, cur_b, st};

    // init_done：流程完成 且 至少一片在线
    assign init_done = init_flow_done & ~(err_icm_a & err_icm_b);

    // 掉线看门狗：整帧（INT_STATUS + 14 数据字节）全 0x00 或全 0xFF
    wire [119:0] burst_all = {int_status, rx_buf_0, rx_buf_1, rx_buf_2, rx_buf_3,
                              rx_buf_4,  rx_buf_5, rx_buf_6, rx_buf_7,
                              rx_buf_8,  rx_buf_9,  rx_buf_10, rx_buf_11,
                              rx_buf_12, rx_buf_13};
    wire bad_frame = (~|burst_all) | (&burst_all);
    wire [111:0] burst_data = burst_all[111:0];   // 本拍 14 数据字节（dup 比对用）

    // 突发读帧发射（帧0：地址 0x3A|读；帧1..15：dummy）
    // 在 ST_B_ISS 状态内组合完成 sop
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            verify_bad<=0;verify_value<=0;
            st <= ST_PWRUP; cur_b <= 1'b0; init_idx <= 4'd0; burst_idx <= 5'd0;
            who_val <= 8'h00; wait_ret <= RET_PWRUP_A;
            retry_run <= 1'b0; retry_sel <= 1'b0; retry_tmr <= 32'd0;
            retry_pending<=0; retry_device<=0; retry_resume<=ST_RST_ISS1; retry_wait<=0;
            who_a<=0; who_b<=0; config_bad_a<=10'h3ff; config_bad_b<=10'h3ff;
            config_failure_a<=0; config_failure_b<=0; status_a<=0; status_b<=0;
            retries_a<=0; retries_b<=0;
            bad_a <= 2'd0; bad_b <= 2'd0; init_flow_done <= 1'b0;
            seq_a_r <= 16'd0; seq_b_r <= 16'd0;
            tick_cnt_r <= 16'd0; vld_a_r <= 16'd0; vld_b_r <= 16'd0;
            drdy0_a_r <= 16'd0; drdy0_b_r <= 16'd0;
            wd_a_r <= 8'd0; wd_b_r <= 8'd0;
            dup_a_r <= 16'd0; dup_b_r <= 16'd0;
            last_a_data <= 112'd0; last_b_data <= 112'd0;
            last_a_vld <= 1'b0; last_b_vld <= 1'b0;
            ms_a_cnt <= 16'd0; ms_b_cnt <= 16'd0;
            got_a_vld <= 1'b0; got_b_vld <= 1'b0;
            int_status <= 8'h00;
            vld_icm_a <= 1'b0; vld_icm_b <= 1'b0;
            err_icm_a <= 1'b1; err_icm_b <= 1'b1;
            wait_cnt <= 24'd0;
            sop <= 1'b0; op_dev <= DEV_A; op_nbits <= 5'd8;
            op_tx <= 16'h0; op_hold <= 1'b0; cs_release <= 1'b0;
            op_register <= 1'b1;
            op_status <= 1'b0;
            icm_a_ax <= 16'sd0; icm_a_ay <= 16'sd0; icm_a_az <= 16'sd0;
            icm_a_t  <= 16'sd0; icm_a_gx <= 16'sd0; icm_a_gy <= 16'sd0; icm_a_gz <= 16'sd0;
            icm_b_ax <= 16'sd0; icm_b_ay <= 16'sd0; icm_b_az <= 16'sd0;
            icm_b_t  <= 16'sd0; icm_b_gx <= 16'sd0; icm_b_gy <= 16'sd0; icm_b_gz <= 16'sd0;
            rx_buf_0 <= 8'd0;  rx_buf_1 <= 8'd0;  rx_buf_2 <= 8'd0;  rx_buf_3 <= 8'd0;
            rx_buf_4 <= 8'd0;  rx_buf_5 <= 8'd0;  rx_buf_6 <= 8'd0;  rx_buf_7 <= 8'd0;
            rx_buf_8 <= 8'd0;  rx_buf_9 <= 8'd0;  rx_buf_10 <= 8'd0; rx_buf_11 <= 8'd0;
            rx_buf_12 <= 8'd0; rx_buf_13 <= 8'd0;
        end else begin
            sop        <= 1'b0;
            op_status  <= 1'b0;
            cs_release <= 1'b0;
            vld_icm_a  <= 1'b0;
            vld_icm_b  <= 1'b0;
            if (sample_tick) tick_cnt_r <= tick_cnt_r + 16'd1;
            if (retry_wait!=0) retry_wait<=retry_wait-1'b1;

            //------------------------------------------------------------------
            // 有效样本超时监控（v0.8）：器件在线（!err）且初始化完成后，
            // 持续 SAMPLE_TIMEOUT_MS 无 vld → 判"停发新数据"，置 err 交
            // 周期重试自愈。背景：坏帧看门狗只覆盖突发读全 0x00/全 0xFF
            // （MISO 悬空/片选失效）；SPI 应答正常但 DRDY 恒 0（内部采样
            // 停摆/时钟异常）时数据字节为陈旧值，旧看门狗不触发、err 永
            // 不置位。
            // wd_a/b_cnt 语义随之扩展为"数据看门狗触发次数"（坏帧+超时
            // 两类共用计数，上位机见 wd 增长即数据断流）。
            // got_x_vld 为毫秒窗粘滞标志（vld 是单拍脉冲，与 ms_tick
            // 不对齐，直接采样会漏计 → 每毫秒窗内有任意 vld 即清超时）。
            //------------------------------------------------------------------
            if (ms_tick) begin
                if (!init_flow_done || err_icm_a) begin
                    ms_a_cnt <= 16'd0; got_a_vld <= 1'b0;
                end else if (got_a_vld) begin
                    ms_a_cnt <= 16'd0; got_a_vld <= 1'b0;
                end else if (ms_a_cnt >= SAMPLE_TIMEOUT_MS - 16'd1) begin
                    err_icm_a <= 1'b1;
                    wd_a_r    <= wd_a_r + 8'd1;
                    last_a_vld<= 1'b0;
                    ms_a_cnt  <= 16'd0;
                end else ms_a_cnt <= ms_a_cnt + 16'd1;

                if (!init_flow_done || err_icm_b) begin
                    ms_b_cnt <= 16'd0; got_b_vld <= 1'b0;
                end else if (got_b_vld) begin
                    ms_b_cnt <= 16'd0; got_b_vld <= 1'b0;
                end else if (ms_b_cnt >= SAMPLE_TIMEOUT_MS - 16'd1) begin
                    err_icm_b <= 1'b1;
                    wd_b_r    <= wd_b_r + 8'd1;
                    last_b_vld<= 1'b0;
                    ms_b_cnt  <= 16'd0;
                end else ms_b_cnt <= ms_b_cnt + 16'd1;
            end

            case (st)
            //--------------------------------------------------------------
            ST_PWRUP: begin
                wait_cnt <= MS_TICKS * POWERUP_MS;
                st       <= ST_WAIT;
                wait_ret <= RET_PWRUP_A;
            end
            //--------------------------------------------------------------
            ST_WAIT: begin
                if (wait_cnt != 27'd0) begin
                    wait_cnt <= wait_cnt - 27'd1;
                end else begin
                    case (wait_ret)
                        RET_PWRUP_A: begin cur_b <= 1'b0; st <= ST_RST_ISS1; end
                        RET_RST_A:   begin cur_b <= 1'b0; st <= ST_WHO_ISS1; end
                        RET_INIT_A:  begin cur_b <= 1'b1; st <= ST_RST_ISS1; end
                        RET_RST_B:   begin cur_b <= 1'b1; st <= ST_WHO_ISS1; end
                        RET_INIT_B:  begin st <= ST_RUN_TICK; end
                        RET_RUN:     begin st <= ST_RUN_TICK; end
                        default:     st <= ST_WHO_ISS1;
                    endcase
                end
            end
            //--------------------------------------------------------------
            // WHO_AM_I：2 帧（0x80|0x75，dummy）
            ST_WHO_ISS1: if (!eng_busy) begin
                op_register <= 1'b1;
                sop <= 1'b1; op_dev <= cur_b ? DEV_B : DEV_A;
                op_nbits <= 5'd8; op_tx <= {8'h00, 8'h80 | 8'h75}; op_hold <= 1'b1; // 保持CS：地址+dummy 为同一事务
                st <= ST_WHO_WAIT1;
            end
            ST_WHO_WAIT1: if (eng_done) st <= ST_WHO_ISS2;
            ST_WHO_ISS2: if (!eng_busy) begin
                sop <= 1'b1; op_dev <= cur_b ? DEV_B : DEV_A;
                op_nbits <= 5'd8; op_tx <= 16'h00FF; op_hold <= 1'b0;
                st <= ST_WHO_WAIT2;
            end
            ST_WHO_WAIT2: if (eng_done) begin
                who_val <= eng_rx[7:0];
                if (!cur_b) who_a<=eng_rx[7:0]; else who_b<=eng_rx[7:0];
                st <= ST_WHO_CHK;
            end
            ST_WHO_CHK: begin
                if ((who_val == WHO_ID) || (ACCEPT_WHO_2E && who_val == 8'h2e)) begin
                    if (!cur_b) begin config_bad_a<=0; config_failure_a<=0; end
                    else begin config_bad_b<=0; config_failure_b<=0; end
                    init_idx <= 4'd0;
                    if (retry_run) begin
                        retry_resume<=ST_INIT_ISS1; retry_pending<=1; st<=ST_RUN_TICK;
                    end else st <= ST_INIT_ISS1;
                end else begin
                    if (retry_run) begin
                        // 运行期重试失败：保持 err，回运行态，下个重试周期再试
                        if (!cur_b) err_icm_a <= 1'b1; else err_icm_b <= 1'b1;
                        retry_run <= 1'b0;
                        retry_pending <= 1'b0;
                        st        <= ST_RUN_TICK;
                    end else if (!cur_b) begin
                        // 上电初始化：A 失败标记后跳过 A，试 B
                        err_icm_a <= 1'b1;
                        cur_b <= 1'b1;
                        st    <= ST_RST_ISS1;
                    end else begin
                        err_icm_b <= 1'b1;
                        wait_cnt <= MS_TICKS * POSTINIT_MS;
                        wait_ret <= RET_INIT_B;  // B 也失败：直接进入运行
                        st       <= ST_WAIT;
                    end
                end
            end
            //--------------------------------------------------------------
            // 软复位：写 PWR_MGMT_1 = 0x80，等 RESET_MS
            // 注意：ISS2 必须等 ISS1 帧的 eng_done——eng_busy 在 sop 后一拍
            // 才置位，若 ISS2 直接判 !eng_busy 会连发两个 sop，地址帧被覆盖
            ST_RST_ISS1: if (!eng_busy) begin
                op_register <= 1'b1;
                if (!cur_b) begin config_bad_a<=10'h3ff; status_a<=0; end
                else begin config_bad_b<=10'h3ff; status_b<=0; end
                sop <= 1'b1; op_dev <= cur_b ? DEV_B : DEV_A;
                op_nbits <= 5'd8; op_tx <= {8'h00, 8'h6B}; op_hold <= 1'b1; // 保持CS：地址+数据同事务
                st <= ST_RST_ISS2;
            end
            ST_RST_ISS2: if (eng_done) begin
                sop <= 1'b1; op_dev <= cur_b ? DEV_B : DEV_A;
                op_nbits <= 5'd8; op_tx <= {8'h00, 8'h80}; op_hold <= 1'b0;
                st <= ST_RST_WAIT2;
            end
            ST_RST_WAIT2: if (eng_done) begin
                if (retry_run) begin
                    retry_wait<=MS_TICKS*RESET_MS;
                    retry_resume<=ST_WHO_ISS1; retry_pending<=1; st<=ST_RUN_TICK;
                end else begin
                    wait_cnt <= MS_TICKS * RESET_MS;
                    wait_ret <= cur_b ? RET_RST_B : RET_RST_A;
                    st       <= ST_WAIT;
                end
            end
            //--------------------------------------------------------------
            // 初始化表写入（ISS2 同样等 eng_done，见软复位处说明）
            ST_INIT_ISS1: if (!eng_busy) begin
                op_register <= 1'b1;
                sop <= 1'b1; op_dev <= cur_b ? DEV_B : DEV_A;
                op_nbits <= 5'd8; op_tx <= {8'h00, init_word[15:8]}; op_hold <= 1'b1; // 保持CS
                st <= ST_INIT_ISS2;
            end
            ST_INIT_ISS2: if (eng_done) begin
                sop <= 1'b1; op_dev <= cur_b ? DEV_B : DEV_A;
                op_nbits <= 5'd8; op_tx <= {8'h00, init_word[7:0]}; op_hold <= 1'b0;
                st <= ST_INIT_WAIT2;
            end
            ST_INIT_WAIT2: if (eng_done) begin
                if (init_idx == INIT_LEN - 1) begin
                    init_idx<=0;verify_bad<=0;
                    if (retry_run) begin retry_resume<=ST_VERIFY_ADDR; retry_pending<=1; st<=ST_RUN_TICK; end
                    else st<=ST_VERIFY_ADDR;
                end else begin
                    init_idx<=init_idx+1'b1;
                    if (retry_run) begin retry_resume<=ST_INIT_ISS1; retry_pending<=1; st<=ST_RUN_TICK; end
                    else st<=ST_INIT_ISS1;
                end
            end
            ST_VERIFY_ADDR: if(!eng_busy) begin
                op_register<=1;
                sop<=1;op_dev<=cur_b ? DEV_B:DEV_A;op_nbits<=8;
                op_tx<={8'h00,(init_word[15:8]|8'h80)};op_hold<=1;st<=ST_VERIFY_DATA;
            end
            ST_VERIFY_DATA: if(eng_done) begin
                sop<=1;op_dev<=cur_b ? DEV_B:DEV_A;op_nbits<=8;
                op_tx<=16'h00ff;op_hold<=0;st<=ST_VERIFY_WAIT;
            end
            ST_VERIFY_WAIT: if(eng_done) begin verify_value<=eng_rx[7:0];st<=ST_VERIFY_CHECK;end
            ST_VERIFY_CHECK: begin
                if(verify_value!=init_word[7:0]) begin
                    verify_bad<=1;
                    if (!cur_b) begin config_bad_a[init_idx]<=1; config_failure_a<={init_word,verify_value}; end
                    else begin config_bad_b[init_idx]<=1; config_failure_b<={init_word,verify_value}; end
                end
                if(init_idx==INIT_LEN-1)st<=ST_VERIFY_DONE;
                else begin
                    init_idx<=init_idx+1'b1;
                    if (retry_run) begin retry_resume<=ST_VERIFY_ADDR; retry_pending<=1; st<=ST_RUN_TICK; end
                    else st<=ST_VERIFY_ADDR;
                end
            end
            ST_VERIFY_DONE: begin
                if(retry_run) begin
                    retry_wait<=MS_TICKS*POSTINIT_MS;
                    retry_resume<=ST_RECOVER_DONE; retry_pending<=1; st<=ST_RUN_TICK;
                end else begin
                    if(!cur_b)err_icm_a<=verify_bad;else err_icm_b<=verify_bad;
                    wait_cnt<=MS_TICKS*POSTINIT_MS;
                    wait_ret<=cur_b ? RET_INIT_B:RET_INIT_A;
                    st<=ST_WAIT;
                end
            end
            ST_RECOVER_DONE: begin
                if (!cur_b) begin
                    err_icm_a<=verify_bad; bad_a<=0; last_a_vld<=0; ms_a_cnt<=0; got_a_vld<=0;
                end else begin
                    err_icm_b<=verify_bad; bad_b<=0; last_b_vld<=0; ms_b_cnt<=0; got_b_vld<=0;
                end
                retry_run<=0; retry_pending<=0; st<=ST_RUN_TICK;
            end
            //--------------------------------------------------------------
            ST_RUN_TICK: begin
                init_flow_done <= 1'b1;
                if (sample_tick) begin
                    burst_idx <= 5'd0;
                    // 双掉线：两片皆 err，本拍不发起读，等周期重试自愈
                    if (!err_icm_a || !err_icm_b) begin
                        cur_b <= err_icm_a;   // A 在线读 A；仅 A 掉线才切读 B
                        st    <= ST_B_ISS;
                    end
                end else if (retry_run) begin
                    if (retry_pending && retry_wait==0 && tick_ph<REGISTER_START_LIMIT) begin
                        cur_b<=retry_device; retry_pending<=0; st<=retry_resume;
                    end
                end else if (retry_tmr >= T_RETRY - 32'd1 && tick_ph<REGISTER_START_LIMIT) begin
                    // 掉线片周期重试：复位 → 等待 → WHO 校验 → 重初始化（自愈）
                    retry_tmr <= 32'd0;
                    if (err_icm_a && (!err_icm_b || retry_sel == 1'b0)) begin
                        retry_run <= 1'b1;
                        retry_sel <= 1'b1;
                        cur_b     <= 1'b0;
                        retry_device<=0; retry_pending<=0; retries_a<=retries_a+1'b1;
                        st        <= ST_RST_ISS1;
                    end else if (err_icm_b) begin
                        retry_run <= 1'b1;
                        retry_sel <= 1'b0;
                        cur_b     <= 1'b1;
                        retry_device<=1; retry_pending<=0; retries_b<=retries_b+1'b1;
                        st        <= ST_RST_ISS1;
                    end
                end else begin
                    retry_tmr <= retry_tmr + 32'd1;
                end
            end
            //--------------------------------------------------------------
            // 突发读 0x3A 起 15 字节（CS 保持到组装完成）：
            //   帧1 = INT_STATUS(DRDY)，帧2..15 = 0x3B..0x48 数据
            ST_B_ISS: if (!eng_busy) begin
                op_register <= 1'b0;
                op_status <= (burst_idx <= 5'd1);
                sop <= 1'b1; op_dev <= cur_b ? DEV_B : DEV_A;
                op_nbits <= 5'd8; op_hold <= 1'b1;
                op_tx <= (burst_idx == 5'd0) ? {8'h00, 8'h80 | 8'h3A} : 16'h0000;
                st <= ST_B_WAIT;
            end
            ST_B_WAIT: if (eng_done) begin
                if (burst_idx == 5'd1 && eng_rx[0] == 1'b0 && eng_rx[7:0] != 8'hFF) begin
                    cs_release <= 1'b1;
                    int_status <= eng_rx[7:0];
                    if (!cur_b) begin
                        status_a <= eng_rx[7:0];
                        bad_a <= 2'd0;
                        drdy0_a_r <= drdy0_a_r + 16'd1;
                        cur_b <= 1'b1;
                        burst_idx <= 5'd0;
                        if (err_icm_b) st <= ST_RUN_TICK;
                        else           st <= ST_B_ISS;
                    end else begin
                        status_b <= eng_rx[7:0];
                        bad_b <= 2'd0;
                        drdy0_b_r <= drdy0_b_r + 16'd1;
                        st <= ST_RUN_TICK;
                    end
                end else begin
                    // 帧0 是地址应答（丢弃），帧1..15 依次入缓冲
                    case (burst_idx)
                        5'd1:  int_status <= eng_rx[7:0];
                        5'd2:  rx_buf_0  <= eng_rx[7:0];
                        5'd3:  rx_buf_1  <= eng_rx[7:0];
                        5'd4:  rx_buf_2  <= eng_rx[7:0];
                        5'd5:  rx_buf_3  <= eng_rx[7:0];
                        5'd6:  rx_buf_4  <= eng_rx[7:0];
                        5'd7:  rx_buf_5  <= eng_rx[7:0];
                        5'd8:  rx_buf_6  <= eng_rx[7:0];
                        5'd9:  rx_buf_7  <= eng_rx[7:0];
                        5'd10: rx_buf_8  <= eng_rx[7:0];
                        5'd11: rx_buf_9  <= eng_rx[7:0];
                        5'd12: rx_buf_10 <= eng_rx[7:0];
                        5'd13: rx_buf_11 <= eng_rx[7:0];
                        5'd14: rx_buf_12 <= eng_rx[7:0];
                        5'd15: rx_buf_13 <= eng_rx[7:0];
                        default: ;
                    endcase
                    if (burst_idx == 5'd15) begin
                        st <= ST_B_ASSEM;
                    end else begin
                        burst_idx <= burst_idx + 5'd1;
                        st        <= ST_B_ISS;
                    end
                end
            end
            ST_B_ASSEM: begin
                cs_release <= 1'b1;
                if (!cur_b) status_a<=int_status; else status_b<=int_status;
                // 掉线看门狗：连续 3 帧全 0x00/全 0xFF → 判离线，触发周期重试
                if (bad_frame) begin
                    if (!cur_b) begin
                        if (bad_a == 2'd2) begin err_icm_a <= 1'b1; bad_a <= 2'd0; wd_a_r <= wd_a_r + 8'd1; last_a_vld <= 1'b0; end
                        else                     bad_a <= bad_a + 2'd1;
                    end else begin
                        if (bad_b == 2'd2) begin err_icm_b <= 1'b1; bad_b <= 2'd0; wd_b_r <= wd_b_r + 8'd1; last_b_vld <= 1'b0; end
                        else                     bad_b <= bad_b + 2'd1;
                    end
                end else begin
                    if (!cur_b) bad_a <= 2'd0; else bad_b <= 2'd0;
                    // DRDY=1 才是本拍新样本（避免 ICM 内部 ODR 与节拍频差
                    // 引起的重复样本/丢拍悄悄污染数据流）
                    if (int_status[0]) begin
                        if (!cur_b) begin
                            icm_a_ax <= {rx_buf_0,  rx_buf_1};
                            icm_a_ay <= {rx_buf_2,  rx_buf_3};
                            icm_a_az <= {rx_buf_4,  rx_buf_5};
                            icm_a_t  <= {rx_buf_6,  rx_buf_7};
                            icm_a_gx <= {rx_buf_8,  rx_buf_9};
                            icm_a_gy <= {rx_buf_10, rx_buf_11};
                            icm_a_gz <= {rx_buf_12, rx_buf_13};
                            vld_icm_a <= 1'b1;
                            got_a_vld <= 1'b1;    // 毫秒窗粘滞（超时监控）
                            seq_a_r   <= seq_a_r + 16'd1;
                            vld_a_r   <= vld_a_r + 16'd1;
                            if (last_a_vld && (burst_data == last_a_data))
                                dup_a_r <= dup_a_r + 16'd1;
                            last_a_data <= burst_data;
                            last_a_vld  <= 1'b1;
                        end else begin
                            icm_b_ax <= {rx_buf_0,  rx_buf_1};
                            icm_b_ay <= {rx_buf_2,  rx_buf_3};
                            icm_b_az <= {rx_buf_4,  rx_buf_5};
                            icm_b_t  <= {rx_buf_6,  rx_buf_7};
                            icm_b_gx <= {rx_buf_8,  rx_buf_9};
                            icm_b_gy <= {rx_buf_10, rx_buf_11};
                            icm_b_gz <= {rx_buf_12, rx_buf_13};
                            vld_icm_b <= 1'b1;
                            got_b_vld <= 1'b1;    // 毫秒窗粘滞（超时监控）
                            seq_b_r   <= seq_b_r + 16'd1;
                            vld_b_r   <= vld_b_r + 16'd1;
                            if (last_b_vld && (burst_data == last_b_data))
                                dup_b_r <= dup_b_r + 16'd1;
                            last_b_data <= burst_data;
                            last_b_vld  <= 1'b1;
                        end
                    end else begin
                        // 本拍无新样本（DRDY=0）：正常现象（节拍 2 倍于 ODR），
                        // 计数供上位机核对 vld/节拍比率是否偏离 ODR
                        if (!cur_b) drdy0_a_r <= drdy0_a_r + 16'd1;
                        else        drdy0_b_r <= drdy0_b_r + 16'd1;
                    end
                end
                if (!cur_b) begin
                    cur_b <= 1'b1; burst_idx <= 5'd0;
                    if (err_icm_b) st <= ST_RUN_TICK;   // B 掉线：跳过其突发读
                    else           st <= ST_B_ISS;
                end else begin
                    st <= ST_RUN_TICK;
                end
            end
            //--------------------------------------------------------------
            default: st <= ST_PWRUP;
            endcase
        end
    end

endmodule
