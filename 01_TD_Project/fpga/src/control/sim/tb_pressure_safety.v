`timescale 1ns/1ps
module tb_pressure_safety;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0,tick_ms=0;
    reg [31:0] now_ms=0;
    reg [767:0] cfg=0;
    reg adc_new=0,adc_error=0,pressure_new=0,pressure_error=1;
    reg signed [15:0] current_raw=100,pressure_raw=0;
    wire adc_valid,pressure_valid;
    wire [31:0] fast_trip;
    safety_monitor #(.PRESSURE_INDEPENDENT(1),.PRESSURE_MAX_MS(5)) dut(
        .clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.now_ms(now_ms),.cfg(cfg),
        .adc_new(adc_new),.adc_error(adc_error),.current_raw(current_raw),.pressure_raw(pressure_raw),
        .pressure_new(pressure_new),.pressure_error(pressure_error),
        .temp_new(1'b0),.temp_present(1'b0),.temp_stale(1'b1),.temp_short(1'b0),.temp_raw(16'sd0),
        .rpm(16'd0),.rpm_new(1'b0),.rpm_valid(1'b0),.a_new(1'b0),.b_new(1'b0),
        .ax(16'sd0),.ay(16'sd0),.az(16'sd0),.bx(16'sd0),.by(16'sd0),.bz(16'sd0),
        .adc_valid(adc_valid),.pressure_valid(pressure_valid),.fast_trip(fast_trip));
    task millisecond;
        begin
            @(negedge clk);tick_ms=1;adc_new=1;now_ms=now_ms+1;
            @(negedge clk);tick_ms=0;adc_new=0;
        end
    endtask
    integer elapsed;
    initial begin
        cfg[0]=1;cfg[7*32+:16]=0;cfg[7*32+16+:16]=150;cfg[8*32+:16]=200;
        cfg[8*32+16+:16]=120;cfg[13*32+:16]=100;
        repeat(8)@(negedge clk);rst_n=1;
        millisecond;
        if(!adc_valid || pressure_valid)$fatal(1,"missing pressure invalidates current or looks fresh");
        pressure_error=0;pressure_new=1;@(negedge clk);pressure_new=0;
        if(!pressure_valid)$fatal(1,"valid zero pressure rejected");
        adc_error=1;@(negedge clk);
        if(adc_valid || !pressure_valid)$fatal(1,"ADC fault couples to digital pressure");
        adc_error=0;
        for(elapsed=0;elapsed<5;elapsed=elapsed+1)millisecond;
        if(!adc_valid || pressure_valid)$fatal(1,"ADC activity refreshes stale pressure");
        pressure_error=1;current_raw=250;adc_new=1;@(negedge clk);adc_new=0;
        if(!fast_trip[0])$fatal(1,"overcurrent waits for pressure/I2C or millisecond tick");
        current_raw=100;pressure_error=0;pressure_new=1;@(negedge clk);pressure_new=0;
        if(!pressure_valid)$fatal(1,"pressure recovery failed");
        pressure_error=1;@(negedge clk);
        if(pressure_valid)$fatal(1,"pressure error held as healthy");
        $display("tb_pressure_safety ALL PASS independent freshness, valid zero and unaffected fast overcurrent");$finish;
    end
    initial begin #100000;$fatal(1,"TIMEOUT pressure safety");end
endmodule
