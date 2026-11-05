`timescale 1ns/1ps
// 115200 8N1 register transport. Request 14 B (C3 51), response 16 B
// (C3 52), little endian, CRC16-CCITT-FALSE. Frames share TX with dbg_uart,
// with whole-frame arbitration. Malformed traffic never reaches registers.
module cooling_uart #(
    parameter CLK_FREQ=100_000_000, parameter BAUD=115200, parameter INTERBYTE_MS=20
)(
    input wire clk,rst_n,rx,dbg_busy,
    output wire dbg_holdoff,
    output reg tx,tx_active,
    output reg req,write_en,output reg [15:0] address,output reg [31:0] write_data,
    input wire response,input wire [31:0] read_data,input wire [7:0] error,
    output reg [31:0] bad_frames,busy_drops
);
    localparam integer BT=CLK_FREQ/BAUD;
    localparam integer GAP=CLK_FREQ/1000*INTERBYTE_MS;
    function [15:0] crc_byte;
        input [15:0] old_crc;input [7:0] data;
        reg [15:0] c;integer k;
        begin c=old_crc^{data,8'd0};for(k=0;k<8;k=k+1)c=c[15] ? (c<<1)^16'h1021:c<<1;crc_byte=c;end
    endfunction
    reg [1:0] rx_sync;
    reg [1:0] rx_state;
    reg [31:0] rx_count;
    reg [2:0] rx_bit;
    reg [7:0] rx_shift,rx_byte;
    reg rx_valid,rx_bad,rx_previous;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin rx_sync<=3;rx_state<=0;rx_count<=0;rx_bit<=0;rx_shift<=0;rx_byte<=0;rx_valid<=0;rx_bad<=0;rx_previous<=1;end
        else begin
            rx_sync<={rx_sync[0],rx};rx_previous<=rx_sync[1];rx_valid<=0;rx_bad<=0;
            case(rx_state)
                0:if(!rx_sync[1] && rx_previous) begin rx_state<=1;rx_count<=BT/2-1;end
                1:if(rx_count!=0)rx_count<=rx_count-1'b1;
                  else if(!rx_sync[1])begin rx_state<=2;rx_count<=BT-1;rx_bit<=0;end
                  else rx_state<=0;
                2:if(rx_count!=0)rx_count<=rx_count-1'b1;
                  else begin rx_shift[rx_bit]<=rx_sync[1];rx_count<=BT-1;
                      if(rx_bit==7)rx_state<=3;else rx_bit<=rx_bit+1'b1;end
                3:if(rx_count!=0)rx_count<=rx_count-1'b1;
                  else begin
                      rx_state<=0;
                      if(rx_sync[1])begin rx_byte<=rx_shift;rx_valid<=1;end else rx_bad<=1;
                  end
            endcase
        end
    end
    reg [111:0] frame;
    reg [3:0] index;
    reg [15:0] rx_crc,packet_sequence,packet_address;
    reg [7:0] packet_op;
    reg [31:0] gap_count;
    reg waiting,preparing,ready;
    reg [3:0] prep_index;
    reg [127:0] reply;
    reg [15:0] reply_crc;
    reg [3:0] tx_index,tx_bit;
    reg [31:0] tx_count;
    wire busy=waiting || preparing || ready || tx_active;
    assign dbg_holdoff=busy;
    wire [15:0] crc_after_byte=crc_byte(reply_crc,reply[prep_index*8 +:8]);
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            tx<=1;tx_active<=0;req<=0;write_en<=0;address<=0;write_data<=0;
            bad_frames<=0;busy_drops<=0;frame<=0;index<=0;rx_crc<=16'hffff;gap_count<=0;
            waiting<=0;preparing<=0;ready<=0;prep_index<=0;reply<=0;reply_crc<=16'hffff;
            packet_sequence<=0;packet_address<=0;packet_op<=0;tx_index<=0;tx_bit<=0;tx_count<=0;
        end else begin
            req<=0;
            if(index!=0) begin
                if(gap_count>=GAP-1) begin index<=0;gap_count<=0;
                    if(bad_frames!=32'hffff_ffff)bad_frames<=bad_frames+1'b1;
                end else gap_count<=gap_count+1'b1;
            end
            if(rx_bad) begin index<=0;if(bad_frames!=32'hffff_ffff)bad_frames<=bad_frames+1'b1;end
            if(rx_valid) begin
                gap_count<=0;
                case(index)
                    0:if(rx_byte==8'hc3)begin frame[7:0]<=rx_byte;index<=1;rx_crc<=crc_byte(16'hffff,rx_byte);end
                    1:if(rx_byte==8'h51)begin frame[15:8]<=rx_byte;index<=2;rx_crc<=crc_byte(rx_crc,rx_byte);end
                      else if(rx_byte==8'hc3)begin index<=1;rx_crc<=crc_byte(16'hffff,rx_byte);end
                      else index<=0;
                    13:begin
                        index<=0;
                        if({rx_byte,frame[12*8 +:8]}!=rx_crc)begin
                            if(bad_frames!=32'hffff_ffff)bad_frames<=bad_frames+1'b1;
                        end else if(busy)begin
                            if(busy_drops!=32'hffff_ffff)busy_drops<=busy_drops+1'b1;
                        end else begin
                            packet_sequence<=frame[4*8 +:16];packet_address<=frame[6*8 +:16];packet_op<=frame[3*8 +:8];
                            if(frame[2*8 +:8]!=1 || frame[3*8 +:8]>1)begin
                                if(bad_frames!=32'hffff_ffff)bad_frames<=bad_frames+1'b1;
                                reply<={16'd0,8'd0,frame[3*8 +:8],32'd0,frame[6*8 +:16],frame[4*8 +:16],8'd1,8'd1,8'h52,8'hc3};
                                preparing<=1;prep_index<=0;reply_crc<=16'hffff;
                            end else begin
                                address<=frame[6*8 +:16];write_data<=frame[8*8 +:32];write_en<=frame[3*8];req<=1;waiting<=1;
                            end
                        end
                    end
                    default:begin
                        frame[index*8 +:8]<=rx_byte;
                        if(index<12)rx_crc<=crc_byte(rx_crc,rx_byte);
                        index<=index+1'b1;
                    end
                endcase
            end
            if(waiting && response)begin
                waiting<=0;preparing<=1;prep_index<=0;reply_crc<=16'hffff;
                reply<={16'd0,8'd0,packet_op,read_data,packet_address,packet_sequence,error,8'd1,8'h52,8'hc3};
            end
            if(preparing)begin
                reply_crc<=crc_after_byte;
                if(prep_index==13)begin reply[127:112]<=crc_after_byte;preparing<=0;ready<=1;end
                else prep_index<=prep_index+1'b1;
            end
            if(!tx_active)begin
                tx<=1;
                if(ready && !dbg_busy)begin
                    ready<=0;tx_active<=1;tx_index<=0;tx_bit<=0;tx_count<=BT-1;tx<=0;
                end
            end else if(tx_count!=0)tx_count<=tx_count-1'b1;
            else begin
                tx_count<=BT-1;
                if(tx_bit<8)begin tx<=reply[tx_index*8+tx_bit];tx_bit<=tx_bit+1'b1;end
                else if(tx_bit==8)begin tx<=1;tx_bit<=9;end
                else if(tx_index==15)begin tx<=1;tx_active<=0;end
                else begin tx_index<=tx_index+1'b1;tx_bit<=0;tx<=0;end
            end
        end
    end
endmodule
