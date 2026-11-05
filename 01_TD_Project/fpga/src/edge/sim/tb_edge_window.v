`timescale 1ns/1ps
module tb_edge_window;
    reg clk=0;always #5 clk=~clk;reg rst_n=0;
    reg [63:0] now_cycles=0;always @(posedge clk)now_cycles<=now_cycles+1;
    reg new_sample=0,adc_new=0,fg_new=0,a_bad=0,b_bad=0;
    reg signed [15:0] ci=100,pr=200;reg [15:0] seq=0;reg [3:0] mode=3;
    reg done=0,ready=0;wire start,abort,valid,busy;wire signed [15:0] data;
    wire [15:0] quality;wire [31:0] drops;
    edge_window #(.CLK_HZ(16000)) dut(.clk(clk),.rst_n(rst_n),.now_cycles(now_cycles),.now_ms(32'd0),
        .a_new(new_sample),.b_new(new_sample),.ax(16'sd1),.ay(16'sd2),.az(16'sd3),.bx(16'sd4),.by(16'sd5),.bz(16'sd6),
        .a_seq(seq),.b_seq(seq),.a_bad(a_bad),.b_bad(b_bad),.adc_new(adc_new),.adc_bad(1'b0),.current_raw(ci),.pressure_raw(pr),
        .temp_new(1'b1),.temp_bad(1'b0),.temp_raw(16'sd480),.fg_new(fg_new),.fg_bad(1'b0),.fg_period(32'd80),
        .enable(1'b1),.control_mode(mode),.feature_ready(1'b1),.feature_done(done),.sample_ready(ready),
        .frame_start(start),.frame_abort(abort),.sample_valid(valid),.sample_data(data),.busy(busy),.quality(quality),.drop_count(drops));
    integer i,aborts=0;always @(posedge clk)if(abort)aborts<=aborts+1;
    task sample;input integer id;input integer rail;begin
        @(negedge clk);new_sample=1;adc_new=1;fg_new=1;seq=id;ci=rail?16'sh7fff:16'sd100;
        @(negedge clk);new_sample=0;adc_new=0;fg_new=0;
        repeat(2)@(negedge clk);
    end endtask
    initial begin
        repeat(8)@(negedge clk);rst_n=1;
        // Rail occurs exactly at the half-window boundary, not one tick earlier.
        for(i=0;i<1024;i=i+1)sample(i,i==1023);
        if(!busy||!quality[8]||!quality[10])$fatal(1,"Boundary rail was not retained");
        // Consumer stalls: a new sample must abort before retained data is reused.
        for(i=1024;i<2049;i=i+1)sample(i,0);
        if(aborts==0||drops==0)$fatal(1,"Retention overrun not detected");
        // Reset and introduce a sequence gap + a brief mode transition inside a
        // window; the tail has returned to RUN, but the whole window stays bad.
        rst_n=0;repeat(8)@(negedge clk);rst_n=1;mode=3;
        for(i=0;i<1024;i=i+1)begin
            if(i==100)mode=4;if(i==110)mode=3;
            sample(i<200?i:i+1,0);
        end
        if(!busy||!quality[4]||!quality[5]||!quality[13])$fatal(1,"Gap/transient quality lost %h",quality);
        // RAM feed holds its value under backpressure, then begins Ax with 1.
        wait(valid);repeat(4)begin @(negedge clk);if(!valid||data!=1)$fatal(1,"RAM sample hold");end
        ready=1;repeat(8)@(negedge clk);
        $display("tb_edge_window ALL PASS boundary rail, stalled-consumer abort, sequence gap, transient and RAM backpressure");$finish;
    end
    initial begin #1000000;$fatal(1,"TIMEOUT windows");end
endmodule
