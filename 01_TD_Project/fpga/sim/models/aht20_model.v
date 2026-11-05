//============================================================================
// aht20_model.v — AHT20 温湿度传感器 I2C 行为模型（仿真用）
//
// 地址 0x38。支持：
//   读状态（纯读 1 字节）：bit7=busy，bit3=calibrated
//   初始化命令 0xBE 08 00 → 10ms 后 cal=1
//   触发测量 0xAC 33 00   → busy 80ms（MEAS_MS 可压缩），期间锁存 hum_in/temp_in
//   读数据（纯读 7 字节）：状态 + 6 数据字节（湿 20bit + 温 20bit，B3 高低位共享）
//   第 7 字节 = CRC8（初值 0xFF、多项式 0x31、MSB first，覆盖前 6 字节），
//   与 AHT20 数据手册一致；crc_corrupt=1 时送反码（tb 注入坏帧）。
// present=0 时不应答任何地址（模拟掉线）。
//============================================================================
`timescale 1ns/1ps
module aht20_model #(
    parameter [6:0]  ADDR7    = 7'h38,
    parameter integer MEAS_MS = 80
)(
    inout  wire        sda,
    inout  wire        scl,
    input  wire        present,      // 0 = 掉线（不响应）
    input  wire        cal_powerup,  // 1 = 上电即已校准；0 = 需 0xBE 初始化
    input  wire [19:0] hum_in,       // 湿度原始码（触发时采样）
    input  wire [19:0] temp_in,      // 温度原始码（触发时采样）
    input  wire        crc_corrupt,  // 1 = CRC 送反码（tb 注入坏帧）
    output wire        busy
);
    //--------------------------------------------------------------------
    // 开漏从机驱动
    //--------------------------------------------------------------------
    reg sda_en = 1'b0, sda_bit = 1'b0;
    assign sda = sda_en ? sda_bit : 1'bz;

    reg busy_r = 1'b0;
    reg cal_r  = 1'b1;
    assign busy = busy_r;

    reg [19:0] hum_r = 20'd0, temp_r = 20'd0;

    reg [7:0] f0, f1, f2, f3, f4, f5, f6;   // 读事务字节快照（f6 = CRC）

    //--------------------------------------------------------------------
    // I2C 位引擎
    //--------------------------------------------------------------------
    reg        started = 1'b0;
    reg        sda_prev = 1'b1;
    reg [3:0]  bitn = 4'd0;        // 当前字节内钟序（0..7 数据，8=ACK 钟，9=ACK 后）
    reg [7:0]  rxsh = 8'd0;
    reg [7:0]  txsh = 8'd0;
    reg        addr_seen = 1'b0, addr_ok = 1'b0, rw_r = 1'b0, reading = 1'b0;
    reg [1:0]  wr_cnt = 2'd0;
    reg [7:0]  w0 = 8'd0, w1 = 8'd0;
    reg        mack = 1'b0;
    reg [2:0]  rd_idx = 3'd0;      // 读事务内数据字节序
    reg        match;
    reg [7:0]  nb;

    event meas_ev, init_ev;

    // START / STOP 检测（SCL 高电平期间 SDA 变化）
    always @(sda) begin
        if (scl === 1'b1) begin
            if (sda === 1'b0 && sda_prev === 1'b1) begin      // START / RESTART
                started   <= 1'b1;
                bitn      <= 4'd0;
                addr_seen <= 1'b0;
                wr_cnt    <= 2'd0;
            end
            if (sda === 1'b1 && sda_prev === 1'b0) begin      // STOP
                started <= 1'b0;
                reading <= 1'b0;
                sda_en  <= 1'b0;
            end
        end
        sda_prev <= sda;
    end

    // 主机→从机：SCL 上升沿采样
    // bitn：0..7=数据位（下一上升沿采样），8=第 9 钟（ACK），
    //       ACK 后回到 0（下一字节 bit1）；无独立"9"态（会吞掉数据位）
    always @(posedge scl) begin
        if (started) begin
            if (bitn < 4'd8) rxsh <= {rxsh[6:0], sda};
            if (bitn == 4'd8) mack <= (sda === 1'b0);         // 读方向主机应答
            bitn <= (bitn == 4'd8) ? 4'd0 : bitn + 4'd1;
        end
    end

    // CRC8（与 aht20_drv 相同算法）：初值 0xFF、多项式 0x31、MSB first
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

    function [7:0] rd_byte;
        input [2:0] idx;
        case (idx)
            3'd0:    rd_byte = f0;
            3'd1:    rd_byte = f1;
            3'd2:    rd_byte = f2;
            3'd3:    rd_byte = f3;
            3'd4:    rd_byte = f4;
            3'd5:    rd_byte = f5;
            default: rd_byte = f6;                            // 第 7 字节：CRC
        endcase
    endfunction

    // 从机→主机 / 应答驱动：SCL 下降沿设置
    always @(negedge scl) begin
        if (started) begin
            if (bitn == 4'd8) begin
                if (reading) begin
                    sda_en <= 1'b0;                          // 交出 SDA 给主机应答
                end else begin
                    match = (rxsh[7:1] == ADDR7) && present;
                    if (!addr_seen) begin
                        addr_seen <= 1'b1;
                        addr_ok   <= match;
                        rw_r      <= rxsh[0];
                    end else if (addr_ok && !rw_r) begin      // 写数据字节
                        case (wr_cnt)
                            2'd0: w0 <= rxsh;
                            2'd1: w1 <= rxsh;
                            default: begin
                                if (w0 == 8'hAC && w1 == 8'h33 && rxsh == 8'h00)
                                    -> meas_ev;               // 触发测量
                                if (w0 == 8'hBE && w1 == 8'h08 && rxsh == 8'h00)
                                    -> init_ev;               // 初始化
                            end
                        endcase
                        if (wr_cnt != 2'd3) wr_cnt <= wr_cnt + 2'd1;
                    end
                    // 应答位
                    if (addr_seen ? addr_ok : match) begin
                        sda_en <= 1'b1; sda_bit <= 1'b0;
                    end else begin
                        sda_en <= 1'b0;                       // 不应答
                    end
                end
            end else if (bitn == 4'd0 && addr_seen) begin      // ACK 钟后；START 后首个负沿 addr_seen=0 跳过
                if (reading) begin
                    if (mack) begin                           // 主机 ACK → 下一字节
                        nb = rd_byte(rd_idx + 3'd1);
                        txsh <= nb; sda_bit <= nb[7]; sda_en <= 1'b1;
                        if (rd_idx != 3'd7) rd_idx <= rd_idx + 3'd1;
                    end else begin
                        sda_en <= 1'b0; reading <= 1'b0;      // NACK → 结束读
                    end
                end else if (addr_ok && rw_r) begin           // 地址(R) 应答后首发
                    reading <= 1'b1; rd_idx <= 3'd0;
                    f0 = {busy_r, 3'b000, cal_r, 3'b000};    // 事务快照（阻塞：本字节立即可用）
                    f1 = hum_r[19:12];
                    f2 = hum_r[11:4];
                    f3 = {hum_r[3:0], temp_r[19:16]};
                    f4 = temp_r[15:8];
                    f5 = temp_r[7:0];
                    f6 = crc_corrupt ? ~crc8_aht({f0,f1,f2,f3,f4,f5})
                                     :  crc8_aht({f0,f1,f2,f3,f4,f5});
                    nb = f0;
                    txsh <= nb; sda_bit <= nb[7]; sda_en <= 1'b1;
                end else begin
                    sda_en <= 1'b0;                           // 写：释放给主机
                end
            end else if (reading) begin                       // 数据位换位（bitn 1..7）
                sda_bit <= txsh[6];
                txsh    <= {txsh[6:0], 1'b0};
            end
        end
    end

    //--------------------------------------------------------------------
    // 测量 / 初始化过程（行为级延时）
    //--------------------------------------------------------------------
    initial cal_r = cal_powerup;

    always @(meas_ev) begin
        busy_r <= 1'b1;
        hum_r  <= hum_in;
        temp_r <= temp_in;
        #(MEAS_MS * 1_000_000);
        busy_r <= 1'b0;
    end

    always @(init_ev) begin
        #(10 * 1_000_000);
        cal_r <= 1'b1;
    end
endmodule
