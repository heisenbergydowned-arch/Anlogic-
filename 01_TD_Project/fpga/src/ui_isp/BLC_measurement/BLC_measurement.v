/*****************************************************************
Company : Nanjing Weiku Robot Technology Co., Ltd.
Brand   : VLKUS
Technical forum:www.uisrc.com
@Author      :   XiaoQingquan 
@Time        :   2024/09/10 
@Description :   ISP_black_level_correction(黑电平矫�???)_measurement
*****************************************************************/
`timescale 1ns / 1ps

module BLC_measurement #(
    parameter [13:0] Width       = 1920,
    parameter [13:0] Height      = 1080,
    parameter [13:0] Width_div4  = 480 ,
    parameter [7:0]  FRAME_COUNT = 30
)
(
    input                   I_clk  ,
    input                   I_rst_n,

    input                   I_tlast   ,
    input                   I_tuser   ,
    input  [39:0]           I_tdata   ,
    input                   I_tvalid  , 
    input  [9:0]            I_tdest   ,
    output                  I_tready  ,
    output reg [20:0]       pixel_count_r,
    output [9:0]            I_blc_data_r0,
    output [9:0]            I_blc_data_r1,
    output [9:0]            I_blc_data_r2,
    output [9:0]            I_blc_data_r3,
    output [9:0]            black_level_offset_r0,
    output [9:0]            black_level_offset_r1,   
    output [9:0]            black_level_offset_r2,
    output [9:0]            black_level_offset_r3             
);

/*****************************************************
                    ���ȼ���
*****************************************************/

// calculate the data's bit width
function integer clog2b(
    input integer width
);
    begin
        for(clog2b=0; width>0; clog2b=clog2b+1)begin
            width = width >> 1;
        end
    end    
endfunction


/*****************************************************
                    measurement
*****************************************************/
    localparam IMAGE_PIXEL_SUM      = FRAME_COUNT*(Height*Width_div4);//30�??
    assign     I_blc_data_r0 = I_tdata[9:0]  ;
    assign     I_blc_data_r1 = I_tdata[19:10];
    assign     I_blc_data_r2 = I_tdata[29:20];
    assign     I_blc_data_r3 = I_tdata[39:30];
    reg        [31:0]   pixel_count;

    reg        [35:0]   measurement_data[3:0];
    // 在时钟上升沿或复位信号有效时触发
    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            pixel_count <= 'd0;
            measurement_data[0] <= 'd0;
            measurement_data[1] <= 'd0;
            measurement_data[2] <= 'd0;
            measurement_data[3] <= 'd0;
            pixel_count_r <= 0;
        end 
        else if(I_tuser)
            pixel_count_r <= 0;
        else if(pixel_count > IMAGE_PIXEL_SUM)begin
            pixel_count <= 'd0;
            measurement_data[0] <= 'd0;
            measurement_data[1] <= 'd0;
            measurement_data[2] <= 'd0;
            measurement_data[3] <= 'd0;
        end
        else if(I_tvalid)begin
            pixel_count_r <= pixel_count_r + 1;
            pixel_count <= pixel_count + 1;
            measurement_data[0] <= measurement_data[0] + I_tdata[9:0]  ;
            measurement_data[1] <= measurement_data[1] + I_tdata[19:10];
            measurement_data[2] <= measurement_data[2] + I_tdata[29:20];
            measurement_data[3] <= measurement_data[3] + I_tdata[39:30];
        end
    end


    wire    [79:0] avg_data_r0[3:0];
    wire    [47:0] avg_data_r1[3:0];
    assign  avg_data_r1[0] = avg_data_r0[0][79:32];
    assign  avg_data_r1[1] = avg_data_r0[1][79:32];
    assign  avg_data_r1[2] = avg_data_r0[2][79:32];
    assign  avg_data_r1[3] = avg_data_r0[3][79:32];
    assign  black_level_offset_r0 = (avg_data_r1[0][47:22])?10'd1023 : avg_data_r1[0][21:12] ;
    assign  black_level_offset_r1 = (avg_data_r1[1][47:22])?10'd1023 : avg_data_r1[1][21:12] ;
    assign  black_level_offset_r2 = (avg_data_r1[2][47:22])?10'd1023 : avg_data_r1[2][21:12] ;
    assign  black_level_offset_r3 = (avg_data_r1[3][47:22])?10'd1023 : avg_data_r1[3][21:12] ;

    genvar i;
    generate for(i=0;i<4;i=i+1)
        begin:min_avg
    div_blc min_avg (
      .aclk(I_clk),                                      // input wire aclk
      .s_axis_divisor_tvalid(I_tvalid),    // input wire s_axis_divisor_tvalid
      .s_axis_divisor_tdata(pixel_count),      // input wire [31 : 0] s_axis_divisor_tdata
      .s_axis_dividend_tvalid(I_tvalid),  // input wire s_axis_dividend_tvalid
      .s_axis_dividend_tdata({measurement_data[i],12'd0}),    // input wire [47 : 0] s_axis_dividend_tdata
      .m_axis_dout_tvalid(),          // output wire m_axis_dout_tvalid
      .m_axis_dout_tdata(avg_data_r0[i])            // output wire [79 : 0] m_axis_dout_tdata
    );
        end
    endgenerate
    
    
    
    
endmodule
