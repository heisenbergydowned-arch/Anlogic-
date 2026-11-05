`timescale 1ns/1ps
module tb_pwm20k;
    reg clk = 0;
    reg rst_n = 0;
    reg [15:0] duty = 0;
    reg inhibit = 0;
    wire pwm;
    wire uninhibited_pwm;
    wire legacy_pwm;
    integer duty_value;
    integer phase;
    integer expected_ticks;
    integer high_ticks;
    integer random_value;
    integer seed = 20261026;
    integer last_rise;
    integer cycle;
    reg previous_pwm;

    always #5 clk = ~clk;
    pwm_out #(.ENABLE_INHIBIT(1)) dut(
        .clk(clk), .rst_n(rst_n), .duty(duty), .inhibit(inhibit), .pwm(pwm));
    pwm_out uninhibited(
        .clk(clk), .rst_n(rst_n), .duty(duty), .inhibit(inhibit), .pwm(uninhibited_pwm));
    pwm_out #(.PWM_HZ(25000), .ENABLE_INHIBIT(1)) legacy(
        .clk(clk), .rst_n(rst_n), .duty(duty), .inhibit(inhibit), .pwm(legacy_pwm));

    initial begin
        #2;
        rst_n = 1;
        #1;
        rst_n = 0;
        #1;
        if (pwm !== 0 || uninhibited_pwm !== 0 || legacy_pwm !== 0)
            $fatal(1, "Asynchronous reset did not force all outputs low");
        for (duty_value = 0; duty_value <= 4000; duty_value = duty_value + 1) begin
            @(negedge clk);
            rst_n = 0;
            duty = duty_value;
            inhibit = 0;
            @(negedge clk);
            rst_n = 1;
            expected_ticks = (duty_value * 5000 + 2000) / 4000;
            high_ticks = 0;
            for (phase = 0; phase < 5000; phase = phase + 1) begin
                @(posedge clk);
                #1;
                if (pwm !== (phase < expected_ticks) || uninhibited_pwm !== pwm)
                    $fatal(1, "20k mismatch duty=%0d phase=%0d", duty_value, phase);
                if (pwm) high_ticks = high_ticks + 1;
                if (legacy_pwm !== ((phase % 4000) < duty_value))
                    $fatal(1, "Legacy 25k compatibility mismatch duty=%0d phase=%0d", duty_value, phase);
            end
            if (high_ticks != expected_ticks)
                $fatal(1, "High tick count mismatch");
        end
        for (duty_value = 4001; duty_value <= 65535; duty_value = duty_value + 1) begin
            @(negedge clk);
            duty = duty_value;
            @(posedge clk);
            #1;
            if (pwm !== 1 || uninhibited_pwm !== 1 || legacy_pwm !== 1)
                $fatal(1, "Out-of-range duty not clamped: %0d", duty_value);
        end
        @(negedge clk);
        rst_n = 0;
        @(negedge clk);
        rst_n = 1;
        for (cycle = 0; cycle < 40000; cycle = cycle + 1) begin
            random_value = $random(seed);
            duty = random_value & 16'hffff;
            inhibit = (cycle % 3 == 0);
            expected_ticks = duty > 4000 ? 5000 : (duty * 5000 + 2000) / 4000;
            @(posedge clk);
            #1;
            if (pwm !== (!inhibit && (cycle % 5000 < expected_ticks)))
                $fatal(1, "Dynamic duty/inhibit priority mismatch at %0d", cycle);
            if (uninhibited_pwm !== (cycle % 5000 < expected_ticks))
                $fatal(1, "Disabled-inhibit compatibility mismatch");
            @(negedge clk);
        end
        duty = 2000;
        inhibit = 0;
        previous_pwm = 0;
        last_rise = -1;
        for (cycle = 0; cycle < 20000; cycle = cycle + 1) begin
            @(posedge clk);
            #1;
            if (pwm && !previous_pwm) begin
                if (last_rise >= 0 && cycle - last_rise != 5000)
                    $fatal(1, "Carrier period is not 5000 cycles");
                last_rise = cycle;
            end
            previous_pwm = pwm;
        end
        #1;
        rst_n = 0;
        #1;
        if (pwm !== 0) $fatal(1, "Reset during an active waveform failed");
        $display("tb_pwm20k: ALL PASS; 4001 complete duty periods, 61535 clamp values, 40000 dynamic/inhibit cycles, exact 5000-cycle carrier");
        $finish;
    end

    initial begin
        #210000000;
        $fatal(1, "tb_pwm20k TIMEOUT");
    end
endmodule
