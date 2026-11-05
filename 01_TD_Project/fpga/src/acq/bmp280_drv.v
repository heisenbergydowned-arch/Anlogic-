//============================================================================
// bmp280_drv.v — BMP280 大气压传感器驱动（经 i2c_master，强制模式）
//
// 初始化：读 chip id（0xD0，期望 0x58）→ 读 24 字节校准参数（0x88..0x9F，
//   小端，拼成 12 个 16bit 字输出给 PS 侧做 Bosch 补偿）
//   → 写 config(0xF5)=0x00（IIR off，spi3w off）
//   → 写 ctrl_meas(0xF4)=0x25（osrs 1×/1×，强制模式触发一次转换）。
// 测量（每 PERIOD_MS）：写 0xF4=0x25 触发 → 等 MEAS_MS
//   → 读 0xF7..0xFC 6 字节 → 20bit 压力/温度原始码。
// PL 只出原始值 + 校准字； Bosch 补偿（整数或浮点）放 PS/NPU 侧算。
// 容错：无应答 → err 置位且清 present（下轮重查 id+校准，防断电重插
//   后读到未校准数据）；id 不符 → err + 周期重试；好帧自动清 err。
// busy=1 期间占用 I2C 仲裁（top 层总线所有权依据）。
//============================================================================
module bmp280_drv #(
    parameter CLK_FREQ  = 100_000_000,
    parameter PERIOD_MS = 1000,          // 测量周期（1Hz）
    parameter MEAS_MS   = 10,            // 强制模式转换等待（1×/1× 约 6.4ms）
    parameter ADDR7     = 7'h76          // SDO=GND；模块丝印 0x77 时改此参数
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
    output reg  [7:0]  chip_id,          // 读回的器件 ID（期望 0x58）
    output reg  [191:0] cal_regs,        // T1,T2,T3,P1..P9（各 16bit，低位在前）
    output reg  [19:0] t_raw,            // 温度原始码（20bit，Q20.4）
    output reg  [19:0] p_raw,            // 压力原始码（20bit，Q20.4）
    output reg         present,          // id 校验通过
    output reg         err,
    output reg         sample_valid
);
    localparam [31:0] T_POR    = CLK_FREQ/1000 * 3;      // 上电 3ms
    localparam [31:0] T_PERIOD = CLK_FREQ/1000 * PERIOD_MS;
    localparam [31:0] T_MEAS   = CLK_FREQ/1000 * MEAS_MS;

    assign i2c_dev = ADDR7;

    localparam [3:0] S_POR=4'd0, S_ID=4'd1, S_CAL=4'd2, S_CFG5=4'd3,
                     S_CFG=4'd4, S_IDLE=4'd5, S_TRIG=4'd6,
                     S_MEAS=4'd7, S_RD=4'd8;

    reg [3:0]  st;
    reg [31:0] tmr;
    reg [7:0]  b0, b1, b2, b3, b4, b5;   // 读回缓存

    // 读字节捕获（b0-b5/cal_regs 唯一驱动块）
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            b0 <= 8'd0; b1 <= 8'd0; b2 <= 8'd0; b3 <= 8'd0; b4 <= 8'd0; b5 <= 8'd0;
            cal_regs <= 192'd0;
        end else if (i2c_rd_valid) begin
            case (st)
            S_ID:  b0 <= i2c_rd_data;
            S_CAL: cal_regs[i2c_rd_idx * 8 +: 8] <= i2c_rd_data;  // 24 字节校准
            S_RD:  case (i2c_rd_idx)
                       5'd0: b0 <= i2c_rd_data;   // 0xF7 压力 MSB
                       5'd1: b1 <= i2c_rd_data;   // 0xF8
                       5'd2: b2 <= i2c_rd_data;   // 0xF9
                       5'd3: b3 <= i2c_rd_data;   // 0xFA 温度 MSB
                       5'd4: b4 <= i2c_rd_data;   // 0xFB
                       5'd5: b5 <= i2c_rd_data;   // 0xFC
                       default: ;
                   endcase
            default: ;
            endcase
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= S_POR; tmr <= T_POR;
            i2c_req <= 1'b0; i2c_nwr <= 3'd0; i2c_nrd <= 5'd0;
            i2c_wr0 <= 8'd0; i2c_wr1 <= 8'd0; i2c_wr2 <= 8'd0;
            busy <= 1'b0; present <= 1'b0; err <= 1'b0;
            chip_id <= 8'd0;
            t_raw <= 20'd0; p_raw <= 20'd0;
            sample_valid <= 1'b0;
        end else begin
            sample_valid <= 1'b0;
            case (st)
            //--------------------------------------------------------------
            S_POR: begin
                if (tmr == 32'd0) st <= S_ID;
                else tmr <= tmr - 32'd1;
            end
            //--------------------------------------------------------------
            S_ID: begin                                       // 读 0xD0
                i2c_req <= 1'b1; i2c_nwr <= 3'd1; i2c_nrd <= 5'd1;
                i2c_wr0 <= 8'hD0;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err <= 1'b1;
                        st <= S_IDLE; tmr <= T_PERIOD;         // 周期重试
                    end else begin
                        chip_id <= b0;
                        if (b0 == 8'h58) begin
                            present <= 1'b1;
                            st <= S_CAL;
                        end else begin
                            err <= 1'b1;                       // 器件不符
                            st <= S_IDLE; tmr <= T_PERIOD;
                        end
                    end
                end
            end
            //--------------------------------------------------------------
            S_CAL: begin                                      // 读 24 字节校准
                i2c_req <= 1'b1; i2c_nwr <= 3'd1; i2c_nrd <= 5'd24;
                i2c_wr0 <= 8'h88;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err <= 1'b1; present <= 1'b0;          // 下轮重查
                        st <= S_IDLE; tmr <= T_PERIOD;
                    end else begin
                        st <= S_CFG5;
                    end
                end
            end
            //--------------------------------------------------------------
            S_CFG5: begin                                     // 写 0xF5=0x00
                i2c_req <= 1'b1; i2c_nwr <= 3'd2; i2c_nrd <= 5'd0;
                i2c_wr0 <= 8'hF5; i2c_wr1 <= 8'h00;            // IIR off, spi3w off
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err <= 1'b1; present <= 1'b0;
                        st <= S_IDLE; tmr <= T_PERIOD;
                    end else begin
                        st <= S_CFG;
                    end
                end
            end
            //--------------------------------------------------------------
            S_CFG: begin                                      // 写 0xF4=0x25
                i2c_req <= 1'b1; i2c_nwr <= 3'd2; i2c_nrd <= 5'd0;
                i2c_wr0 <= 8'hF4; i2c_wr1 <= 8'h25;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err <= 1'b1; present <= 1'b0;
                        st <= S_IDLE; tmr <= T_PERIOD;
                    end else begin
                        st <= S_IDLE; tmr <= 32'd0;             // 首帧立即
                    end
                end
            end
            //--------------------------------------------------------------
            S_IDLE: begin
                if (tmr == 32'd0) st <= present ? S_TRIG : S_ID;
                else tmr <= tmr - 32'd1;
            end
            //--------------------------------------------------------------
            S_TRIG: begin                                     // 强制模式触发
                busy <= 1'b1;
                i2c_req <= 1'b1; i2c_nwr <= 3'd2; i2c_nrd <= 5'd0;
                i2c_wr0 <= 8'hF4; i2c_wr1 <= 8'h25;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err <= 1'b1; present <= 1'b0;          // 下轮重查 id+校准
                        busy <= 1'b0;
                        st <= S_IDLE; tmr <= T_PERIOD;
                    end else begin
                        st <= S_MEAS; tmr <= T_MEAS;
                    end
                end
            end
            S_MEAS: begin
                if (tmr == 32'd0) st <= S_RD;
                else tmr <= tmr - 32'd1;
            end
            //--------------------------------------------------------------
            S_RD: begin                                       // 读 6 字节
                i2c_req <= 1'b1; i2c_nwr <= 3'd1; i2c_nrd <= 5'd6;
                i2c_wr0 <= 8'hF7;
                if (i2c_ack) begin
                    i2c_req <= 1'b0;
                    if (i2c_err) begin
                        err <= 1'b1; present <= 1'b0;          // 下轮重查 id+校准
                        busy <= 1'b0;
                        st <= S_IDLE; tmr <= T_PERIOD;
                    end else begin
                        sample_valid <= 1'b1;
                        p_raw <= {b0, b1, b2[7:4]};            // 20bit 压力
                        t_raw <= {b3, b4, b5[7:4]};            // 20bit 温度
                        err <= 1'b0; busy <= 1'b0;
                        st <= S_IDLE; tmr <= T_PERIOD;
                    end
                end
            end
            //--------------------------------------------------------------
            default: st <= S_POR;
            endcase
        end
    end
endmodule
