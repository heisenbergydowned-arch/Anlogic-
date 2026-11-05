`timescale 1ns/1ps
module tb_fft1024;
    localparam CASES=6;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,start=0,in_valid=0,out_ready=0;
    reg signed [31:0] in_data=0;
    wire in_ready,out_valid,busy,done;wire [9:0] out_bin;
    wire signed [31:0] out_re,out_im;
    fft1024_iter dut(.*);
    reg [31:0] data[0:CASES*1024-1];reg [1023:0] input_path,output_path;
    integer fd,c,n,cycle=0,count=0,completions=0;
    reg stalled=0;reg [9:0] held_bin;reg signed [31:0] held_re,held_im;
    always @(negedge clk) out_ready=(cycle%7)>2;
    always @(posedge clk) begin
        cycle=cycle+1;if (cycle>240000) $fatal(1,"FFT timeout");
        if (rst_n) begin
            if (stalled && (!out_valid || out_bin!==held_bin || out_re!==held_re || out_im!==held_im))
                $fatal(1,"FFT output changed under backpressure");
            stalled=out_valid && !out_ready;held_bin=out_bin;held_re=out_re;held_im=out_im;
            if (out_valid && out_ready) begin
                if (out_bin!==count%1024) $fatal(1,"FFT bin order");
                $fdisplay(fd,"%0d %0d %0d %0d",count/1024,out_bin,out_re,out_im);count=count+1;
            end
            if (done) completions=completions+1;
        end else stalled=0;
    end
    initial begin
        if (!$value$plusargs("INPUT=%s",input_path) || !$value$plusargs("OUT=%s",output_path)) $fatal(1,"Missing paths");
        $readmemh(input_path,data);fd=$fopen(output_path,"w");if (!fd) $fatal(1,"Output open failed");
        repeat(4) @(negedge clk);rst_n=1;@(negedge clk);
        for (c=0;c<CASES;c=c+1) begin
            start=1;@(negedge clk);start=0;
            for (n=0;n<1024;n=n+1) begin
                while (!in_ready) @(negedge clk);
                if (n%11==0) @(negedge clk);
                in_valid=1;in_data=data[c*1024+n];@(negedge clk);in_valid=0;
            end
            while (busy) @(negedge clk);
            @(negedge clk);
        end
        if (count!=CASES*1024 || completions!=CASES) $fatal(1,"FFT count mismatch");
        $fclose(fd);$display("PASS FFT protocol: %0d complete transforms",CASES);$finish;
    end
endmodule
