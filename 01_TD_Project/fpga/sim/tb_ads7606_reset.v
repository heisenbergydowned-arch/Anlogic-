`timescale 1ns/1ps
module adc_reset_case #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer SCLK_DIV = 4,
    parameter integer WAIT_US = 8,
    parameter integer HIGH_US = 2,
    parameter integer RECOVERY_US = 3
)(output reg done = 0);
    localparam real PERIOD_NS = 1.0e9 / CLK_HZ;
    localparam integer MICRO_CYCLES = (CLK_HZ + 999_999) / 1_000_000;
    reg clk = 0;
    reg rst_n = 0;
    reg connected = 1;
    reg stuck_busy = 0;
    wire adc_reset, convst, sclk, cs_n, douta, frstdata, model_busy;
    wire valid, error;
    wire signed [15:0] channel1, channel8;
    integer reset_count = 0;
    integer valid_count = 0;
    integer cycle_count = 0;
    integer release_cycle = 0;
    integer reset_rise_cycle = 0;
    integer reset_fall_cycle = 0;
    integer previous_convst = 0;
    integer reset_phase;
    integer saved_valid_count;
    integer saved_reset_count;
    reg startup_complete = 0;

    always #(PERIOD_NS / 2.0) clk = ~clk;
    always @(posedge clk) cycle_count = cycle_count + 1;
    ads7606_if #(.CLK_FREQ(CLK_HZ), .SCLK_DIV(SCLK_DIV),
        .POWERUP_US(WAIT_US), .RESET_HIGH_US(HIGH_US),
        .RESET_RECOVERY_US(RECOVERY_US)) dut (
        .clk(clk), .rst_n(rst_n), .o_reset(adc_reset), .o_convst(convst),
        .o_sclk(sclk), .o_cs_n(cs_n), .i_douta(douta),
        .i_frstdata(frstdata), .i_busy(stuck_busy | model_busy),
        .ch1_code(channel1), .ch2_code(), .ch3_code(), .ch4_code(),
        .ch5_code(), .ch6_code(), .ch7_code(), .ch8_code(channel8), .vld(valid), .err(error));
    ads7606_model model (
        .reset(adc_reset), .convst(convst), .sclk(sclk), .cs_n(cs_n),
        .busy(model_busy), .douta(douta), .frstdata(frstdata),
        .ch1_code(16'h8001), .ch2_code(16'h1234), .ch3_code(16'hffff),
        .ch4_code(16'h0000), .ch5_code(16'h7fff), .ch6_code(16'ha55a),
        .ch7_code(16'h5aa5), .ch8_code(16'hffff), .en(connected), .frst_mode(2'd0));
    pullup(douta);

    always @(negedge rst_n) startup_complete = 0;
    always @(posedge rst_n) begin
        release_cycle = cycle_count;
        previous_convst = 0;
    end
    always @(posedge adc_reset) begin
        reset_count = reset_count + 1;
        reset_rise_cycle = cycle_count;
        if (!rst_n || cycle_count - release_cycle != WAIT_US * MICRO_CYCLES)
            $fatal(1, "RESET power-up wait CLK=%0d cycles=%0d", CLK_HZ, cycle_count-release_cycle);
        if (convst || sclk || !cs_n || valid)
            $fatal(1, "RESET while interface active");
    end
    always @(negedge adc_reset) begin
        if (rst_n && reset_count != 0) begin
            if (cycle_count - reset_rise_cycle != HIGH_US * MICRO_CYCLES)
                $fatal(1, "RESET pulse width CLK=%0d", CLK_HZ);
            reset_fall_cycle = cycle_count;
            startup_complete = 1;
        end
    end
    always @(negedge clk) begin
        if (rst_n && (!startup_complete || cycle_count-reset_fall_cycle <= RECOVERY_US*MICRO_CYCLES)) begin
            if (convst || sclk || !cs_n || valid || error)
                $fatal(1, "Interface not quiescent during startup CLK=%0d", CLK_HZ);
        end
        if (valid) begin
            if (!startup_complete || adc_reset || error || channel1 !== 16'sh8001 || channel8 !== -16'sd1)
                $fatal(1, "Valid data corruption CLK=%0d", CLK_HZ);
            valid_count = valid_count + 1;
        end
    end
    always @(posedge convst) begin
        if (!startup_complete || adc_reset || cycle_count-reset_fall_cycle < RECOVERY_US*MICRO_CYCLES)
            $fatal(1, "Premature conversion CLK=%0d", CLK_HZ);
        if (previous_convst != 0 && cycle_count-previous_convst != CLK_HZ/50_000)
            $fatal(1, "Conversion cadence changed CLK=%0d", CLK_HZ);
        previous_convst = cycle_count;
    end

    initial begin
        repeat(5) @(negedge clk);
        rst_n = 1;
        wait(valid_count >= 3);
        for (reset_phase = 0; reset_phase < 3; reset_phase = reset_phase + 1) begin
            if (reset_phase == 0) @(posedge convst);
            if (reset_phase == 1) @(posedge model_busy);
            if (reset_phase == 2) @(negedge cs_n);
            @(negedge clk);
            rst_n = 0;
            #1;
            if (convst || sclk || !cs_n || adc_reset || valid || channel1 !== 0 || channel8 !== 0)
                $fatal(1, "Warm reset failed phase=%0d", reset_phase);
            repeat(10) @(negedge clk);
            saved_valid_count = valid_count;
            rst_n = 1;
            wait(valid_count >= saved_valid_count + 3);
        end
        saved_reset_count = reset_count;
        @(negedge clk);
        connected = 0;
        saved_valid_count = valid_count;
        #100_000;
        if (!error || valid_count != saved_valid_count || reset_count != saved_reset_count)
            $fatal(1, "Disconnect handling or unwanted RESET");
        connected = 1;
        wait(valid_count >= saved_valid_count + 3);
        @(negedge clk);
        connected = 0;
        stuck_busy = 1;
        saved_valid_count = valid_count;
        #100_000;
        if (!error || valid_count != saved_valid_count || reset_count != saved_reset_count)
            $fatal(1, "BUSY stuck handling or unwanted RESET");
        stuck_busy = 0;
        connected = 1;
        wait(valid_count >= saved_valid_count + 3);
        if (reset_count != 4) $fatal(1, "Unexpected reset count %0d", reset_count);
        $display("RESET_CASE PASS CLK=%0d reset_count=%0d valid=%0d", CLK_HZ, reset_count, valid_count);
        done = 1;
    end
endmodule

module tb_ads7606_reset;
    wire done100, done75, done50, done1;
    adc_reset_case default_clock(done100);
    adc_reset_case #(.CLK_HZ(75_500_000), .SCLK_DIV(3)) fractional_clock(done75);
    adc_reset_case #(.CLK_HZ(50_000_000), .SCLK_DIV(2)) slow_clock(done50);
    adc_reset_case #(.WAIT_US(1), .HIGH_US(1), .RECOVERY_US(1)) minimum_counters(done1);
    initial begin
        wait(done100 && done75 && done50 && done1);
        $display("tb_ads7606_reset: ALL PASS");
        $finish;
    end
    initial begin
        #2_000_000;
        $fatal(2, "tb_ads7606_reset TIMEOUT");
    end
endmodule
