//============================================================================
// bmp280_model.v — BMP280 气压传感器 I2C 行为模型（仿真用）
//
// 地址 0x76（SDO=GND）。256 字节寄存器空间：
//   0xD0 = chip id（chip_id_in，期望 0x58）
//   0x88..0x9F = 24 字节校准参数（cal_in 小端打包，初始化时装载）
//   0xF4 写非零（强制模式 0x25）→ MEAS_MS 后 0xF7..0xFC 更新为 p_raw_in/t_raw_in
//   0xF7..0xFC = 压力/温度原始值（读自动递增）
// present=0 时不应答任何地址（模拟掉线）。
//============================================================================
`timescale 1ns/1ps
module bmp280_model #(
    parameter [6:0]   ADDR7    = 7'h76,
    parameter integer MEAS_MS  = 6,
    parameter [7:0]   CHIP_ID  = 8'h58
)(
    inout  wire        sda,
    inout  wire        scl,
    input  wire        present,
    input  wire [191:0] cal_in,     // T1,T2,T3,P1..P9（各 16bit 小端）
    input  wire [19:0] t_raw_in,
    input  wire [19:0] p_raw_in
);
    //--------------------------------------------------------------------
    // 寄存器空间
    //--------------------------------------------------------------------
    reg [7:0] mem [0:255];
    integer i;
    initial begin
        for (i = 0; i < 256; i = i + 1) mem[i] = 8'h00;
        mem[8'hD0] = CHIP_ID;
        #1;                                // 等 tb 对 cal_in 的连续赋值传播（0 时刻采样会读到 Z）
        for (i = 0; i < 24; i = i + 1)
            mem[8'h88 + i] = cal_in[i * 8 +: 8];
        mem[8'hF7] = 8'h00; mem[8'hF8] = 8'h00; mem[8'hF9] = 8'h00;
        mem[8'hFA] = 8'h00; mem[8'hFB] = 8'h00; mem[8'hFC] = 8'h00;
    end

    event meas_ev;

    //--------------------------------------------------------------------
    // I2C 位引擎（与 aht20_model 同套路）
    //--------------------------------------------------------------------
    reg sda_en = 1'b0, sda_bit = 1'b0;
    assign sda = sda_en ? sda_bit : 1'bz;

    reg        started = 1'b0;
    reg        sda_prev = 1'b1;
    reg [3:0]  bitn = 4'd0;
    reg [7:0]  rxsh = 8'd0;
    reg [7:0]  txsh = 8'd0;
    reg        addr_seen = 1'b0, addr_ok = 1'b0, rw_r = 1'b0, reading = 1'b0;
    reg [7:0]  ptr = 8'd0;         // 寄存器指针（写段设置，读段自动递增）
    reg        ptr_seen = 1'b0;
    reg        mack = 1'b0;
    reg        match;
    reg [7:0]  nb;

    always @(sda) begin
        if (scl === 1'b1) begin
            if (sda === 1'b0 && sda_prev === 1'b1) begin      // START / RESTART
                started   <= 1'b1;
                bitn      <= 4'd0;
                addr_seen <= 1'b0;
            end
            if (sda === 1'b1 && sda_prev === 1'b0) begin      // STOP
                started  <= 1'b0;
                reading  <= 1'b0;
                ptr_seen <= 1'b0;                             // 新事务重置指针
                sda_en   <= 1'b0;
            end
        end
        sda_prev <= sda;
    end

    always @(posedge scl) begin
        if (started) begin
            if (bitn < 4'd8) rxsh <= {rxsh[6:0], sda};
            if (bitn == 4'd8) mack <= (sda === 1'b0);
            bitn <= (bitn == 4'd8) ? 4'd0 : bitn + 4'd1;
        end
    end

    always @(negedge scl) begin
        if (started) begin
            if (bitn == 4'd8) begin
                if (reading) begin
                    sda_en <= 1'b0;
                end else begin
                    match = (rxsh[7:1] == ADDR7) && present;
                    if (!addr_seen) begin
                        addr_seen <= 1'b1;
                        addr_ok   <= match;
                        rw_r      <= rxsh[0];
                    end else if (addr_ok && !rw_r) begin      // 写数据字节
                        if (!ptr_seen) begin
                            ptr      <= rxsh;                 // 首字节 = 子地址
                            ptr_seen <= 1'b1;
                        end else begin
                            if (ptr == 8'hF4 && rxsh != 8'h00)
                                -> meas_ev;                   // 强制模式触发
                            if (ptr >= 8'h88 && ptr <= 8'hF5)
                                mem[ptr] <= rxsh;             // 可写窗口
                            ptr <= ptr + 8'd1;
                        end
                    end
                    if (addr_seen ? addr_ok : match) begin
                        sda_en <= 1'b1; sda_bit <= 1'b0;
                    end else begin
                        sda_en <= 1'b0;
                    end
                end
            end else if (bitn == 4'd0 && addr_seen) begin  // ACK 钟后；START 后首个负沿 addr_seen=0 跳过
                if (reading) begin
                    if (mack) begin
                        nb = mem[ptr];
                        txsh <= nb; sda_bit <= nb[7]; sda_en <= 1'b1;
                        ptr <= ptr + 8'd1;
                    end else begin
                        sda_en <= 1'b0; reading <= 1'b0;
                    end
                end else if (addr_ok && rw_r) begin
                    reading <= 1'b1;
                    nb = mem[ptr];
                    txsh <= nb; sda_bit <= nb[7]; sda_en <= 1'b1;
                    ptr <= ptr + 8'd1;
                end else begin
                    sda_en <= 1'b0;
                end
            end else if (reading) begin                   // 数据位换位（bitn 1..7）
                sda_bit <= txsh[6];
                txsh    <= {txsh[6:0], 1'b0};
            end
        end
    end

    //--------------------------------------------------------------------
    // 强制模式转换（行为级延时）
    //--------------------------------------------------------------------
    always @(meas_ev) begin
        #(MEAS_MS * 1_000_000);
        mem[8'hF7] = p_raw_in[19:12];
        mem[8'hF8] = p_raw_in[11:4];
        mem[8'hF9] = {p_raw_in[3:0], 4'b0000};
        mem[8'hFA] = t_raw_in[19:12];
        mem[8'hFB] = t_raw_in[11:4];
        mem[8'hFC] = {t_raw_in[3:0], 4'b0000};
    end
endmodule
