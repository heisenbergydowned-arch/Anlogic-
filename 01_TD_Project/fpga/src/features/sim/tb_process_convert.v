`timescale 1ns/1ps
module tb_process_convert;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,start=0;
    reg signed [31:0] current_mean_code_q16=0,pressure_mean_code_q16=0;
    reg signed [15:0] temperature_raw=0;
    reg [31:0] fg_mean_period=0;reg [3:0] valid_mask=0;
    // Static-coefficient compatibility test; runtime configuration is disabled.
    wire signed [31:0] cfg_current_zero=0,cfg_pressure_zero=0;
    wire signed [31:0] cfg_current_slope=0,cfg_pressure_slope=0;
    wire [3:0] cfg_ppr=0;
    wire busy,done;wire signed [31:0] current_q16,temp_q16,pressure_q16,rpm_q16;wire [15:0] quality;
    feature_process_convert dut(.*);
    reg [31:0] vectors[0:29];reg [1023:0] input_path,output_path;
    integer fd,c,cycles=0;
    always @(posedge clk) begin cycles=cycles+1;if(cycles>1000)$fatal(1,"Process timeout");end
    initial begin
        if (!$value$plusargs("INPUT=%s",input_path) || !$value$plusargs("OUT=%s",output_path)) $fatal(1,"Missing paths");
        $readmemh(input_path,vectors);fd=$fopen(output_path,"w");if (!fd) $fatal(1,"Output open failed");
        repeat(4) @(negedge clk);rst_n=1;@(negedge clk);
        for (c=0;c<6;c=c+1) begin
            current_mean_code_q16=vectors[5*c];pressure_mean_code_q16=vectors[5*c+1];
            temperature_raw=vectors[5*c+2];fg_mean_period=vectors[5*c+3];valid_mask=vectors[5*c+4];
            start=1;@(negedge clk);start=0;
            while (!done) @(negedge clk);
            $fdisplay(fd,"%0d %0d %0d %0d %0d %04h",c,current_q16,temp_q16,pressure_q16,rpm_q16,quality);
            @(negedge clk);
        end
        $fclose(fd);$display("PASS process converter: six snapshots");$finish;
    end
endmodule
