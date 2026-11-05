//============================================================================
// aht20_drv.v — AHT20 温湿度传感器驱动（经 i2c_master，地址 0x38）
//
// 流程：上电等待 40ms → 读状态（校准位[3]；未校准则发 0xBE 08 00 初始化）
//   → 每 PERIOD_MS：触发测量（写 0xAC 33 00）→ 等 MEAS_MS（典型 80ms）
//   → 读 7 字节（状态 + 6 数据 + CRC）→ CRC8 校验 → 拼出 20bit 湿度/温度原始码
// 换算（PS 侧或上位机）：RH = hum_code/2^20 ×100 %；T = temp_code/2^20 ×200-50 °C
// CRC：AHT20 数据手册——初值 0xFF、多项式 0x31（x^8+x^5+x^4+1）、MSB first，
//       覆盖字节 0..5（状态+湿 2.5 字节+温 2.5 字节），第 7 字节比对；
//       CRC 错 → 本帧不更新数据（旧值保持）、err 置位，下轮重测。
// 容错：器件无应答/超时 → err 黏性置位（好帧自动清零），不阻塞系统；
//       读回时状态 busy 位仍置 → 5ms 后重读（最多 4 次）。
// busy=1 期间占用 I2C 仲裁（top 层总线所有权依据）。
//============================================================================
module aht20_drv #(
    parameter CLK_FREQ  = 100_000_000,
    parameter PERIOD_MS = 1000,          // 测量周期（1Hz）
    parameter MEAS_MS   = 80             // 触发后等待
)(
    input  wire        clk,
    input  wire        rst_n,

    // I2C 服务接口（top 层仲裁复用后接 i2c_master）
    output reg         i2c_req,
    output wire [6:0]  i2c_dev,
    output reg  [2:0]  i2c_nwr,
    output reg  [7:0]  i2c_wr0,
    output reg  [7:0]  i2c_wr1,
    output reg  [7:0]  i2c_wr2,
    output reg  [4:0]  i2c_nrd,
    input  wire        i2c_ack,
    input  wire        i2c_err,
    input  wire        i2c_rd_valid,
    input  wire [7:0]  i2c_rd_data,
    input  wire [4:0]  i2c_rd_idx,

    output reg         busy,             // 一个测量周期进行中（含等待）
    output reg  [19:0] hum_code,         // 湿度原始码（20bit）
    output reg  [19:0] temp_code,        // 温度原始码（20bit）
    output reg         present,          // 曾成功通信（在线）
    output reg         err,
    output reg         sample_valid
);
    localparam [31:0] T_POR    = CLK_FREQ/1000 * 40;     // 40ms 上电稳定
    localparam [31:0] T_PERIOD = CLK_FREQ/1000 * PERIOD_MS;
    localparam [31:0] T_MEAS   = CLK_FREQ/1000 * MEAS_MS;
    localparam [31:0] T_INIT   = CLK_FREQ/1000 * 10;     // 初始化命令后 10ms
    localparam [31:0] T_RETRY  = CLK_FREQ/1000 * 5;      // busy 重读间隔 5ms

    assign i2c_dev = 7'h38;

    localparam [3:0] S_POR=4'd0, S_CHK=4'd1, S_INIT=4'd2, S_INIT_W=4'd3,
                     S_IDLE=4'd4, S_TRIG=4'd5, S_MEAS=4'd6,
                     S_RD=4'd7, S_RD_W=4'd8;

    reg [3:0]  st;
    reg [31:0] tmr;
    reg [1:0]  retry;
    reg [7:0]  b0, b1, b2, b3, b4, b5, b6;  // 读回缓存（b6 = CRC 字节）

    // 读字节捕获（事务期间 u_rd_valid 逐字节到来）
    always @(posedge clk) begin
        if (i2c_rd_valid) begin
            case (i2c_rd_idx)
                5'd0: b0 <= i2c_rd_data;
                5'd1: b1 <= i2c_rd_data;
                5'd2: b2 <= i2c_rd_data;
                5'd3: b3 <= i2c_rd_data;
                5'd4: b4 <= i2c_rd_data;
                5'd5: b5 <= i2c_rd_data;
                5'd6: b6 <= i2c_rd_data;
                default: ;
            endcase
        end
    end

    // AHT20 CRC8：初值 0xFF、多项式 0x31、MSB first，覆盖字节 0..5
    function [7:0] crc8_aht;
        input [47:0] msg;
        reg   [7:0] c;
        integer     byi, bi;
        begin
            c = 8'hFF;
            for (byi = 0; byi < 6; byi = byi + 1) begin
                c = c ^ msg[47 - byi*8 -: 8];
                for (bi = 0; bi < 8; bi = bi + 1)
                    c = c[7] ? ((c << 1) ^ 8'h31) : (c << 1);
            end
            crc8_aht = c;
        end
    endfunction

    wire [7:0] crc_calc = crc8_aht({b0, b1, b2, b3, b4, b5});

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= S_POR; tmr <= T_POR; retry <= 2'd0;
            i2c_req <= 1'b0; i2c_nwr <= 3'd0; i2c_nrd <= 5'd0;
            i2c_wr0 <= 8'd0; i2c_wr1 <= 8'd0; i2c_wr2 <= 8'd0;
            busy <= 1'b0; present <= 1'b0; err <= 1'b0;
            hum_code <= 20'd0; temp_code <= 20'd0;
            sample_valid <= 1'b0;
        end else begin
            sample_valid <= 1'b0;
            case (st)
            //--------------------------------------------------------------
            S_POR: begin
                if (tmr == 32'd0) st <= S_CHK;
                else tmr <= tmr - 32'd1;
            end
            //--------------------------------------------------------------
            S_CHK: begin                                       // 读 1 字节状态
                i2c_req <= 1'b1; i2c_nwr <= 3'd0; i2c_nrd <= 5'd1;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err <= 1'b1;                           // 不在线
                        st <= S_IDLE; tmr <= T_PERIOD;
                    end else begin
                        present <= 1'b1;
                        if (!b0[3]) begin                      // 未校准 → 初始化
                            st <= S_INIT;
                        end else begin
                            st <= S_IDLE; tmr <= 32'd0;        // 首帧立即
                        end
                    end
                end
            end
            //--------------------------------------------------------------
            S_INIT: begin                                      // 写 BE 08 00
                i2c_req <= 1'b1; i2c_nwr <= 3'd3; i2c_nrd <= 5'd0;
                i2c_wr0 <= 8'hBE; i2c_wr1 <= 8'h08; i2c_wr2 <= 8'h00;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err <= 1'b1; present <= 1'b0;      // 掉线：下轮重查
                        st <= S_IDLE; tmr <= T_PERIOD;
                    end else begin
                        st <= S_INIT_W; tmr <= T_INIT;
                    end
                end
            end
            S_INIT_W: begin
                if (tmr == 32'd0) st <= S_CHK;
                else tmr <= tmr - 32'd1;
            end
            //--------------------------------------------------------------
            S_IDLE: begin
                if (tmr == 32'd0) st <= present ? S_TRIG : S_CHK;
                else tmr <= tmr - 32'd1;
            end
            //--------------------------------------------------------------
            S_TRIG: begin                                      // 写 AC 33 00
                busy <= 1'b1;
                i2c_req <= 1'b1; i2c_nwr <= 3'd3; i2c_nrd <= 5'd0;
                i2c_wr0 <= 8'hAC; i2c_wr1 <= 8'h33; i2c_wr2 <= 8'h00;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err <= 1'b1; present <= 1'b0;      // 掉线：下轮重查校准位
                        busy <= 1'b0;
                        st <= S_IDLE; tmr <= T_PERIOD;
                    end else begin
                        st <= S_MEAS; tmr <= T_MEAS;
                    end
                end
            end
            S_MEAS: begin
                if (tmr == 32'd0) begin st <= S_RD; retry <= 2'd0; end
                else tmr <= tmr - 32'd1;
            end
            //--------------------------------------------------------------
            S_RD: begin                                        // 读 7 字节
                i2c_req <= 1'b1; i2c_nwr <= 3'd0; i2c_nrd <= 5'd7;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err <= 1'b1; present <= 1'b0;      // 掉线：下轮重查校准位
                        busy <= 1'b0;
                        st <= S_IDLE; tmr <= T_PERIOD;
                    end else if (b0[7]) begin                  // 仍在测量 → 重读
                        if (retry == 2'd3) begin
                            err <= 1'b1; busy <= 1'b0; retry <= 2'd0;
                            st <= S_IDLE; tmr <= T_PERIOD;
                        end else begin
                            retry <= retry + 2'd1;
                            st <= S_RD_W; tmr <= T_RETRY;
                        end
                    end else if (b6 != crc_calc || !b0[3]) begin
                        if (!b0[3]) present <= 1'b0;
                        err  <= 1'b1;                           // CRC 坏帧：不更新数据
                        busy <= 1'b0; retry <= 2'd0;
                        st <= S_IDLE; tmr <= T_PERIOD;
                    end else begin
                        hum_code  <= {b1, b2, b3[7:4]};        // 20bit 湿度
                        temp_code <= {b3[3:0], b4, b5};        // 20bit 温度
                        sample_valid <= 1'b1;
                        err <= 1'b0; busy <= 1'b0; retry <= 2'd0;
                        st <= S_IDLE; tmr <= T_PERIOD;
                    end
                end
            end
            S_RD_W: begin
                if (tmr == 32'd0) st <= S_RD;
                else tmr <= tmr - 32'd1;
            end
            //--------------------------------------------------------------
            default: st <= S_POR;
            endcase
        end
    end
endmodule
