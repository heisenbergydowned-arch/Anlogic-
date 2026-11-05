/*******************************MILIANKE*******************************
*Company : MiLianKe Electronic Technology Co., Ltd.
*WebSite:https://www.milianke.com
*TechWeb:https://www.uisrc.com
*tmall-shop:https://milianke.tmall.com
*jd-shop:https://milianke.jd.com
*taobao-shop1: https://milianke.taobao.com
*Create Date: 2023/03/23
*Module Name:hdmi_tx
*File Name:hdmi_tx.v
*Description: 
*The reference demo provided by Milianke is only used for learning. 
*We cannot ensure that the demo itself is free of bugs, so users 
*should be responsible for the technical problems and consequences
*caused by the use of their own products.
*Copyright: Copyright (c) MiLianKe
*All rights reserved.
*Revision: 1.1
*Signal description
*1) _i input
*2) _o output
*3) _n activ low
*4) _dg debug signal 
*5) _r delay or register
*6) _s state mechine
*********************************************************************/
/********************************************************************
本IP由上海安路科技提供，米联客根据自己使用习惯接口部分增加了RGB输入接口方式，
核心功能描述如下：
HDMI Transmitter工作需要两个时钟，像素时钟pixel_clk和串行发送时钟serial_clk。两个时钟都是通过PLL生成，其中serial_clk的频率是pixel_clk频率的五倍。
HDMI Transmitter的三个接口EDID_Read_interface、Video_interface和Audio_interface都是工作在pixel_clk时钟域下，因此用户逻辑需要使用pixel_clk来生成音视频数据。
HDMI Transmitter的pixel_clk频率和serial_clk频率需要根据显示分辨率进行计算。以1080p60的分辨率为例，有效分辨率为1920x1080，在计算频率的时候需要加上消隐区，
图像总的长宽为2200x1125，每秒60帧，因此像素时钟的频率为：
F_pixel=Htotal×Vtotal×FrameRate
F_pixel=2200×1125×60=148500000Hz=148.5MHz
串行发送时钟serial_clk频率为像素时钟频率的五倍，因此串行发送时钟频率为：
F_serial=5×F_pixel=5×148.5MHz=742.5MHz

1-最高支持1080p60显示分辨率。
2-支持两路音频输入。
3-支持RGB444和YUV444。
4-支持内部视频测试源。
5-支持EDID读取。
*********************************************************************/
`timescale 1ns / 1ns //仿真时间刻度/精度


module uihdmi_tx#(
    parameter DEVICE            = "DR1"//"EF2","EF3","EF4","SF1","EG","PH1A","PH1P","DR1","PH2A"
)
(
    
    input wire       I_pixel_clk, //像素时钟
    input wire       I_serial_clk,//串行发送时钟
    input wire       I_rst, //异步复位信号，高电平有效
    input wire[23:0] I_video_in_data,   //视频输入数据
    input wire       I_video_in_de,     //输入de有效
    input wire       I_video_in_vs,     //输入VS 帧同步
    input wire       I_video_in_hs,     //输入hS 帧同步
    output           O_hdmi_clk_p, //HDMI输出时钟P端
    output    [2:0]  O_hdmi_tx_p  //HDMI输出数据P端

);
reg [23:0] r_video_in_data;
always @(posedge I_pixel_clk) r_video_in_data <= I_video_in_data;
  
  
    wire[9:0]   S_ch0_tmds_code_data;               
    wire[9:0]   S_ch1_tmds_code_data;               
    wire[9:0]   S_ch2_tmds_code_data;               
    wire[9:0]   S_clk_tmds_code_data;

    hdmi_tx_controller_wrapper u_hdmi_tx_controller_wrapper(
        .I_pixel_clk          (I_pixel_clk          ),
        .I_rst                (I_rst                ),
        .I_video_in_data      (r_video_in_data      ),
        .I_video_in_vs        (I_video_in_vs        ),
        .I_video_in_hs        (I_video_in_hs        ),
        .I_video_in_de        (I_video_in_de        ),
        .O_ch0_tmds_code_data ( S_ch0_tmds_code_data ),
        .O_ch1_tmds_code_data ( S_ch1_tmds_code_data ),
        .O_ch2_tmds_code_data ( S_ch2_tmds_code_data ),
        .O_clk_tmds_code_data ( S_clk_tmds_code_data )
    );
    
    hdmi_tx_phy_wrapper  #(
        .DEVICE ( DEVICE )  //"EF2","EF3","EF4","SF1","EG","PH1A","PH1P","DR1"
    )u_hdmi_tx_phy_wrapper(
        .I_pixel_clk        ( I_pixel_clk          ),
        .I_serial_clk       ( I_serial_clk         ),
        .I_rst              ( I_rst                ),

        .I_tmds_channel_0   ( S_ch0_tmds_code_data ),
        .I_tmds_channel_1   ( S_ch1_tmds_code_data ),
        .I_tmds_channel_2   ( S_ch2_tmds_code_data ),
        .I_tmds_channel_clk ( S_clk_tmds_code_data ),

        .O_tmds_ch0_p       ( O_hdmi_tx_p[0]       ),
        .O_tmds_ch1_p       ( O_hdmi_tx_p[1]       ),
        .O_tmds_ch2_p       ( O_hdmi_tx_p[2]       ),
        .O_tmds_clk_p       ( O_hdmi_clk_p         )
    );



endmodule