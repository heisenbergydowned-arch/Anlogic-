/*******************************MILIANKE*******************************
*Company : MiLianKe Electronic Technology Co., Ltd.
*WebSite:https://www.milianke.com
*TechWeb:https://www.uisrc.com
*tmall-shop:https://milianke.tmall.com
*jd-shop:https://milianke.jd.com
*taobao-shop1: https://milianke.taobao.com
*Create Date: 2023/03/23
*Module Name:
*File Name:
*Description: 
*The reference demo provided by Milianke is only used for learning. 
*We cannot ensure that the demo itself is free of bugs, so users 
*should be responsible for the technical problems and consequences
*caused by the use of their own products.
*Copyright: Copyright (c) MiLianKe
*All rights reserved.
*Revision: 1.0
*Signal description
*1) I_ input
*2) O_ output
*3) IO_ input output
*4) S_ system internal signal
*5) _n activ low
*6) _dg debug signal 
*7) _r delay or register
*8) _s state mechine
*********************************************************************/
/*********csi_unpacket_4lane MIPI CSI解码***********
--版本号1.0
--MIPI IP数据解码为32bit数据输出给下一级使用，这里需要了解MIPI协议的数据格式
*********************************************************************/

module csi_unpacket_4lane (
    input wire       I_clk,
    input wire       I_rst_n,

    input wire       I_hs_valid,
    input wire[31:0] I_hs_data,

    output reg       O_csi_frame_start,
    output reg       O_csi_frame_end,
    output reg       O_csi_valid,
    output reg[31:0] O_csi_data
);

    localparam FRAME_DATA_DT  = 8'h2B;   ///RAW10
    localparam FRAME_START_DT = 8'h00;
    localparam FRAME_END_DT   = 8'h01;

    reg        S_hs_valid_1d;          
    reg[31:0]  S_hs_data_1d;               
    wire       S_head_en;       
    wire[31:0] S_packet_head_data;     
    reg[15:0]  S_data_length;          
    reg        S_data_en;              
    reg[15:0]  S_data_en_cnt;          

    always @(posedge I_clk) begin
        S_hs_valid_1d        <= I_hs_valid;
        S_hs_data_1d         <= I_hs_data;
    end

    assign S_head_en = ~S_hs_valid_1d & I_hs_valid;


    assign S_packet_head_data = S_head_en ? I_hs_data : 'd0;


    always @(posedge I_clk) begin
        if(S_head_en && S_packet_head_data[31:24] == FRAME_START_DT)
            O_csi_frame_start <= 1'b1;
        else    
            O_csi_frame_start <= 1'b0;
    end


    always @(posedge I_clk) begin
        if(S_head_en && S_packet_head_data[31:24] == FRAME_END_DT)
            O_csi_frame_end <= 1'b1;
        else    
            O_csi_frame_end <= 1'b0;
    end


    always @(posedge I_clk) begin 
        if(I_hs_valid)
            begin
                if(S_head_en && S_packet_head_data[31:24] == FRAME_DATA_DT)
                    S_data_length <= {S_packet_head_data[15:8],S_packet_head_data[23:16]} >> 2;
                else    
                    S_data_length <= S_data_length;
            end
        else    
            S_data_length <= 'd0;
    end

    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n)
            S_data_en <= 1'b0;
        else    
            if(S_head_en && S_packet_head_data[31:24] == FRAME_DATA_DT)
                S_data_en <= 1'b1;
            else if(S_data_en_cnt == S_data_length-1)
                S_data_en <= 1'b0;
            else    
                S_data_en <= S_data_en;
    end

    always @(posedge I_clk) begin
        if(S_data_en)
            S_data_en_cnt <= S_data_en_cnt + 'd1;
        else
            S_data_en_cnt <= 'd0;
    end


    always @(posedge I_clk) begin
        if(S_data_en)
            begin
                O_csi_valid <= 1'b1;
                O_csi_data  <= I_hs_data;
            end
        else
            begin
                O_csi_valid <= 1'b0;
                O_csi_data  <= 'd0;
            end
    end

    
endmodule