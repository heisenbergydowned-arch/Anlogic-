`timescale 1ns/1ps
// Compile-time TEST source feeds only the diagnostic feature chain. It NEVER
// replaces physical inputs to the independent control/protection controller.
module edge_test_source #(parameter CLK_HZ=100000000)(
    input wire clk,rst_n,output reg sample_new,adc_new,temp_new,fg_new,
    output reg signed [15:0] ax,ay,az,bx,by,bz,output reg [15:0] sample_seq,
    output wire signed [15:0] current_raw,pressure_raw,temp_raw,output wire [31:0] fg_period
);
    reg [31:0] sample_timer,adc_timer,temp_timer,fg_timer;
    reg [5:0] phase;
    assign current_raw=16'sd16400;assign pressure_raw=16'sd16410;
    assign temp_raw=16'sd480;assign fg_period=CLK_HZ/200;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            sample_timer<=0;adc_timer<=0;temp_timer<=0;fg_timer<=0;
            sample_new<=0;adc_new<=0;temp_new<=0;fg_new<=0;sample_seq<=0;phase<=0;
            ax<=0;ay<=0;az<=0;bx<=0;by<=0;bz<=0;
        end else begin
            sample_new<=0;adc_new<=0;temp_new<=0;fg_new<=0;
            if(sample_timer==CLK_HZ/4000-1)begin
                sample_timer<=0;sample_new<=1;sample_seq<=sample_seq+1;
                phase<=phase==39 ? 0:phase+1;
                ax<=phase<20 ? 16'sd2048:-16'sd2048;
                ay<=phase<10 || phase>=30 ? 16'sd1024:-16'sd1024;
                az<=$signed({1'b0,phase})*16'sd64-16'sd1248;
                bx<=phase<20 ? 16'sd1024:-16'sd1024;
                by<=phase<10 || phase>=30 ? 16'sd512:-16'sd512;
                bz<=$signed({1'b0,phase})*16'sd32-16'sd624;
            end else sample_timer<=sample_timer+1;
            if(adc_timer==CLK_HZ/50000-1)begin adc_timer<=0;adc_new<=1;end else adc_timer<=adc_timer+1;
            if(temp_timer==0)temp_new<=1;
            if(temp_timer==CLK_HZ-1)temp_timer<=0;else temp_timer<=temp_timer+1;
            if(fg_timer==CLK_HZ/200-1)begin fg_timer<=0;fg_new<=1;end else fg_timer<=fg_timer+1;
        end
    end
endmodule
