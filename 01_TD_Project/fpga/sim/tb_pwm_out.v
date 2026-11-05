//============================================================================
// tb_pwm_out.v — pwm_out 单元测试
//
// 校验：25kHz 周期（4000 clk）、各占空比高电平计数、0% 恒低、100%/超限恒高。
//============================================================================
`timescale 1ns/1ps
module tb_pwm_out;
    localparam integer CLK_NS = 10;             // 100MHz
    localparam integer PER_CLK = 4000;          // 100MHz / 25kHz

    reg  clk = 1'b0;
    reg  rst_n = 1'b0;
    reg  [15:0] duty = 16'd0;
    wire pwm;

    always #(CLK_NS/2.0) clk = ~clk;

    pwm_out #(
        .CLK_FREQ (100_000_000),
        .PWM_HZ   (25_000)
    ) dut (
        .clk   (clk),
        .rst_n (rst_n),
        .duty  (duty),
        .pwm   (pwm)
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

    // 采样统计：同步 pwm，数一个周期内的高电平拍数与周期长度
    reg pwm_d;
    always @(posedge clk) pwm_d <= pwm;
    wire pwm_rise = pwm & ~pwm_d;
    wire pwm_fall = ~pwm & pwm_d;

    integer hi_cnt = 0, per_cnt = 0;
    reg     armed = 0;
    integer hi_result = -1, per_result = -1;
    always @(posedge clk) begin
        if (pwm_rise) begin
            if (armed) begin
                per_result = per_cnt + 1;   // 补首个 rise 拍
                hi_result  = hi_cnt;        // 完成拍属新周期，不计
                armed      = 0;
            end else begin
                hi_cnt = 1; per_cnt = 0; armed = 1;   // rise 拍 pwm=1 计 1
            end
        end else if (armed) begin
            per_cnt = per_cnt + 1;
            if (pwm) hi_cnt = hi_cnt + 1;
        end
    end

    // 等一个测量结果就绪
    task wait_measure;
        begin
            hi_result = -1;
            @(posedge armed);
            @(negedge armed);   // 测量完成
        end
    endtask

    integer k;
    initial begin
        duty = 16'd0;
        repeat (10) @(posedge clk);
        rst_n = 1'b1;

        // duty=0：2 个周期恒低
        repeat (2 * PER_CLK) @(posedge clk);
        check(pwm === 1'b0, "duty0_const_low");

        // duty=1000 (25%)
        duty = 16'd1000;
        wait_measure; wait_measure;
        $display("duty=1000 : hi=%0d per=%0d", hi_result, per_result);
        check(hi_result == 1000, "duty1000_hi");
        check(per_result == PER_CLK, "duty1000_per");

        // duty=2000 (50%)
        duty = 16'd2000;
        wait_measure; wait_measure;
        $display("duty=2000 : hi=%0d per=%0d", hi_result, per_result);
        check(hi_result == 2000, "duty2000_hi");
        check(per_result == PER_CLK, "duty2000_per");

        // duty=3000 (75%)
        duty = 16'd3000;
        wait_measure; wait_measure;
        check(hi_result == 3000, "duty3000_hi");
        check(per_result == PER_CLK, "duty3000_per");

        // duty=4000 (100%)：恒高
        duty = 16'd4000;
        repeat (2 * PER_CLK) @(posedge clk);
        check(pwm === 1'b1, "duty4000_const_high");

        // duty=5000 超限：钳位到 4000 恒高
        duty = 16'd5000;
        repeat (2 * PER_CLK) @(posedge clk);
        check(pwm === 1'b1, "duty5000_clamp");

        if (errors == 0) begin
            $display("tb_pwm_out: ALL PASS");
            $finish;
        end else begin
            $fatal(1, "tb_pwm_out: %0d ERRORS", errors);
        end
    end

    // 超时保护（全程 ~0.5ms；wait_measure 挂起则 $fatal(2)）
    initial begin
        #2_000_000;
        $fatal(2, "tb_pwm_out: TIMEOUT — errors=%0d", errors);
    end
endmodule
