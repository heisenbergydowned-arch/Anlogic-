//============================================================================
// ds18b20.v — DS18B20 温度传感器 1-Wire 主控（纯硬件时序）
//
// 流程（每 PERIOD_MS 一次，周期含转换与协议段，从本轮启动到下轮启动）：
//   复位(500µs) → 存在检测(70µs采样) → 恢复(410µs)
//   → Skip ROM(0xCC) + Convert T(0x44) → 等转换(CONV_MS)
//   → 复位 → Skip ROM + Read Scratchpad(0xBE) → 读 9 字节（72bit）
//   → CRC8 校验通过 且 非 85°C 上电默认值(0x0550) → 更新 temperature + vld
//
// 位时隙：TX0 = 拉低 75µs；TX1 = 拉低 8µs + 释放 70µs；
//         读   = 拉低 2µs + 释放 8µs 采样（采样点 ≈10µs，留 5µs 余量）
//         + 补 60µs（总时隙 ≈70µs < 75µs 上限）。
// 容错：presence 无应答 → present=0，跳过本轮命令/读（不产生 vld）；
//       CRC 错 / 0x0550 → 本轮不 vld（旧值保持），下轮重测；
//       连续 3 帧无效（present 但 CRC/85°C 不合格）→ stale=1，
//       任意一帧有效即清零（"最近有效值已陈旧"告警标志，接 alarm）。
// 总线短路检测（v0.8）：DQ 对地短路/被器件拉死时，释放期总线恒 0，
//       presence 采样恒见"有器件"、9 字节读回全 0x00——Dallas CRC8
//       初值 0 喂 72 个 0 仍得 0，校验恰好通过，0x0000 会被当作
//       有效 0℃ 进入温控！两层防护：
//       ① S_RECOV 末尾"总线释放检查"——复位释放后 410µs，presence
//          脉冲（≤240µs）早已结束，总线必须回高；仍为低 = 短路，
//          本轮跳过命令/读（不产生 vld），present 压 0；
//       ② 每个命令/读取时隙结束后检查总线回高；未释放立即终止本轮，
//          present=0、bus_short=1，不允许部分有效位 + 后续恒 0 混成有效帧。
//       ③ S_DONE 拒绝全 0 scratchpad（真实器件包含固定非零字段），
//          保留合法 0℃；连续 3 次复位释放失败/全 0 帧判 bus_short。
//       bus_short 保持到一帧完整有效数据到来才清零，释放检查通过本身
//       不代表温度数据已恢复。stale 仍只表示 CRC/85℃ 坏帧。
// 周期实现：独立 cyc_us 从本轮启动（S_IDLE→S_RESET）计 µs，S_IDLE 等
//       cyc_us ≥ PERIOD_US 才开下一轮 → 整轮恰为 PERIOD_MS（协议段+
//       转换超出 PERIOD 时按实际时长执行，不截断协议时序）。
// DQ 开漏（外部 4.7kΩ 上拉到 3.3V），输入经 2FF 同步。
// 温度原始码 1/16°C/LSB（25°C = 0x0190），LSB 先发。
//============================================================================
module ds18b20 #(
    parameter CLK_FREQ  = 100_000_000,
    parameter CONV_MS   = 800,    // 转换等待（12 位最长 750ms）
    parameter PERIOD_MS = 1000    // 采样周期（含协议段与转换）
)(
    input  wire               clk,
    input  wire               rst_n,
    inout  wire               dq,
    output reg  signed [15:0] temperature,
    output reg               vld,
    output reg               present,
    output reg               stale,      // 1 = 连续 3 帧 CRC/85°C 无效（最近有效值已陈旧）
    output reg               bus_short   // 1 = 时隙未释放，或连续 3 次复位/全 0 帧故障
);
    //====================================================================
    // µs 时基
    //====================================================================
    localparam [19:0] US_DIV = CLK_FREQ / 1_000_000;
    reg [19:0] us_psc;
    reg        us_tick;
    reg [20:0] us_cnt;          // 通用 µs 计数（最长 ~2.1s）

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            us_psc  <= 20'd0;
            us_tick <= 1'b0;
        end else begin
            us_tick <= 1'b0;
            if (us_psc >= US_DIV - 20'd1) begin
                us_psc  <= 20'd0;
                us_tick <= 1'b1;
            end else begin
                us_psc  <= us_psc + 20'd1;
            end
        end
    end

    // 采样周期（µs）：从本轮启动到下轮启动
    localparam [20:0] PERIOD_US = PERIOD_MS * 1000;
    reg [20:0] cyc_us;    // 本轮已流逝 µs（S_IDLE 判周期；全 1 溢出放行防死锁）

    //====================================================================
    // DQ 开漏驱动 + 输入 2FF 同步
    //====================================================================
    reg  dq_drv;        // 位引擎拉低
    reg  dq_macro;      // 复位脉冲拉低（序列器驱动）

    assign dq = (dq_drv | dq_macro) ? 1'b0 : 1'bz;

    reg [1:0] dq_sync;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) dq_sync <= 2'b11;
        else        dq_sync <= {dq_sync[0], dq};
    end
    wire dq_in = dq_sync[1];

    //====================================================================
    // 位引擎：一次 TX0 / TX1 / 读时隙
    //====================================================================
    localparam [1:0] BOP_TX0 = 2'd0, BOP_TX1 = 2'd1, BOP_RD = 2'd2;
    localparam [1:0] BP_IDLE = 2'd0, BP_PULL = 2'd1, BP_SAMP = 2'd2, BP_REST = 2'd3;

    reg [1:0]  bop;
    reg [1:0]  bph;
    reg        bit_busy, bit_done, rd_bit, bit_fault;
    reg [6:0]  bit_t;           // 当前相位剩余 µs
    reg        bit_go;          // 1 clk 启动脉冲（序列器驱动）

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            bph <= BP_IDLE; bit_busy <= 1'b0; bit_done <= 1'b0;
            rd_bit <= 1'b0; bit_fault <= 1'b0; bit_t <= 7'd0; dq_drv <= 1'b0;
        end else begin
            bit_done <= 1'b0;
            if (bit_go) begin
                bit_fault<= 1'b0;
                bit_busy <= 1'b1;
                bph      <= BP_PULL;
                bit_t    <= (bop == BOP_TX0) ? 7'd75 :
                            (bop == BOP_TX1) ? 7'd8  : 7'd2;   // 读：2µs 拉低
                dq_drv   <= 1'b1;
            end else if (bit_busy && us_tick) begin
                if (bit_t != 7'd0) begin
                    bit_t <= bit_t - 7'd1;
                end else begin
                    case (bph)
                        BP_PULL: begin      // 拉低结束 → 释放
                            dq_drv <= 1'b0;
                            if (bop == BOP_RD) begin
                                bit_t <= 7'd8;               // 8µs 后采样（≈10µs 点）
                                bph   <= BP_SAMP;
                            end else begin
                                bit_t <= (bop == BOP_TX0) ? 7'd5 : 7'd70;
                                bph   <= BP_REST;
                            end
                        end
                        BP_SAMP: begin      // 释放后 8µs 采样
                            rd_bit   <= dq_in;    // 位值=总线电平：器件拉低=0，高=1
                            bit_t    <= 7'd60;    // 补完时隙（总 ≈70µs）
                            bph      <= BP_REST;
                        end
                        BP_REST: begin      // 时隙剩余
                            // TX0 已释放至少 5us，TX1/读时隙的从机低脉冲
                            // 也应结束。先锁存故障，再由序列器决定是否接收本位。
                            bit_fault<= ~dq_in;
                            bit_busy <= 1'b0;
                            bit_done <= 1'b1;
                        end
                        default: bit_busy <= 1'b0;
                    endcase
                end
            end
        end
    end

    //====================================================================
    // 字节序列器
    //====================================================================
    localparam [3:0]
        S_IDLE   = 4'd0,   // 等采样周期
        S_RESET  = 4'd1,   // 复位脉冲 500µs
        S_PRESMP = 4'd2,   // 释放后 70µs 采样存在
        S_RECOV  = 4'd3,   // 恢复 410µs
        S_CMDBIT = 4'd4,   // 命令位发送中（引擎忙）
        S_CMDNEXT= 4'd5,   // 发下一位/字节/段
        S_CONV   = 4'd6,   // 等温度转换
        S_RDBIT  = 4'd7,   // 读位中
        S_RDNEXT = 4'd8,   // 下一个读位
        S_DONE   = 4'd9;

    reg [3:0]  st;
    reg        seg_rd;      // 0 = Convert 段，1 = Read Scratchpad 段
    reg [1:0]  byte_idx;
    reg [2:0]  bit_idx;
    reg [6:0]  rd_cnt;      // 已读位 0..72（9 字节）
    reg [15:0] rd_shift;
    reg [15:0] temp_hold;   // 位 0..15（byte0/1 = 温度）收完即锁存；
                            // rd_shift 后续继续喂 CRC，S_DONE 时不再含温度
    reg [7:0]  crc8;        // Dallas CRC8（多项式 0x8C，初值 0，LSB first）
    reg [1:0]  bad_f;       // 连续无效帧计数（CRC/85°C，3 帧判 stale）
    reg [1:0]  bus_fail;    // 连续总线故障计数（释放检查失败/全 0 帧，3 次判 short）
    reg        nz_seen;     // 本读段见过非 0 位（合法 scratchpad 包含固定非零字段）

    function [7:0] cmd_byte;
        input        seg;
        input [1:0]  bidx;
        begin
            if (bidx == 2'd0)      cmd_byte = 8'hCC;
            else if (!seg)         cmd_byte = 8'h44;
            else                   cmd_byte = 8'hBE;
        end
    endfunction

    // 下一位的（字节，位号，位值）——组合计算，避免非阻塞旧值问题
    // 1-Wire 规定 LSB first：bit0 先发/先收
    wire        last_bit  = (bit_idx == 3'd7);
    wire        last_byte = (byte_idx == 2'd1);
    wire [2:0]  nbit      = last_bit ? 3'd0 : (bit_idx + 3'd1);
    wire [1:0]  nbyte     = (last_bit && !last_byte) ? (byte_idx + 2'd1) : byte_idx;
    wire [7:0]  ncmd      = cmd_byte(seg_rd, nbyte);
    wire        nbitv     = ncmd[nbit];
    wire [7:0]  cmd0      = cmd_byte(seg_rd, 2'd0);   // 每段首字节（0xCC）

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= S_IDLE; seg_rd <= 1'b0; byte_idx <= 2'd0; bit_idx <= 3'd0;
            rd_cnt <= 7'd0; rd_shift <= 16'd0; temp_hold <= 16'd0; crc8 <= 8'd0;
            bit_go <= 1'b0; bop <= BOP_TX0;
            us_cnt <= 21'd0; cyc_us <= 21'd0; dq_macro <= 1'b0;
            temperature <= 16'sd0; vld <= 1'b0; present <= 1'b0;
            stale <= 1'b0; bad_f <= 2'd0;
            bus_short <= 1'b0; bus_fail <= 2'd0; nz_seen <= 1'b0;
        end else begin
            bit_go <= 1'b0;
            vld    <= 1'b0;
            if (us_tick) begin
                us_cnt <= us_cnt + 21'd1;
                cyc_us <= cyc_us + 21'd1;
            end

            case (st)
            //--------------------------------------------------------
            S_IDLE: begin
                if (cyc_us >= PERIOD_US || &cyc_us) begin
                    cyc_us <= 21'd0;
                    us_cnt <= 21'd0;
                    seg_rd <= 1'b0;
                    st     <= S_RESET;
                end
            end
            S_RESET: begin
                dq_macro <= 1'b1;               // 复位脉冲（独立驱动器）
                if (us_cnt >= 21'd500) begin
                    dq_macro <= 1'b0;
                    us_cnt   <= 21'd0;
                    st       <= S_PRESMP;
                end
            end
            S_PRESMP: begin
                if (us_cnt >= 21'd70) begin
                    present <= ~dq_in;
                    us_cnt  <= 21'd0;
                    if (dq_in) begin            // 无 presence：跳过本轮命令/读
                        st <= S_IDLE;          // cyc_us 继续计满整周期
                    end else begin
                        st <= S_RECOV;
                    end
                end
            end
            S_RECOV: begin
                if (us_cnt >= 21'd410) begin
                    us_cnt <= 21'd0;
                    if (dq_in) begin        // 总线已回高：正常进入命令段
                        byte_idx <= 2'd0;
                        bit_idx  <= 3'd0;
                        bit_go   <= 1'b1;
                        bop      <= cmd0[0] ? BOP_TX1 : BOP_TX0;   // 第一位=bit0
                        st       <= S_CMDBIT;
                    end else begin          // 主机已释放 410µs 总线仍低：
                        present  <= 1'b0;   // 对地短路/器件拉死——presence
                        if (bus_fail != 2'd3)
                            bus_fail <= bus_fail + 2'd1;
                        if (bus_fail >= 2'd2)         // 命令/读全部跳过
                            bus_short <= 1'b1;
                        st <= S_IDLE;       // cyc_us 继续计满整周期
                    end
                end
            end
            //--------------------------------------------------------
            S_CMDBIT: begin                     // 引擎执行当前位
                if (bit_done) begin
                    if (bit_fault) begin
                        present   <= 1'b0;
                        bus_short <= 1'b1;
                        bus_fail  <= 2'd3;
                        st        <= S_IDLE;
                    end else st <= S_CMDNEXT;
                end
            end
            S_CMDNEXT: begin                    // 推进位/字节/段
                if (!last_bit || !last_byte) begin
                    bit_idx <= nbit;
                    byte_idx<= nbyte;
                    bit_go  <= 1'b1;
                    bop     <= nbitv ? BOP_TX1 : BOP_TX0;
                    st      <= S_CMDBIT;
                end else begin
                    // 16 个命令位发完
                    byte_idx <= 2'd0;
                    if (!seg_rd) begin
                        us_cnt <= 21'd0;
                        st     <= S_CONV;       // Convert T 已发
                    end else begin
                        rd_cnt  <= 7'd0;
                        rd_shift<= 16'd0;
                        crc8    <= 8'd00;
                        nz_seen <= 1'b0;    // 读段开始：清"见过非 0 位"
                        bit_go  <= 1'b1;
                        bop     <= BOP_RD;
                        st      <= S_RDBIT;
                    end
                end
            end
            //--------------------------------------------------------
            S_CONV: begin
                if (us_cnt >= CONV_MS * 1000) begin
                    us_cnt <= 21'd0;
                    seg_rd <= 1'b1;             // 下轮复位后进入读段
                    st     <= S_RESET;
                end
            end
            //--------------------------------------------------------
            S_RDBIT: begin
                if (bit_done) begin
                    if (bit_fault) begin
                        present   <= 1'b0;
                        bus_short <= 1'b1;
                        bus_fail  <= 2'd3;
                        st        <= S_IDLE;
                    end else begin
                    rd_shift <= {rd_bit, rd_shift[15:1]}; // LSB 先收：右移入低位
                    crc8     <= {1'b0, crc8[7:1]}         // Dallas CRC8 逐位
                              ^ ((rd_bit ^ crc8[0]) ? 8'h8C : 8'h00);
                    if (rd_bit) nz_seen <= 1'b1;          // 总线短路兜底：记录非 0 位
                    rd_cnt   <= rd_cnt + 7'd1;
                    if (rd_cnt == 7'd15)                    // 温度 16 位落位：
                        temp_hold <= {rd_bit, rd_shift[15:1]}; // 取本拍移位后的新值
                    st       <= S_RDNEXT;
                    end
                end
            end
            S_RDNEXT: begin
                if (rd_cnt == 7'd72) begin
                    st <= S_DONE;
                end else begin
                    bit_go <= 1'b1;
                    bop    <= BOP_RD;
                    st     <= S_RDBIT;
                end
            end
            //--------------------------------------------------------
            S_DONE: begin
                // 9 字节（含 CRC）全喂入后 crc8==0 表示校验通过；
                // 0x0550 = 器件上电默认值（85°C），视为无效帧
                if (!dq_in) begin
                    present   <= 1'b0;
                    bus_short <= 1'b1;
                    bus_fail  <= 2'd3;
                end else if (crc8 == 8'h00 && temp_hold != 16'h0550 && nz_seen) begin
                    temperature <= temp_hold;
                    vld         <= 1'b1;
                    stale       <= 1'b0;
                    bad_f       <= 2'd0;
                    bus_fail    <= 2'd0;
                    bus_short   <= 1'b0;
                end else if (!nz_seen) begin
                    // 全 0 帧：CRC 初值 0 喂 72 个 0 恰好"通过"——总线读段
                    // 恒 0（短路/拉死），合法 scratchpad 包含固定非零字段。
                    // 拒绝并按总线故障计（不得把 0x0000 当有效 0℃ 进温控）
                    present  <= 1'b0;
                    if (bus_fail != 2'd3)
                        bus_fail <= bus_fail + 2'd1;
                    if (bus_fail >= 2'd2)
                        bus_short <= 1'b1;
                end else begin
                    bus_fail <= 2'd0;          // 总线正常，计数仅累计连续总线坏帧
                    if (bad_f == 2'd2) begin    // 连续 3 帧无效 → 数据陈旧
                        stale <= 1'b1;
                        bad_f <= 2'd0;
                    end else begin
                        bad_f <= bad_f + 2'd1;
                    end
                end
                st <= S_IDLE;                  // cyc_us 计满整周期
            end
            default: st <= S_IDLE;
            endcase
        end
    end

endmodule
