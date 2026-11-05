//============================================================================
// dbg_uart.v — PL 调试串口（115200 8N1，双帧周期发送）
//
// 作用：给全部测量量/状态/诊断计数一个真实输出出口（防止综合裁剪
//       数据通路——尤其 BMP280 校准参数），上位机按帧格式解析即可
//       实时观测；后续可平滑演进为 PS 数据口。
//
// 帧率与带宽（115200 8N1 ≈ 11.5 KB/s 单向）：frm_tmr 仅在发送空闲期计数，
//   帧传输时间不计入 → 帧 A 实际周期 = FRAME_MS + 传输时间（77B ≈ 6.7ms）
//   ≈ 106.7ms，即 **~9.4 帧/s**（非精确 10 帧/s）；帧 B 每 CAL_DIV(10) 个
//   A 周期插入一次（B 后立即补发一帧 A 保持节奏，B 实际 ~1.18s 一帧）。
//   带宽 ≈ 77B×9.4 + 27B×0.85 ≈ 744 B/s ≈ 7.4 kbps。
//   注意：115200 只够冒烟观测与慢变量（温湿度/气压/状态），装不下
//   6 路 1 kSps 振动波形（12 KB/s）——振动连续采集须走 PS/DDR 通路，
//   本口不作为采集通道。
//
// 帧 A（77 字节，小端，实际每 FRAME_MS+6.7ms 一帧）：
//   [0..1]   帧头 0x55 0xA5
//   [2..3]   状态字（位定义见下）
//   [4..5]   ICM-A 样本序号 seq_a（uint16，vld +1，回绕 ~65s）
//   [6..7]   ICM-B 样本序号 seq_b
//            注：seq_a/seq_b 各自独立递增（两片 ODR 各自晶振，序号相互
//            漂移属正常），下游 ratio_ab/联合 FFT 必须按帧内 tick 时间窗
//            配对，禁止按 seq 1:1 配对。
//   [8..9]   采样节拍累计 tick_cnt（2kHz）
//   [10..11] A 有效样本累计 vld_a_cnt
//   [12..13] B 有效样本累计 vld_b_cnt
//   [14..15] A 在线但 DRDY=0 次数（正常 ≈ 节拍数 − 有效数）
//   [16..17] B 同上
//   [18]     A 掉线看门狗触发次数（uint8）
//   [19]     B 同上
//   [20..21] AHT20进风温度Q12.4（int16，1/16°C/LSB）
//   [22..23] 唯一DS18B20/S4b核心温度Q12.4
//   [24..26] AHT20 湿度原始码（20bit，%RH = code/2^20×100）
//   [27..29] AHT20 温度原始码（20bit，°C = code/2^20×200-50）
//   [30..32] BMP280 温度原始码（20bit，PS 侧 Bosch 补偿）
//   [33..35] BMP280 压力原始码（20bit）
//   [36..41] ICM-A ax/ay/az（int16 ×3）
//   [42..47] ICM-B ax/ay/az（int16 ×3）
//   [48..63] ADC ch1..ch8（int16 ×8）
//   [64..67] FG 周期计数（uint32，时钟数）
//   [68..71] FG 累计脉冲数（uint32）
//   [72..73] A 相邻两次 vld 的 14 数据字节全同计数 dup_a_cnt（正常≈0；
//            持续增长 = DRDY 门控失效或器件冻结输出，后续改 FIFO 的前置判据）
//   [74..75] B 同上 dup_b_cnt
//   [76]     校验：字节 0..75 逐字节异或
//
// 帧 B（27 字节，每 CAL_DIV(10) 个帧 A 周期插入一帧，实际 ~1.18s 一帧）：
//   [0..1]   帧头 0x55 0xA6
//   [2..25]  BMP280 校准参数 24 字节（寄存器 0x88..0x9F 原样，
//            无此帧则上位机无法做 Bosch 补偿、原始码换算不出气压）
//   [26]     校验：字节 0..25 逐字节异或
//
// 状态字位定义（top.v 组装）：
//   bit0 err_icm_a  bit1 err_icm_b  bit2 err_adc
//   bit3 inlet_aht_present  bit4 temp_core_present  bit5 aht_err  bit6 bmp_err
//   bit7 fg_stall（宽限后） bit8 alarm  bit9 init_done
//   bit10 inlet_aht_stale  bit11 temp_core_stale  bit12 fg_timeout（原始）
//   bit13 bmp_cal_valid  bit14 aht_present  bit15 bmp_present
//============================================================================
module dbg_uart #(
    parameter CLK_FREQ = 100_000_000,
    parameter BAUD     = 115_200,
    parameter FRAME_MS = 100,          // 帧 A 发送周期
    parameter ARBITRATION = 0,
    parameter CAL_DIV  = 10            // 每 N 个帧 A 周期插入一帧 B（1Hz）
)(
    input  wire        clk,
    input  wire        rst_n,

    input  wire [15:0] d_status,       // 状态字（位定义见头注释）
    input  wire [15:0] d_seq_a, d_seq_b,         // ICM 样本序号
    input  wire [15:0] d_tick,                  // 采样节拍累计
    input  wire [15:0] d_vld_a, d_vld_b,        // 有效样本累计
    input  wire [15:0] d_drdy0_a, d_drdy0_b,    // 在线但 DRDY=0 累计
    input  wire [7:0]  d_wd_a, d_wd_b,          // 看门狗触发次数
    input  wire [15:0] d_dup_a, d_dup_b,        // 相邻 vld 样本全同计数（正常≈0）
    input  wire [191:0] d_bmp_cal,              // BMP280 校准 24 字节
    input  wire        d_bmp_cal_vld,           // 1 = 校准数据有效

    input  wire [15:0] d_a_ax, d_a_ay, d_a_az,  // ICM-A 加速度
    input  wire [15:0] d_b_ax, d_b_ay, d_b_az,  // ICM-B 加速度
    input  wire [15:0] d_adc1, d_adc2, d_adc3, d_adc4,
    input  wire [15:0] d_adc5, d_adc6, d_adc7, d_adc8,
    input  wire [31:0] d_fg_period,             // 测周法周期（时钟数）
    input  wire [31:0] d_fg_pcount,             // 累计 FG 脉冲
    input  wire [15:0] d_inlet_aht_q4, d_core_temp_q4,      // AHT20 inlet / DS18B20 core, signed Q12.4
    input  wire [19:0] d_aht_hum, d_aht_temp,   // AHT20 原始码
    input  wire [19:0] d_bmp_t,   d_bmp_p,      // BMP280 原始码

    input wire         holdoff,
    output wire        frame_busy,
    output reg         tx
);
    localparam integer NBYTES_A    = 77;
    localparam integer NBYTES_B    = 27;
    localparam [31:0]  BAUD_TICKS  = CLK_FREQ / BAUD;
    localparam [31:0]  FRAME_TICKS = CLK_FREQ / 1000 * FRAME_MS;

    // 帧快照移位队列：只在帧起点取一次数据；发送时按字节移位。
    // A/B复用同一个队列，保证帧内一致；XOR字节仍在发送时生成。
    reg [607:0] snap;        // 帧 A 内容（76 字节，byte0 在 [7:0]）
    reg [31:0]  frm_tmr;
    reg [6:0]   bidx;        // 当前发送字节序号
    reg [3:0]   bbit;        // 0=start, 1..8=data, 9=stop
    reg [31:0]  baud_cnt;
    reg [7:0]   cur_byte;
    reg [7:0]   xor_acc;
    reg         sending;
    reg         frm_b;       // 1 = 正在发送帧 B
    reg         pend_a;      // 帧 B 完成后立即补发帧 A（保持节奏）
    reg [3:0]   cal_div;
    reg         cal_due;
    reg stop_pending;
    reg [31:0] guard_count;
    assign frame_busy = sending || stop_pending;

    // 拼接序 = 发送序的逆序：字节引擎从 LSB 端逐字节发送（payload[7:0]
    // 最先上线），帧头放最低位端，线上字节序与头注释帧格式一致
    wire [607:0] payload_a = {
        d_dup_b[15:8], d_dup_b[7:0],
        d_dup_a[15:8], d_dup_a[7:0],
        d_fg_pcount[31:24], d_fg_pcount[23:16], d_fg_pcount[15:8], d_fg_pcount[7:0],
        d_fg_period[31:24], d_fg_period[23:16], d_fg_period[15:8], d_fg_period[7:0],
        d_adc8, d_adc7, d_adc6, d_adc5, d_adc4, d_adc3, d_adc2, d_adc1,
        d_b_az, d_b_ay, d_b_ax,
        d_a_az, d_a_ay, d_a_ax,
        {4'h0, d_bmp_p[19:16]},    d_bmp_p[15:8],  d_bmp_p[7:0],
        {4'h0, d_bmp_t[19:16]},    d_bmp_t[15:8],  d_bmp_t[7:0],
        {4'h0, d_aht_temp[19:16]}, d_aht_temp[15:8], d_aht_temp[7:0],
        {4'h0, d_aht_hum[19:16]},  d_aht_hum[15:8],  d_aht_hum[7:0],
        d_core_temp_q4, d_inlet_aht_q4,
        d_wd_b,  d_wd_a,
        d_drdy0_b, d_drdy0_a,
        d_vld_b,   d_vld_a,
        d_tick,
        d_seq_b, d_seq_a,
        d_status,
        8'hA5, 8'h55
    };

    // 帧 B：byte2 = 校准寄存器 0x88（cal_regs[7:0]），依次到 0x9F
    wire [207:0] payload_b;
    genvar gb;
    generate
        for (gb = 0; gb < 24; gb = gb + 1) begin : g_cal
            assign payload_b[16 + gb*8 +: 8] = d_bmp_cal[gb*8 +: 8];
        end
    endgenerate
    assign payload_b[7:0]   = 8'h55;
    assign payload_b[15:8]  = 8'hA6;

    // 下一个字节位于固定偏移，避免整个快照的可变宽多路选择。
    wire [7:0] nxt_byte = snap[15:8];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tx <= 1'b1; sending <= 1'b0; frm_b <= 1'b0; pend_a <= 1'b0;
            snap <= 608'd0; frm_tmr <= 32'd0;
            bidx <= 7'd0; bbit <= 4'd0; baud_cnt <= 32'd0;
            cur_byte <= 8'd0; xor_acc <= 8'd0;
            cal_div <= 4'd0; cal_due <= 1'b0; stop_pending<=0; guard_count<=0;
        end else begin
            if (!sending) begin
                tx <= 1'b1;                            // 空闲电平
                if (stop_pending) begin
                    if (guard_count==0) stop_pending<=0;
                    else guard_count<=guard_count-1'b1;
                end else if (ARBITRATION && holdoff) begin
                    // Pause only between complete frames, including final stop bit.
                end else if (pend_a) begin
                    // 帧 B 已上线，立即补发帧 A（保持 FRAME_MS 节奏）
                    pend_a   <= 1'b0;
                    snap     <= payload_a;
                    sending  <= 1'b1; frm_b <= 1'b0;
                    bidx <= 7'd0; bbit <= 4'd0; baud_cnt <= 32'd0;
                    cur_byte <= payload_a[7:0]; xor_acc <= 8'd0;
                end else if (frm_tmr >= FRAME_TICKS - 32'd1) begin
                    frm_tmr <= 32'd0;
                    if (cal_due && d_bmp_cal_vld) begin
                        // 低频校准帧：BMP absent 时跳过（无有效数据）
                        snap     <= {400'd0,payload_b};
                        sending  <= 1'b1; frm_b <= 1'b1;
                        bidx <= 7'd0; bbit <= 4'd0; baud_cnt <= 32'd0;
                        cur_byte <= payload_b[7:0]; xor_acc <= 8'd0;
                        pend_a   <= 1'b1;
                        cal_due  <= 1'b0; cal_div <= 4'd0;
                    end else begin
                        snap     <= payload_a;
                        sending  <= 1'b1; frm_b <= 1'b0;
                        bidx <= 7'd0; bbit <= 4'd0; baud_cnt <= 32'd0;
                        cur_byte <= payload_a[7:0]; xor_acc <= 8'd0;
                        if (cal_div >= CAL_DIV - 1) begin
                            cal_due <= 1'b1; cal_div <= 4'd0;
                        end else begin
                            cal_div <= cal_div + 4'd1;
                        end
                    end
                end else begin
                    frm_tmr <= frm_tmr + 32'd1;
                end
            end else if (baud_cnt >= BAUD_TICKS - 32'd1) begin
                baud_cnt <= 32'd0;
                if (bbit == 4'd0) begin                // start 位
                    tx <= 1'b0;
                    bbit <= 4'd1;
                end else if (bbit <= 4'd8) begin       // 数据位 LSB first
                    tx <= cur_byte[bbit - 4'd1];
                    bbit <= bbit + 4'd1;
                end else begin                         // stop 位，字节推进
                    tx <= 1'b1;
                    bbit <= 4'd0;
                    xor_acc <= xor_acc ^ cur_byte;
                    if (bidx == (frm_b ? NBYTES_B[6:0] : NBYTES_A[6:0]) - 7'd1) begin
                        sending <= 1'b0;               // 帧完成
                        if (ARBITRATION) begin stop_pending<=1;guard_count<=BAUD_TICKS-1'b1;end
                    end else begin
                        bidx <= bidx + 7'd1;
                        snap <= snap >> 8;
                        if (bidx == (frm_b ? NBYTES_B[6:0] : NBYTES_A[6:0]) - 7'd2)
                            cur_byte <= xor_acc ^ cur_byte;    // 校验字节
                        else
                            cur_byte <= nxt_byte;
                    end
                end
            end else begin
                baud_cnt <= baud_cnt + 32'd1;
            end
        end
    end
endmodule
