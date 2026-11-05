`timescale 1ns/1ps
module tb_edge_float;
    reg clk=0;always #5 clk=~clk;reg rst_n=0,start=0;reg signed [31:0] q16=0;
    wire [31:0] fp32,expected;wire busy,done;integer i,n,checks=0;
    feature_float_serial dut(.*);
    feature_q16_float reference(.q16(q16),.fp32(expected));
    task check;input signed [31:0] value;begin
        @(negedge clk);q16=value;start=1;@(negedge clk);start=0;n=0;
        while(!done&&n<36)begin @(negedge clk);n=n+1;end
        if(!done||fp32!=expected)$fatal(1,"Float mismatch q=%h expected=%h got=%h latency=%d",value,expected,fp32,n);
        checks=checks+1;
    end endtask
    initial begin
        repeat(8)@(negedge clk);rst_n=1;
        check(0);check(1);check(-1);check(32'sh80000000);check(32'sh7fffffff);
        for(i=0;i<31;i=i+1)begin check(32'd1<<i);check((32'd1<<i)-1);check(-(32'd1<<i));end
        // Rounding half-way values and mantissa/exponent carry.
        check(32'h01000001);check(32'h01000003);check(32'h01ffffff);check(32'h7fffffc0);
        for(i=0;i<2000;i=i+1)check($random);
        $display("tb_edge_float ALL PASS %0d corner/random FP32 and bounded latency comparisons",checks);$finish;
    end
    initial begin #2000000;$fatal(1,"TIMEOUT float");end
endmodule
