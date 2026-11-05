//============================================================================
// tb_fg_cap.v — fg_cap 单元测试
//
// 校验：1kHz FG（周期 100000 clk）周期测量；<20µs 毛刺被滤除；
//       无边沿超时与恢复。
// 注意：TIMEOUT_US 压缩值必须 > FG 周期 1ms——若压到半周期以下，
//       正常运转的每个周期间隔都会先"超时"，vld 门控（超时后首沿
//       只校准不发 vld）会把全部 vld 吞掉，测不到任何周期。
//============================================================================
`timescale 1ns/1ps
module tb_fg_cap;
    localparam integer CLK_NS = 10;
    localparam integer FG_HALF_NS = 500_000;    // 1kHz 方波，半周期 500µs

    reg  clk = 1'b0;
    reg  rst_n = 1'b0;
    reg  fg = 1'b1;
    wire [31:0] period_cnt;
    wire vld, timeout;
    wire [31:0] pulse_count;

    always #(CLK_NS/2.0) clk = ~clk;

    fg_cap #(
        .CLK_FREQ   (100_000_000),
        .GLITCH_US  (20),
        .TIMEOUT_US (1500)         // 1.5ms > FG 周期 1ms：正常运转不误超时
    ) dut (
        .clk        (clk),
        .rst_n      (rst_n),
        .fg         (fg),
        .period_cnt (period_cnt),
        .vld        (vld),
        .pulse_count(pulse_count),
        .timeout    (timeout)
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

    // 周期监测
    integer period_seen = 0;
    reg [31:0] first_per = 0;
    always @(posedge clk) begin
        if (vld) begin
            period_seen = period_seen + 1;
            if (period_seen == 3) first_per = period_cnt;
        end
    end

    integer k;
    integer pc_before;
    initial begin
        // 复位
        repeat (10) @(posedge clk);
        rst_n = 1'b1;

        // 阶段1：正常 1kHz 方波，跑 4 个周期
        for (k = 0; k < 8; k = k + 1) begin
            fg = 1'b0; #(FG_HALF_NS);
            fg = 1'b1; #(FG_HALF_NS);
        end
        check(period_seen >= 3, "vld_seen");
        $display("period_cnt=%0d (expect 100000)", first_per);
        check(first_per > 32'd99990 && first_per < 32'd100010, "period_100000");

        // 阶段2：高电平期间注入 5µs 毛刺（< 滤波窗 20µs）
        // 原始信号 3 个上升沿；积分滤波将毛刺前后合并为连续高电平，
        // 理想结果剩 2 个上升沿。未滤波则会数出 3 个（多 1 个假边沿）。
        pc_before = pulse_count;
        fg = 1'b0; #(FG_HALF_NS);
        fg = 1'b1; #(FG_HALF_NS / 2);
        fg = 1'b0; #(5_000);       // 5µs 毛刺
        fg = 1'b1; #(FG_HALF_NS / 2);
        fg = 1'b0; #(FG_HALF_NS);
        fg = 1'b1; #(FG_HALF_NS);
        #(100_000);
        $display("pulse delta=%0d (expect 2)", pulse_count - pc_before);
        check(pulse_count - pc_before == 2, "glitch_filtered");

        // 阶段3：停转（fg 恒高）→ 1.5ms 门限后超时（阶段2 末沿后已有 100µs）
        fg = 1'b1;
        #(1_800_000);
        check(timeout === 1'b1, "timeout_assert");
        $display("timeout=%b pulse_count=%0d", timeout, pulse_count);

        // 阶段4：恢复方波 → timeout 清零、vld 恢复
        period_seen = 0;
        for (k = 0; k < 4; k = k + 1) begin
            fg = 1'b0; #(FG_HALF_NS);
            fg = 1'b1; #(FG_HALF_NS);
        end
        check(timeout === 1'b0, "timeout_clear");
        check(period_seen >= 2, "vld_recover");

        if (errors == 0) begin
            $display("tb_fg_cap: ALL PASS");
            $finish;
        end else begin
            $fatal(1, "tb_fg_cap: %0d ERRORS", errors);
        end
    end

    // 超时保护（全程 ~15.9ms：阶段1 8ms + 阶段2 2.1ms + 阶段3 1.8ms
    // + 阶段4 4ms；挂起则 $fatal(2)）
    initial begin
        #25_000_000;
        $fatal(2, "tb_fg_cap: TIMEOUT — errors=%0d", errors);
    end
endmodule
