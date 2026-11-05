//============================================================================
// tb_dbg_uart.v — dbg_uart v2 双帧格式单元测试（FRAME_MS/CAL_DIV 压缩加速）
//
// 校验：帧 A 77B（0x55 0xA5 头 + 状态字 + 序号/诊断计数（含 dup）+
//       14 路量，全部 76 内容字节逐字段比对，[76] = 0..75 逐字节异或）；
//       帧 B 27B（0x55 0xA6 头 + BMP280 校准 24B 逐字节比对，
//       [26] = 0..25 异或）；CAL_DIV=2 → 每 2 帧 A 插 1 帧 B 并立即
//       补发帧 A（保持节奏）——序列断言：A, A(跳过), B, A(补发)。
//       小端字节序与 dbg_uart.v 头注释帧格式一致。
//============================================================================
`timescale 1ns/1ps
module tb_dbg_uart;
    localparam integer CLK_NS = 10;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    wire tx;

    always #(CLK_NS/2.0) clk = ~clk;

    // 测试激励：每字段取可辨识值，覆盖全部字节通路
    wire [191:0] cal_tb;
    genvar gi;
    generate
        for (gi = 0; gi < 24; gi = gi + 1) begin : g_cal
            assign cal_tb[gi*8 +: 8] = 8'h88 + gi[7:0];   // 0x88..0x9F
        end
    endgenerate

    dbg_uart #(
        .CLK_FREQ  (100_000_000),
        .BAUD      (115_200),
        .FRAME_MS  (1),          // 仿真压缩：帧背靠背发送
        .CAL_DIV   (2)           // 仿真压缩：每 2 帧 A 一帧 B
    ) dut (
        .clk        (clk),
        .rst_n      (rst_n),
        .d_status   (16'h1234),
        .d_seq_a    (16'd1),  .d_seq_b   (16'd2),
        .d_tick     (16'd3),
        .d_vld_a    (16'd4),  .d_vld_b   (16'd5),
        .d_drdy0_a  (16'd6),  .d_drdy0_b (16'd7),
        .d_wd_a     (8'd8),   .d_wd_b    (8'd9),
        .d_dup_a    (16'd10), .d_dup_b   (16'd11),
        .d_bmp_cal  (cal_tb),
        .d_bmp_cal_vld(1'b1),
        .d_a_ax     (16'h0102), .d_a_ay (16'h0304), .d_a_az (16'h0506),
        .d_b_ax     (16'h1112), .d_b_ay (16'h1314), .d_b_az (16'h1516),
        .d_adc1     (16'h1234), .d_adc2 (16'h5678),
        .d_adc3     (16'h9ABC), .d_adc4 (16'hDEF0),
        .d_adc5     (16'h0123), .d_adc6 (16'h4567),
        .d_adc7     (16'h89AB), .d_adc8 (16'hCDEF),
        .d_fg_period(32'd100000),
        .d_fg_pcount(32'd5),
        .d_inlet_aht_q4   (16'h0190), .d_core_temp_q4 (16'h0258),
        .d_aht_hum  (20'h80000), .d_aht_temp (20'h60000),
        .d_bmp_t    (20'hABCDE), .d_bmp_p   (20'h12345),
        .tx         (tx)
    );

    integer errors = 0;
    task check;
        input cond;
        input [255:0] tag;
        begin
            if (cond !== 1'b1) begin
                errors = errors + 1;
                $display("[%0s] FAIL @%0t", tag, $time);
            end
        end
    endtask

    // 115200 8N1：起始沿后等 1.5 位到 bit0 中心采样（位宽 ≈ 868 clk）
    task uart_rx_byte;
        output [7:0] b;
        integer k;
        begin
            @(negedge tx);
            #(CLK_NS * 1302);            // bit0 中心 = 起始沿 + 1.5 bit
            for (k = 0; k < 8; k = k + 1) begin
                b[k] = tx;
                #(CLK_NS * 868);         // 下一位中心
            end
        end
    endtask

    // 扫描到帧头 0x55 + (0xA5|0xA6)，frame_type = 帧类型字节
    reg [7:0] frame_type;
    reg [7:0] b0, b1;
    reg       hdr_found;
    integer   guard;

    task sync_hdr;
        begin
            hdr_found = 0; guard = 0;
            while (!hdr_found && guard < 400) begin
                uart_rx_byte(b0);
                if (b0 == 8'h55) begin
                    uart_rx_byte(b1);
                    if (b1 == 8'hA5 || b1 == 8'hA6) begin
                        hdr_found  = 1;
                        frame_type = b1;
                    end
                end
                guard = guard + 1;
            end
        end
    endtask

    reg [7:0]  fra [0:76];       // 帧 A 77 字节
    reg [7:0]  frb [0:26];       // 帧 B 27 字节
    reg [7:0]  xor_calc;
    integer    i;

    initial begin
        #(100);
        rst_n = 1'b1;

        //──── 帧 A #1：全字段逐字节校验 ────
        sync_hdr;
        check(hdr_found, "frame_sync");
        check(frame_type == 8'hA5, "frame1_is_A");
        if (hdr_found && frame_type == 8'hA5) begin
            fra[0] = 8'h55; fra[1] = 8'hA5;
            for (i = 2; i < 77; i = i + 1) uart_rx_byte(fra[i]);

            check(fra[2]  == 8'h34 && fra[3]  == 8'h12, "status_le");
            check(fra[4]  == 8'h01 && fra[5]  == 8'h00, "seq_a_le");
            check(fra[6]  == 8'h02 && fra[7]  == 8'h00, "seq_b_le");
            check(fra[8]  == 8'h03 && fra[9]  == 8'h00, "tick_le");
            check(fra[10] == 8'h04 && fra[11] == 8'h00, "vld_a_le");
            check(fra[12] == 8'h05 && fra[13] == 8'h00, "vld_b_le");
            check(fra[14] == 8'h06 && fra[15] == 8'h00, "drdy0_a_le");
            check(fra[16] == 8'h07 && fra[17] == 8'h00, "drdy0_b_le");
            check(fra[18] == 8'h08 && fra[19] == 8'h09, "wd_counters");
            check(fra[20] == 8'h90 && fra[21] == 8'h01, "temp_a_le");
            check(fra[22] == 8'h58 && fra[23] == 8'h02, "temp_b_le");
            check(fra[24] == 8'h00 && fra[25] == 8'h00 && fra[26] == 8'h08, "aht_hum_le");
            check(fra[27] == 8'h00 && fra[28] == 8'h00 && fra[29] == 8'h06, "aht_temp_le");
            check(fra[30] == 8'hDE && fra[31] == 8'hBC && fra[32] == 8'h0A, "bmp_t_le");
            check(fra[33] == 8'h45 && fra[34] == 8'h23 && fra[35] == 8'h01, "bmp_p_le");
            check(fra[36] == 8'h02 && fra[37] == 8'h01, "a_ax_le");
            check(fra[38] == 8'h04 && fra[39] == 8'h03, "a_ay_le");
            check(fra[40] == 8'h06 && fra[41] == 8'h05, "a_az_le");
            check(fra[42] == 8'h12 && fra[43] == 8'h11, "b_ax_le");
            check(fra[44] == 8'h14 && fra[45] == 8'h13, "b_ay_le");
            check(fra[46] == 8'h16 && fra[47] == 8'h15, "b_az_le");
            check(fra[48] == 8'h34 && fra[49] == 8'h12, "adc1_le");
            check(fra[50] == 8'h78 && fra[51] == 8'h56, "adc2_le");
            check(fra[52] == 8'hBC && fra[53] == 8'h9A, "adc3_le");
            check(fra[54] == 8'hF0 && fra[55] == 8'hDE, "adc4_le");
            check(fra[56] == 8'h23 && fra[57] == 8'h01, "adc5_le");
            check(fra[58] == 8'h67 && fra[59] == 8'h45, "adc6_le");
            check(fra[60] == 8'hAB && fra[61] == 8'h89, "adc7_le");
            check(fra[62] == 8'hEF && fra[63] == 8'hCD, "adc8_le");
            check(fra[64] == 8'hA0 && fra[65] == 8'h86 &&
                  fra[66] == 8'h01 && fra[67] == 8'h00, "fg_period_le");
            check(fra[68] == 8'h05 && fra[69] == 8'h00 &&
                  fra[70] == 8'h00 && fra[71] == 8'h00, "fg_pcount_le");
            check(fra[72] == 8'h0A && fra[73] == 8'h00, "dup_a_le");
            check(fra[74] == 8'h0B && fra[75] == 8'h00, "dup_b_le");

            xor_calc = 8'h00;
            for (i = 0; i < 76; i = i + 1) xor_calc = xor_calc ^ fra[i];
            check(fra[76] == xor_calc, "frameA_xor_checksum");

            $display("frameA: hdr=%02x%02x status=%02x%02x seq_a=%02x%02x a_ax=%02x%02x adc1=%02x%02x dup_a=%02x%02x xor=%02x(calc %02x)",
                     fra[0], fra[1], fra[3], fra[2], fra[5], fra[4],
                     fra[37], fra[36], fra[49], fra[48],
                     fra[73], fra[72], fra[76], xor_calc);
        end

        //──── 帧 A #2：CAL_DIV=2 → 下一帧应为 B，本帧跳过 ────
        sync_hdr;
        check(hdr_found, "frame2_sync");
        check(frame_type == 8'hA5, "frame2_is_A");
        for (i = 2; i < 77; i = i + 1) uart_rx_byte(b0);   // 丢弃内容

        //──── 帧 B：BMP280 校准 24 字节 ────
        sync_hdr;
        check(hdr_found, "frameB_sync");
        check(frame_type == 8'hA6, "frameB_header_55A6");
        if (hdr_found && frame_type == 8'hA6) begin
            frb[0] = 8'h55; frb[1] = 8'hA6;
            for (i = 2; i < 27; i = i + 1) uart_rx_byte(frb[i]);

            for (i = 0; i < 24; i = i + 1)
                check(frb[2 + i] == (8'h88 + i), "bmp_cal_byte");

            xor_calc = 8'h00;
            for (i = 0; i < 26; i = i + 1) xor_calc = xor_calc ^ frb[i];
            check(frb[26] == xor_calc, "frameB_xor_checksum");

            $display("frameB: hdr=%02x%02x cal[0]=%02x cal[23]=%02x xor=%02x(calc %02x)",
                     frb[0], frb[1], frb[2], frb[25], frb[26], xor_calc);
        end

        //──── 帧 B 后立即补发帧 A（保持节奏）────
        sync_hdr;
        check(hdr_found, "frame3_sync");
        check(frame_type == 8'hA5, "refill_frame_is_A");

        if (errors == 0) begin
            $display("tb_dbg_uart: ALL PASS");
            $finish;
        end else begin
            $fatal(1, "tb_dbg_uart: %0d ERRORS", errors);
        end
    end

    initial begin
        #120_000_000;             // 120ms 保护（4 帧 A + 1 帧 B 背靠背 ~28ms）
        $fatal(2, "tb_dbg_uart: TIMEOUT — errors=%0d", errors);
    end
endmodule
