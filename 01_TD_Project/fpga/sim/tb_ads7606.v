//============================================================================
// tb_ads7606.v — ads7606_if 单元测试（四实例并行）
//
// 场景A（健康）：8 通道数据通路 + vld 节拍 20µs + err=0 + 动态换数；
// 场景B（掉线→恢复）：en=0 时 err=1、无 vld；en=1 后 err 自动清除、数据恢复；
// 场景C（FRSTDATA 恒低）：bit0 相位校验报 err（不阻塞读数）；
// 场景D（FRSTDATA 恒高）：bit17 相位校验报 err。
//============================================================================
`timescale 1ns/1ps
module tb_ads7606;
    localparam integer CLK_NS = 10;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    realtime released_at, reset_rise_at, reset_fall_at;
    integer reset_pulses = 0;
    reg startup_checked = 0;
    always #(CLK_NS/2.0) clk = ~clk;

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

    //====================================================================
    // 场景 A：健康（换数测试）
    //====================================================================
    wire        a_convst, a_sclk, a_cs_n, a_douta, a_frst;
    wire        a_busy, a_reset, b_reset, c_reset, d_reset;
    wire signed [15:0] a_ch1, a_ch2, a_ch3, a_ch4, a_ch5, a_ch6, a_ch7, a_ch8;
    wire        a_vld, a_err;

    reg [15:0] ain1 = 16'h8001, ain2 = 16'h7FFE, ain3 = 16'h0001, ain4 = 16'hFFFE;
    reg [15:0] ain5 = 16'h1234, ain6 = 16'h5678, ain7 = 16'h9ABC, ain8 = 16'hDEAD;

    ads7606_if #(
        .CLK_FREQ (100_000_000), .SAMPLE_HZ (50_000), .SCLK_DIV (4)
    ) dut_a (
        .o_reset(a_reset),
        .clk (clk), .rst_n (rst_n),
        .o_convst (a_convst), .i_busy (a_busy), .o_sclk (a_sclk),
        .i_douta (a_douta), .o_cs_n (a_cs_n), .i_frstdata (a_frst),
        .ch1_code (a_ch1), .ch2_code (a_ch2), .ch3_code (a_ch3), .ch4_code (a_ch4),
        .ch5_code (a_ch5), .ch6_code (a_ch6), .ch7_code (a_ch7), .ch8_code (a_ch8),
        .vld (a_vld), .err (a_err)
    );

    ads7606_model u_model_a (
        .reset(a_reset),
        .convst (a_convst), .busy (a_busy), .sclk (a_sclk), .cs_n (a_cs_n),
        .douta (a_douta), .frstdata (a_frst),
        .ch1_code (ain1), .ch2_code (ain2), .ch3_code (ain3), .ch4_code (ain4),
        .ch5_code (ain5), .ch6_code (ain6), .ch7_code (ain7), .ch8_code (ain8),
        .en (1'b1), .frst_mode (2'd0)
    );
    pullup (a_douta);

    always @(posedge rst_n) released_at = $realtime;
    always @(posedge a_reset) begin
        reset_pulses = reset_pulses + 1;
        reset_rise_at = $realtime;
        check(reset_rise_at-released_at >= 49_999_990.0 && reset_rise_at-released_at <= 50_000_010.0,
              "default_powerup_50ms");
    end
    always @(negedge a_reset) begin
        if (reset_pulses != 0) begin
            reset_fall_at = $realtime;
            check(reset_fall_at-reset_rise_at == 10_000.0, "default_reset_high_10us");
        end
    end
    always @(posedge a_convst) begin
        if (!startup_checked) begin
            check(reset_pulses == 1, "default_exactly_one_reset");
            check($realtime-reset_fall_at >= 1_000_000.0, "default_recovery_1ms");
            startup_checked = 1;
        end
        check(a_reset === 0, "no_conversion_during_reset");
    end

    //====================================================================
    // 场景 B：掉线 → 恢复
    //====================================================================
    wire        b_convst, b_sclk, b_cs_n, b_douta, b_frst;
    wire        b_busy;
    wire signed [15:0] b_ch1, b_ch2, b_ch3, b_ch4, b_ch5, b_ch6, b_ch7, b_ch8;
    wire        b_vld, b_err;
    reg         b_en = 1'b0;

    ads7606_if #(
        .CLK_FREQ (100_000_000), .SAMPLE_HZ (50_000), .SCLK_DIV (4)
    ) dut_b (
        .o_reset(b_reset),
        .clk (clk), .rst_n (rst_n),
        .o_convst (b_convst), .i_busy (b_busy), .o_sclk (b_sclk),
        .i_douta (b_douta), .o_cs_n (b_cs_n), .i_frstdata (b_frst),
        .ch1_code (b_ch1), .ch2_code (b_ch2), .ch3_code (b_ch3), .ch4_code (b_ch4),
        .ch5_code (b_ch5), .ch6_code (b_ch6), .ch7_code (b_ch7), .ch8_code (b_ch8),
        .vld (b_vld), .err (b_err)
    );

    ads7606_model u_model_b (
        .reset(b_reset),
        .convst (b_convst), .busy (b_busy), .sclk (b_sclk), .cs_n (b_cs_n),
        .douta (b_douta), .frstdata (b_frst),
        .ch1_code (16'h0102), .ch2_code (16'h0304), .ch3_code (16'h0506),
        .ch4_code (16'h0708), .ch5_code (16'h090A), .ch6_code (16'h0B0C),
        .ch7_code (16'h0D0E), .ch8_code (16'h0F10),
        .en (b_en), .frst_mode (2'd0)
    );
    pullup (b_douta);

    //====================================================================
    // 场景 C/D：FRSTDATA 恒低 / 恒高
    //====================================================================
    wire        c_convst, c_sclk, c_cs_n, c_douta, c_frst, c_busy, c_vld, c_err;
    wire signed [15:0] c_ch1, c_ch2, c_ch3, c_ch4, c_ch5, c_ch6, c_ch7, c_ch8;
    wire        d_convst, d_sclk, d_cs_n, d_douta, d_frst, d_busy, d_vld, d_err;
    wire signed [15:0] d_ch1, d_ch2, d_ch3, d_ch4, d_ch5, d_ch6, d_ch7, d_ch8;

    ads7606_if #(
        .CLK_FREQ (100_000_000), .SAMPLE_HZ (50_000), .SCLK_DIV (4)
    ) dut_c (
        .o_reset(c_reset),
        .clk (clk), .rst_n (rst_n),
        .o_convst (c_convst), .i_busy (c_busy), .o_sclk (c_sclk),
        .i_douta (c_douta), .o_cs_n (c_cs_n), .i_frstdata (c_frst),
        .ch1_code (c_ch1), .ch2_code (c_ch2), .ch3_code (c_ch3), .ch4_code (c_ch4),
        .ch5_code (c_ch5), .ch6_code (c_ch6), .ch7_code (c_ch7), .ch8_code (c_ch8),
        .vld (c_vld), .err (c_err)
    );
    ads7606_model u_model_c (
        .reset(c_reset),
        .convst (c_convst), .busy (c_busy), .sclk (c_sclk), .cs_n (c_cs_n),
        .douta (c_douta), .frstdata (c_frst),
        .ch1_code (16'h1111), .ch2_code (16'h2222), .ch3_code (16'h3333),
        .ch4_code (16'h4444), .ch5_code (16'h5555), .ch6_code (16'h6666),
        .ch7_code (16'h7777), .ch8_code (16'h8888),
        .en (1'b1), .frst_mode (2'd1)      // 恒低
    );
    pullup (c_douta);

    ads7606_if #(
        .CLK_FREQ (100_000_000), .SAMPLE_HZ (50_000), .SCLK_DIV (4)
    ) dut_d (
        .o_reset(d_reset),
        .clk (clk), .rst_n (rst_n),
        .o_convst (d_convst), .i_busy (d_busy), .o_sclk (d_sclk),
        .i_douta (d_douta), .o_cs_n (d_cs_n), .i_frstdata (d_frst),
        .ch1_code (d_ch1), .ch2_code (d_ch2), .ch3_code (d_ch3), .ch4_code (d_ch4),
        .ch5_code (d_ch5), .ch6_code (d_ch6), .ch7_code (d_ch7), .ch8_code (d_ch8),
        .vld (d_vld), .err (d_err)
    );
    ads7606_model u_model_d (
        .reset(d_reset),
        .convst (d_convst), .busy (d_busy), .sclk (d_sclk), .cs_n (d_cs_n),
        .douta (d_douta), .frstdata (d_frst),
        .ch1_code (16'h1111), .ch2_code (16'h2222), .ch3_code (16'h3333),
        .ch4_code (16'h4444), .ch5_code (16'h5555), .ch6_code (16'h6666),
        .ch7_code (16'h7777), .ch8_code (16'h8888),
        .en (1'b1), .frst_mode (2'd2)      // 恒高
    );
    pullup (d_douta);

    //====================================================================
    // 监测：vld 计数、周期
    //====================================================================
    integer vld_a_cnt = 0, vld_b_cnt = 0, vld_c_cnt = 0, vld_d_cnt = 0;
    real    t_a_prev = 0.0, t_a_last = 0.0;
    real    period_min = 1.0e9, period_max = 0.0;

    always @(posedge clk) begin
        if (a_vld) begin
            vld_a_cnt = vld_a_cnt + 1;
            t_a_prev  = t_a_last;
            t_a_last  = $realtime;
            if (vld_a_cnt > 1) begin
                if (t_a_last - t_a_prev < period_min) period_min = t_a_last - t_a_prev;
                if (t_a_last - t_a_prev > period_max) period_max = t_a_last - t_a_prev;
            end
        end
        if (b_vld) vld_b_cnt = vld_b_cnt + 1;
        if (c_vld) vld_c_cnt = vld_c_cnt + 1;
        if (d_vld) vld_d_cnt = vld_d_cnt + 1;
    end

    //====================================================================
    // 主流程（帧 20µs：首帧完成 ≈35µs；各检查点留足余量）
    //====================================================================
    initial begin
        repeat (10) @(posedge clk);
        rst_n = 1'b1;
        wait(dut_a.startup_ready);

        // ---- 场景 B 前半：掉线 ----
        #(100_000);   // 100µs ≈ 5 帧
        $display("@%0t B(absent): vld=%0d err=%b", $time, vld_b_cnt, b_err);
        check(vld_b_cnt == 0, "B_absent_no_vld");
        check(b_err    === 1'b1, "B_absent_err");

        // ---- 场景 B 后半：恢复 ----
        b_en = 1'b1;
        #(100_000);   // 再 5 帧
        $display("@%0t B(recovered): vld=%0d err=%b ch1=%04x ch8=%04x",
                 $time, vld_b_cnt, b_err, b_ch1, b_ch8);
        check(b_err    === 1'b0, "B_recover_err_clear");
        check(vld_b_cnt >= 3, "B_recover_vld");
        check(b_ch1 == 16'sh0102 && b_ch8 == 16'sh0F10, "B_recover_data");

        // ---- 场景 C/D：FRSTDATA 错位 ----
        $display("@%0t C(frst low): vld=%0d err=%b | D(frst high): vld=%0d err=%b",
                 $time, vld_c_cnt, c_err, vld_d_cnt, d_err);
        check(c_err === 1'b1, "C_frst_low_err");
        check(vld_c_cnt >= 3, "C_frst_low_nonblocking");
        check(d_err === 1'b1, "D_frst_high_err");
        check(vld_d_cnt >= 3, "D_frst_high_nonblocking");

        // ---- 场景 A：正常采集（300µs ≈ 13 帧）----
        #(100_000);
        $display("@%0t A: vld=%0d err=%b period=%.1f..%.1f ns",
                 $time, vld_a_cnt, a_err, period_min, period_max);
        check(a_err === 1'b0, "A_no_err");
        check(vld_a_cnt >= 10, "A_vld_rate");
        check(period_min >= 19985.0 && period_max <= 20015.0, "A_frame_period_20us");
        $display("A ch: %04x %04x %04x %04x %04x %04x %04x %04x",
                 a_ch1, a_ch2, a_ch3, a_ch4, a_ch5, a_ch6, a_ch7, a_ch8);
        check(a_ch1 == 16'sh8001 && a_ch2 == 16'sh7FFE, "A_ch12");
        check(a_ch3 == 16'sh0001 && a_ch4 == -16'sd2,   "A_ch34");
        check(a_ch5 == 16'sh1234 && a_ch6 == 16'sh5678, "A_ch56");
        check(a_ch7 == 16'sh9ABC && a_ch8 == 16'shDEAD, "A_ch78");

        // ---- 场景 A：动态换数（改激励后下一帧生效）----
        ain1 = 16'h0000; ain2 = 16'hFFFF; ain3 = 16'h00FF; ain4 = 16'hFF00;
        ain5 = 16'hA55A; ain6 = 16'h5AA5; ain7 = 16'h0F0F; ain8 = 16'hF0F0;
        #(60_000);    // 3 帧
        $display("@%0t A(new): ch1=%04x ch8=%04x", $time, a_ch1, a_ch8);
        check(a_ch1 == 16'sh0000 && a_ch2 == -16'sd1,  "A_new_ch12");
        check(a_ch3 == 16'sh00FF && a_ch4 == 16'shFF00, "A_new_ch34");
        check(a_ch5 == -16'sh5AA6 && a_ch6 == 16'sh5AA5, "A_new_ch56");
        check(a_ch7 == 16'sh0F0F && a_ch8 == 16'shF0F0, "A_new_ch78");
        check(a_err === 1'b0, "A_new_no_err");
        check(reset_pulses == 1 && startup_checked, "default_reset_no_retrigger");

        if (errors == 0) begin
            $display("tb_ads7606: ALL PASS");
            $finish;
        end else begin
            $fatal(1, "tb_ads7606: %0d ERRORS", errors);
        end
    end

    // 超时保护
    initial begin
        #55_000_000;
        $fatal(2, "tb_ads7606: TIMEOUT — errors=%0d", errors);
    end
endmodule
