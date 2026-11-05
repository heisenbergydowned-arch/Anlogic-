`timescale 1ns/1ps
module tb_pressure_convert;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0,start=0;
    reg signed [31:0] pressure_mean=0;
    reg [3:0] valid_mask=15;
    wire done;
    wire signed [31:0] pressure_q16,current_q16;
    wire [15:0] quality;
    feature_process_convert #(.RUNTIME_CONFIG(1)) dut(
        .clk(clk),.rst_n(rst_n),.start(start),.current_mean_code_q16(32'sd1074790400),
        .pressure_mean_code_q16(pressure_mean),.temperature_raw(16'sd480),.fg_mean_period(32'd500000),
        .valid_mask(valid_mask),.cfg_current_zero(32'sd1073741824),.cfg_pressure_zero(32'sd0),
        .cfg_current_slope(32'sd885622),.cfg_pressure_slope(32'sd17896),.cfg_ppr(4'd2),
        .done(done),.pressure_q16(pressure_q16),.current_q16(current_q16),.quality(quality));
    task convert;
        input integer raw_counts;
        input integer expected;
        integer waited;
        begin
            @(negedge clk);pressure_mean=raw_counts*65536;start=1;
            @(negedge clk);start=0;waited=0;
            while(!done && waited<200)begin @(negedge clk);waited=waited+1;end
            if(!done)$fatal(1,"process conversion timeout");
            if(pressure_q16>expected+1 || pressure_q16<expected-1)$fatal(1,"Pa to kPa wrong counts=%d got=%d expected=%d",raw_counts,pressure_q16,expected);
        end
    endtask
    initial begin
        repeat(8)@(negedge clk);rst_n=1;
        convert(6000,6553);if(quality)$fatal(1,"nominal conversion invalid");
        convert(-6000,-6554);convert(0,0);convert(30000,32768);convert(-30000,-32769);
        valid_mask=4'b1011;convert(6000,0);
        if(!quality[10] || quality[8] || current_q16==0)$fatal(1,"pressure invalid mask coupled to current");
        $display("tb_pressure_convert ALL PASS signed SDP counts to kPa and independent validity");$finish;
    end
    initial begin #100000;$fatal(1,"TIMEOUT digital pressure conversion");end
endmodule
