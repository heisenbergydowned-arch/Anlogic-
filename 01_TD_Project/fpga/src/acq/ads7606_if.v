//============================================================================
// ads7606_if.v — AD7606 8 通道同步采样 ADC 串行接口（单线 DOUTA 模式）
//
// 器件：ADI AD7606（经典款，无配置寄存器，全部引脚硬配置）。
// 板级硬连接要求：PAR/SER/BYTE=1（串行）、STBY=1、OS[2:0]=000（不过采样）、
//   CONVSTA/B 短接、RANGE 按量程（0=±5V，1=±10V）、VDRIVE=3.3V（直连 BANK11）。
//
// 时序（AD7606 数据手册 Rev G）：
//   CONVST 上升沿启动 8 通道同时转换（高脉宽≥25ns，本设计 200ns）；
//   BUSY ≤45ns 后拉高，tCONV ≤4.2µs 后拉低 = 数据就绪；
//   CS↓ → DOUTA 呈现 V1 的 MSB → 其后每个 SCLK 上升沿出下一位；
//   单线模式 128 位依序读出 V1..V8（MSB first），FRSTDATA 在前 16 位为高；
//   SCLK ≤17MHz（本设计 12.5MHz），采样点在 SCLK 低电平末尾（建立裕量最大）。
//   帧预算@50kSPS：BUSY 4.2µs + 读数 10.3µs = 14.5µs < 周期 20µs。
//
// 容错：BUSY 上升 1µs / 下降 10µs 超时 → err 置位、跳过本帧（器件不在位
//       不阻塞系统）；FRSTDATA 相位校验；正常帧完成自动清 err。
// 数据：16 位补码。±5V 量程 1LSB=152.58µV，±10V 量程 1LSB=305.18µV。
//============================================================================
module ads7606_if #(
    parameter CLK_FREQ  = 100_000_000,
    parameter SAMPLE_HZ = 50_000,          // CONVST 频率 = 每通道采样率
    parameter SCLK_DIV  = 4,               // SCLK = CLK_FREQ/(2*SCLK_DIV) = 12.5MHz
    parameter CONVST_CK = 20,              // CONVST 高电平宽度（clk 数，200ns）
    parameter POWERUP_US = 50_000,
    parameter RESET_HIGH_US = 10,
    parameter RESET_RECOVERY_US = 1_000
)(
    input  wire clk,
    input  wire rst_n,
    output reg  o_reset,

    // AD7606 物理接口
    output reg  o_convst,      // 空闲低；上升沿启动转换
    input  wire i_busy,        // 高 = 转换进行中
    output reg  o_sclk,        // 空闲低；读数时 12.5MHz
    input  wire i_douta,       // 串行数据（MSB first，V1→V8）
    output reg  o_cs_n,        // 空闲高；读数窗口
    input  wire i_frstdata,    // 前 16 位（V1）期间为高

    // 采样结果（V1..V8 对应器件通道 1..8）
    output reg  signed [15:0] ch1_code,
    output reg  signed [15:0] ch2_code,
    output reg  signed [15:0] ch3_code,
    output reg  signed [15:0] ch4_code,
    output reg  signed [15:0] ch5_code,
    output reg  signed [15:0] ch6_code,
    output reg  signed [15:0] ch7_code,
    output reg  signed [15:0] ch8_code,
    output reg  vld,           // 每帧一拍（SAMPLE_HZ）
    output reg  err            // 黏性：超时/FRSTDATA 错；正常帧自动清
);
    localparam integer TICKS    = CLK_FREQ / SAMPLE_HZ;   // 帧周期（clk）
    localparam integer TO_UP_CK = CLK_FREQ / 1_000_000;  // BUSY 上升超时 1µs
    localparam integer TO_DN_CK = CLK_FREQ / 100_000;    // BUSY 下降超时 10µs
    localparam integer TICK_WIDTH = TICKS < 2 ? 1 : $clog2(TICKS);
    localparam integer MICRO_TICKS = (CLK_FREQ + 999_999) / 1_000_000;
    localparam integer MICRO_WIDTH = MICRO_TICKS < 2 ? 1 : $clog2(MICRO_TICKS);
    localparam integer RESET_MAX_US = POWERUP_US > RESET_HIGH_US ? POWERUP_US : RESET_HIGH_US;
    localparam integer STARTUP_MAX_US = RESET_MAX_US > RESET_RECOVERY_US ? RESET_MAX_US : RESET_RECOVERY_US;
    localparam integer STARTUP_WIDTH = STARTUP_MAX_US < 2 ? 1 : $clog2(STARTUP_MAX_US);

    reg [MICRO_WIDTH-1:0] micro_count;
    reg [STARTUP_WIDTH-1:0] startup_count;
    reg [1:0] startup_state;
    reg startup_ready;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            micro_count <= 0;
            startup_count <= 0;
            startup_state <= 0;
            startup_ready <= 1'b0;
            o_reset <= 1'b0;
        end else if (!startup_ready) begin
            if (micro_count == MICRO_TICKS - 1) begin
                micro_count <= 0;
                case (startup_state)
                    0: begin
                        if (startup_count == POWERUP_US - 1) begin
                            startup_count <= 0;
                            startup_state <= 1;
                            o_reset <= 1'b1;
                        end else startup_count <= startup_count + 1'b1;
                    end
                    1: begin
                        if (startup_count == RESET_HIGH_US - 1) begin
                            startup_count <= 0;
                            startup_state <= 2;
                            o_reset <= 1'b0;
                        end else startup_count <= startup_count + 1'b1;
                    end
                    2: begin
                        if (startup_count == RESET_RECOVERY_US - 1) begin
                            startup_count <= 0;
                            startup_state <= 3;
                            startup_ready <= 1'b1;
                        end else startup_count <= startup_count + 1'b1;
                    end
                    default: begin
                        startup_count <= 0;
                        startup_state <= 0;
                        o_reset <= 1'b0;
                    end
                endcase
            end else micro_count <= micro_count + 1'b1;
        end
    end

    // 注意：TICKS 对应的周期必须大于 转换+读数 总时间
    // （默认参数 ≈14.5µs < 20µs），否则节拍被跳过、实际采样率减半。

    //--------------------------------------------------------------------
    // 引脚 2FF 同步
    //--------------------------------------------------------------------
    reg [1:0] busy_s, douta_s, frst_s;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy_s  <= 2'b00;
            douta_s <= 2'b00;
            frst_s  <= 2'b00;
        end else begin
            busy_s  <= {busy_s[0],  i_busy};
            douta_s <= {douta_s[0], i_douta};
            frst_s  <= {frst_s[0],  i_frstdata};
        end
    end

    //--------------------------------------------------------------------
    // 状态机
    //--------------------------------------------------------------------
    localparam [2:0] S_WAIT = 3'd0,   // 帧间隔计时
                     S_CVT  = 3'd1,   // CONVST 高电平脉冲
                     S_UP   = 3'd2,   // 等 BUSY 上升
                     S_DN   = 3'd3,   // 等 BUSY 下降（转换完成）
                     S_PRE  = 3'd4,   // CS↓ 后等 1 个 SCLK 周期，采 MSB
                     S_BIT  = 3'd5,   // 127 位：高/低相位交替，低位末采样
                     S_DONE = 3'd6;   // CS 保持半周期后拉高，发 vld

    reg  [2:0]  st;
    reg  [TICK_WIDTH-1:0] tick_cnt;
    reg  [15:0] tmr;        // 复用计时：脉宽/超时/相位计数
    reg  [6:0]  bit_idx;    // 当前位序号 1..127（0 在 S_PRE 采）
    reg         ph;         // S_BIT 内 1=SCLK 高相位
    reg  [15:0] rx_shift;
    reg         frst_bad;

    wire [15:0] rx_new = {rx_shift[14:0], douta_s[1]};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= S_WAIT; tick_cnt <= 0; tmr <= 16'd0; bit_idx <= 7'd0;
            ph <= 1'b0; rx_shift <= 16'd0; frst_bad <= 1'b0;
            o_convst <= 1'b0; o_sclk <= 1'b0; o_cs_n <= 1'b1;
            ch1_code <= 16'sd0; ch2_code <= 16'sd0; ch3_code <= 16'sd0; ch4_code <= 16'sd0;
            ch5_code <= 16'sd0; ch6_code <= 16'sd0; ch7_code <= 16'sd0; ch8_code <= 16'sd0;
            vld <= 1'b0; err <= 1'b0;
        end else if (!startup_ready) begin
            st <= S_WAIT;
            tick_cnt <= 0;
            tmr <= 0;
            bit_idx <= 0;
            ph <= 0;
            rx_shift <= 0;
            frst_bad <= 0;
            o_convst <= 0;
            o_sclk <= 0;
            o_cs_n <= 1;
            vld <= 0;
            err <= 0;
        end else begin
            vld <= 1'b0;
            // 帧节拍自由运行：忙不过来时跳过该拍（实际速率减半，不堆积）
            tick_cnt <= (tick_cnt >= TICKS - 1) ? 0 : tick_cnt + 1'b1;

            case (st)
            //--------------------------------------------------------------
            S_WAIT: begin
                if (tick_cnt >= TICKS - 32'd1) begin
                    tick_cnt <= 0;
                    o_convst <= 1'b1;
                    tmr      <= 16'd0;
                    frst_bad <= 1'b0;
                    st       <= S_CVT;
                end
            end
            //--------------------------------------------------------------
            S_CVT: begin
                if (tmr >= CONVST_CK - 16'd1) begin
                    o_convst <= 1'b0;
                    tmr      <= 16'd0;
                    st       <= S_UP;
                end else begin
                    tmr <= tmr + 16'd1;
                end
            end
            //--------------------------------------------------------------
            S_UP: begin                      // BUSY 应在 CONVST↑ 后 ≤45ns 升高
                if (busy_s[1]) begin
                    tmr <= 16'd0;
                    st  <= S_DN;
                end else if (tmr >= TO_UP_CK - 16'd1) begin
                    err <= 1'b1;             // 器件不在位：跳过本帧
                    st  <= S_WAIT;
                end else begin
                    tmr <= tmr + 16'd1;
                end
            end
            //--------------------------------------------------------------
            S_DN: begin                      // tCONV ≤4.2µs（10µs 超时保护）
                if (!busy_s[1]) begin
                    o_cs_n <= 1'b0;          // CS↓：MSB 上线
                    tmr    <= 16'd0;
                    st     <= S_PRE;
                end else if (tmr >= TO_DN_CK - 16'd1) begin
                    err <= 1'b1;             // BUSY 不回落：器件异常
                    st  <= S_WAIT;
                end else begin
                    tmr <= tmr + 16'd1;
                end
            end
            //--------------------------------------------------------------
            S_PRE: begin                     // 等 1 个 SCLK 周期后采 bit0
                if (tmr >= 2 * SCLK_DIV - 16'd1) begin
                    rx_shift <= rx_new;                       // bit0 = V1[15]
                    if (!frst_s[1]) frst_bad <= 1'b1;         // 此处应高
                    bit_idx <= 7'd1;
                    ph      <= 1'b1;
                    o_sclk  <= 1'b1;                          // 上升沿 1
                    tmr     <= 16'd0;
                    st      <= S_BIT;
                end else begin
                    tmr <= tmr + 16'd1;
                end
            end
            //--------------------------------------------------------------
            S_BIT: begin
                if (tmr >= SCLK_DIV - 16'd1) begin
                    tmr <= 16'd0;
                    if (ph) begin
                        ph     <= 1'b0;
                        o_sclk <= 1'b0;                       // 下降沿
                    end else begin
                        // SCLK 低电平末尾：数据已稳定 1 个周期，采样
                        rx_shift <= rx_new;
                        if (bit_idx[3:0] == 4'd15) begin       // 凑满 16 位
                            case (bit_idx[6:4])
                                3'd0: ch1_code <= rx_new;
                                3'd1: ch2_code <= rx_new;
                                3'd2: ch3_code <= rx_new;
                                3'd3: ch4_code <= rx_new;
                                3'd4: ch5_code <= rx_new;
                                3'd5: ch6_code <= rx_new;
                                3'd6: ch7_code <= rx_new;
                                default: ch8_code <= rx_new;
                            endcase
                        end
                        if (bit_idx == 7'd17 && frst_s[1])     // 此处应低
                            frst_bad <= 1'b1;
                        if (bit_idx >= 7'd127) begin
                            st <= S_DONE;                      // 不再出上升沿
                        end else begin
                            bit_idx <= bit_idx + 7'd1;
                            ph      <= 1'b1;
                            o_sclk  <= 1'b1;                   // 下一位上升沿
                        end
                    end
                end else begin
                    tmr <= tmr + 16'd1;
                end
            end
            //--------------------------------------------------------------
            S_DONE: begin                   // CS 保持 ≥ 半周期（t_H_SCK_CS）
                if (tmr >= SCLK_DIV - 16'd1) begin
                    o_cs_n <= 1'b1;
                    vld    <= 1'b1;
                    err    <= frst_bad;     // 正常帧自动清历史错误
                    st     <= S_WAIT;
                end else begin
                    tmr <= tmr + 16'd1;
                end
            end
            default: st <= S_WAIT;
            endcase
        end
    end

endmodule
