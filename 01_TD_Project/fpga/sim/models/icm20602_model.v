//============================================================================
// icm20602_model.v — ICM-20602 SPI 从机行为模型（仅仿真）
//
// SPI Mode0：SCLK 上升沿采样 MOSI；下降沿更新 MISO。
// 支持单字节读/写 + 突发读（地址自增）。
// 复位行为不模拟（写 PWR_MGMT_1=0x80 仅记录，不回退寄存器）。
//
// ODR 自由采样：按 ODR_HZ 用内部时钟独立生成样本，与 FPGA 采样节拍无关，
//   复现真实器件"1kHz 节拍 vs ODR 频差 → 周期性重复读/丢拍"。
//   t=0 预置样本 0；温度寄存器对(0x41/0x42)携带样本序号（TB 据此验证
//   DRDY 门控是否恰好每 vld 消费一个新样本），其余字节保持 DATA_BASE+i
//   固定样式（TB 校验突发通路与字节序）。
// DRDY 消费语义（ICM-20602 手册，已核实）：INT_STATUS(0x3A) bit0 新样本
//   落地置 1；INT_PIN_CFG.INT_RD_CLEAR 默认 0 —— 仅读 INT_STATUS(0x3A)
//   寄存器清零，读数据寄存器(0x3B..0x48)不影响 DRDY。
//   （早期版本误实现为"读任一数据寄存器清零"，对应错误的死窗丢样机理，
//    已废弃——如需复现该行为须改写 INT_PIN_CFG 的 INT_RD_CLEAR=1。）
// 样本装载冻结：CS 有效期间延迟 load_sample（DRDY 与数据一同冻结），
//   把"突发读撕裂帧"（真实器件存在、手册不保证突发读原子性，概率性
//   字节新旧混合，留待台架实测）与"丢样"解耦——TB 据此可对零丢样
//   做 dup==0 / jump==0 的精确断言，撕裂帧不产生计数噪声。
// FROZEN=1（负向注入）：样本字节恒定（sample_id 不递增）、DRDY 仍按
//   ODR 置位——仿真实器件"数据寄存器冻结但仍报新数据"故障，供 TB
//   验证 sns_sync 的 dup_a/b_cnt 能检出重复消费（每 vld 计一次，首样本除外）。
// halt（运行时注入，v0.8）：内部采样时钟停摆——ODR 进程挂起、不再装载
//   新样本（DRDY 恒 0、数据字节保持陈旧值），SPI 应答一切正常（WHO_AM_I
//   照常回读）。复现"器件在线但停止产生新数据"，供 TB 验证 sns_sync 的
//   有效样本超时监控（SAMPLE_TIMEOUT_MS → err 置位 + 周期重试自愈）。
//============================================================================
`timescale 1ns/1ps
module icm20602_model #(
    parameter [7:0]   WHO_ID    = 8'h12,  // WHO_AM_I 应答值
    parameter [7:0]   DATA_BASE = 8'h01,  // 0x3B 起的突发读数据基值
    parameter integer ODR_HZ    = 1000,  // 内部 ODR（自由时钟；偏离节拍可看频差效应）
    parameter [7:0] IGNORE_WRITE_ADDR = 8'hff, // readback fault injection
    parameter integer FROZEN    = 0     // 1=输出冻结（负向注入，见头注释）
)(
    input  wire sclk,
    input  wire mosi,
    output wire miso,
    input  wire cs_n,
    input  wire halt       // 1=采样停摆（运行时注入；未连接时为 z，=== 1'b1 判定不受影响）
);
    reg [7:0] regs [0:127];
    reg       drdy_r = 1'b1;               // INT_STATUS bit0：RAW_DATA_0_RDY

    // 寄存器读复用：0x3A 返回 DRDY 状态位（其余走寄存器堆）
    function [7:0] reg_rd;
        input [7:0] a;
        begin
            if (a == 8'h3A) reg_rd = {7'b0000000, drdy_r};
            else            reg_rd = regs[a];
        end
    endfunction

    integer i;
    reg [15:0] sample_id = 16'd0;

    task load_sample;                       // 原子装载当前样本并置 DRDY
        begin
            regs[8'h3B] = DATA_BASE + 8'd0;
            regs[8'h3C] = DATA_BASE + 8'd1;
            regs[8'h3D] = DATA_BASE + 8'd2;
            regs[8'h3E] = DATA_BASE + 8'd3;
            regs[8'h3F] = DATA_BASE + 8'd4;
            regs[8'h40] = DATA_BASE + 8'd5;
            regs[8'h41] = sample_id[15:8];  // 温度对 = 样本序号（高字节）
            regs[8'h42] = sample_id[7:0];   // 温度对 = 样本序号（低字节）
            regs[8'h43] = DATA_BASE + 8'd8;
            regs[8'h44] = DATA_BASE + 8'd9;
            regs[8'h45] = DATA_BASE + 8'd10;
            regs[8'h46] = DATA_BASE + 8'd11;
            regs[8'h47] = DATA_BASE + 8'd12;
            regs[8'h48] = DATA_BASE + 8'd13;
            drdy_r = 1'b1;
        end
    endtask

    // ODR 自由采样进程（内部时钟，与外部节拍无任何同步关系）
    initial begin
        for (i = 0; i < 128; i = i + 1) regs[i] = 8'h00;
        regs[8'h75] = WHO_ID;
        regs[8'h6B] = 8'h40; // sleep after power-on/reset
        regs[8'h6C] = 0;regs[8'h70]=0;
        load_sample;                        // 样本 0
        forever begin
            #(1_000_000_000 / ODR_HZ);
            if (!FROZEN) sample_id = sample_id + 16'd1;
            if (halt === 1'b1) begin      // 停发注入：采样时钟停摆（v0.8）
                wait (halt !== 1'b1);     // 挂起：不装载新样本，DRDY 冻结
                wait (cs_n === 1'b1);     // 恢复时若 CS 有效，等释放再装载
            end
            wait (cs_n === 1'b1);           // CS 有效期间挂起（DRDY 与数据一同
            if(!regs[8'h6B][6] && regs[8'h6C][5:3]!=3'b111) load_sample; // honor sleep / accel standby
            else drdy_r=0; // 冻结），释放后装载——见头注释
        end
    end

    reg [7:0]  bit_cnt;       // CS 期间累计位数
    reg [7:0]  rx_shift;
    reg        first_byte;    // 1=下一完成字节是寄存器地址
    reg        rw;            // 地址 bit0：1=读 0=写
    reg [7:0]  reg_addr;
    reg [15:0] tx_shift;
    reg        miso_drv;
    integer    wr_count;      // 累计写入次数（tb 观测，跨 CS 累计）

    wire [7:0] rx_byte_now = {rx_shift[6:0], mosi};

    assign miso = !cs_n ? miso_drv : 1'bz;

    // 上升沿：采样 MOSI、组装字节、读操作预取下一字节
    always @(posedge sclk or posedge cs_n) begin
        if (cs_n) begin
            bit_cnt    <= 8'd0;
            rx_shift   <= 8'h00;
            first_byte <= 1'b1;
            rw         <= 1'b0;
            reg_addr   <= 8'h00;
            tx_shift   <= 16'h0000;
        end else begin
            bit_cnt  <= bit_cnt + 8'd1;
            rx_shift <= rx_byte_now;
            if (bit_cnt[2:0] == 3'd7) begin
                if (first_byte) begin
                    first_byte <= 1'b0;
                    rw         <= rx_byte_now[7];    // bit7 = R/W（1=读）
                    reg_addr   <= rx_byte_now[6:0];  // bit6:0 = 寄存器地址
                    if (rx_byte_now[7])
                        tx_shift <= {reg_rd(rx_byte_now[6:0]), 8'h00};
                end else begin
                    if (!rw) begin
                        if(reg_addr!=IGNORE_WRITE_ADDR) begin
                            if(reg_addr==8'h6B && rx_byte_now[7])begin
                                regs[8'h6B]<=8'h40;regs[8'h6C]<=0;regs[8'h70]<=0;drdy_r<=0;
                            end else if(reg_addr==8'h6A)regs[reg_addr]<=rx_byte_now & 8'h55;
                            else regs[reg_addr]<=rx_byte_now;
                        end
                        wr_count       <= wr_count + 1;
                    end
                    reg_addr <= reg_addr + 8'd1;
                    if (rw) begin
                        tx_shift <= {reg_rd(reg_addr + 8'd1), 8'h00};
                        // DRDY 消费：仅读 INT_STATUS(0x3A) 清零（INT_RD_CLEAR=0）
                        if (reg_addr == 8'h3A)
                            drdy_r <= 1'b0;
                    end
                end
            end
        end
    end

    initial wr_count = 0;

    // 下降沿：更新 MISO（仅数据字节期间输出，地址字节期间为 0）
    always @(negedge sclk) begin
        if (!cs_n) begin
            if (!first_byte && rw && bit_cnt >= 8'd8) begin
                miso_drv <= tx_shift[15];
                tx_shift <= {tx_shift[14:0], 1'b0};
            end else begin
                miso_drv <= 1'b0;
            end
        end
    end

endmodule
