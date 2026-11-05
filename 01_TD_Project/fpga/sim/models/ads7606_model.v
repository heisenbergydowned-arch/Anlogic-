//============================================================================
// ads7606_model.v — AD7606 串行接口行为模型（仅仿真，单线 DOUTA 模式）
//
// 行为（对齐 AD7606 数据手册 Rev G 串行时序）：
//   CONVST↑ → BUSY 拉高（t_BUSY 25ns）→ tCONV 后拉低，8 通道同时"转换完成"，
//             结果寄存器锁存 ch1..ch8_code；
//   CS↓  → DOUTA 退出三态、驱动 V1 的 MSB，FRSTDATA 拉高；
//   SCLK↑ → 驱动下一位（MSB first，V1→V8 共 128 位）；
//   第 16 个 SCLK↓ → FRSTDATA 拉低（V1 读毕）。
//
// 故障注入（tb 激励）：
//   en=0        器件不在位：BUSY 恒低（主机应在超时后置 err 跳帧）
//   frst_mode=1 FRSTDATA 恒低（主机 bit0 相位校验应报错）
//   frst_mode=2 FRSTDATA 恒高（主机 bit17 相位校验应报错）
//
// 不建模：过采样（板级 OS=000 硬连）、并行模式、转换期间读数。
//============================================================================
`timescale 1ns/1ps
module ads7606_model #(
    parameter integer TCONV_NS = 4_150    // 转换时间（手册 max ≈4.15µs）
)(
    input  wire        convst,
    input  wire        reset,
    output reg         busy,
    input  wire        sclk,
    input  wire        cs_n,
    output wire        douta,
    output reg         frstdata,
    input  wire [15:0] ch1_code,    // 各通道转换结果，tb 提供
    input  wire [15:0] ch2_code,
    input  wire [15:0] ch3_code,
    input  wire [15:0] ch4_code,
    input  wire [15:0] ch5_code,
    input  wire [15:0] ch6_code,
    input  wire [15:0] ch7_code,
    input  wire [15:0] ch8_code,
    input  wire        en,          // 1=器件在位
    input  wire [1:0]  frst_mode    // 0=正常 1=恒低 2=恒高
);
    reg [127:0] result;    // 最近一次完成的转换结果 {V1..V8}
    reg [127:0] shifter;   // 读数移位寄存器
    reg [7:0]   rd_idx;    // 已驱动的最高位序号（0..127）
    reg [8:0]   fall_cnt;  // SCLK 下降沿计数（FRSTDATA 相位用）
    reg         douta_drv;
    reg         reset_valid = 1'b0;
    integer     reset_generation = 0;
    integer     conversion_generation;
    realtime    reset_started = 0.0;

    assign douta = !cs_n && en && !reset && reset_valid ? douta_drv : 1'bz;

    initial begin
        busy = 1'b0; frstdata = 1'b0;
        result = 128'h0; shifter = 128'h0;
        rd_idx = 8'd0; fall_cnt = 9'd0; douta_drv = 1'b0;
    end

    always @(posedge reset) begin
        reset_started = $realtime;
        reset_valid = 1'b0;
        reset_generation = reset_generation + 1;
        busy = 1'b0;
        frstdata = 1'b0;
        result = 0;
        shifter = 0;
        rd_idx = 0;
        fall_cnt = 0;
        douta_drv = 0;
    end

    always @(negedge reset) begin
        if ($realtime - reset_started >= 50.0)
            reset_valid = 1'b1;
    end

    always @(negedge en) begin
        reset_generation = reset_generation + 1;
        busy = 1'b0;
    end

    always @(posedge convst) begin
        if (en && !reset && reset_valid) begin
            conversion_generation = reset_generation;
            #25;
            if (en && !reset && conversion_generation == reset_generation)
                busy = 1'b1;
            #(TCONV_NS - 25);
            if (en && !reset && conversion_generation == reset_generation) begin
                result = {ch1_code, ch2_code, ch3_code, ch4_code,
                          ch5_code, ch6_code, ch7_code, ch8_code};
                busy = 1'b0;
            end
        end
    end

    // 读窗口开启：装载 128 位，驱动 V1 的 MSB，FRSTDATA↑
    always @(negedge cs_n) begin
        if (en && !reset && reset_valid) begin
        shifter   = result;
        rd_idx    = 8'd0;
        fall_cnt  = 9'd0;
        douta_drv = shifter[127];
        frstdata  = (frst_mode == 2'd1) ? 1'b0 : 1'b1;
        end
    end

    // SCLK 上升沿：驱动下一位
    always @(posedge sclk) begin
        if (!cs_n && en && !reset && reset_valid && rd_idx < 8'd127) begin
            rd_idx    = rd_idx + 8'd1;
            douta_drv = shifter[127 - rd_idx];
        end
    end

    // SCLK 下降沿：FRSTDATA 在第 16 个下降沿拉低（V1 读毕）
    always @(negedge sclk) begin
        if (!cs_n && en && !reset && reset_valid) begin
            fall_cnt = fall_cnt + 9'd1;
            if (fall_cnt == 9'd16 && frst_mode == 2'd0)
                frstdata = 1'b0;
        end
    end

endmodule
