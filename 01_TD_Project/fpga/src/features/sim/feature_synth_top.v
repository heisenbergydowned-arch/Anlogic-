`timescale 1ns/1ps
// Synthesis-only wrapper: internal buses must not become 336 physical package pins.
// Small register bus keeps all feature inputs/outputs observable without pruning.
module feature_synth_top (
    input wire clk,rst_n,reg_wr,
    input wire [3:0] reg_addr,
    input wire [15:0] reg_wdata,
    input wire sample_valid,
    input wire signed [15:0] sample_data,
    input wire out_ready,
    output wire sample_ready,frame_ready,out_valid,
    output wire [5:0] out_index,
    output reg [15:0] reg_rdata
);
    reg [15:0] bank[0:11];integer i;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) for(i=0;i<12;i=i+1) bank[i]<=0;
        else if(reg_wr && reg_addr<12) bank[reg_addr]<=reg_wdata;
    end
    wire signed [31:0] out_q16;
    wire [31:0] out_fp32,out_frame_id;
    wire [15:0] out_quality;
    wire busy,out_last,frame_done;
    feature_extract dut(.clk(clk),.rst_n(rst_n),
        .frame_start(reg_wr && reg_addr==13 && reg_wdata[0]),.frame_ready(frame_ready),
        .frame_id({bank[1],bank[0]}),.current_q16({bank[3],bank[2]}),
        .temp_q16({bank[5],bank[4]}),.pressure_q16({bank[7],bank[6]}),.rpm_q16({bank[9],bank[8]}),
        .input_quality(bank[10]),.sample_valid(sample_valid),.sample_ready(sample_ready),.sample_data(sample_data),
        .cfg_we(reg_wr && reg_addr==12),.cfg_index(bank[11][3:0]),.cfg_edge(reg_wdata[9:0]),
        .busy(busy),.out_valid(out_valid),.out_ready(out_ready),.out_index(out_index),
        .out_q16(out_q16),.out_fp32(out_fp32),.out_last(out_last),.out_frame_id(out_frame_id),
        .out_quality(out_quality),.frame_done(frame_done));
    always @* begin
        case(reg_addr)
            0: reg_rdata=out_q16[15:0];1:reg_rdata=out_q16[31:16];
            2: reg_rdata=out_fp32[15:0];3:reg_rdata=out_fp32[31:16];
            4: reg_rdata=out_frame_id[15:0];5:reg_rdata=out_frame_id[31:16];
            6: reg_rdata=out_quality;
            default: reg_rdata={11'd0,busy,frame_ready,sample_ready,frame_done,out_last};
        endcase
    end
endmodule
