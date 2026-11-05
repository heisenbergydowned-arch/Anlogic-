`timescale 1ns / 1ps

/*******************************MILIANKE*******************************
*Company : MiLianKe Electronic Technology Co., Ltd.
*WebSite:https://www.milianke.com
*TechWeb:https://www.uisrc.com
*tmall-shop:https://milianke.tmall.com
*jd-shop:https://milianke.jd.com
*taobao-shop1: https://milianke.taobao.com
*Create Date: 2021/10/15
*File Name: uidelay.v
*Description: 
*Declaration:
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
*4) _n activ low
*5) _dg debug signal 
*6) _r delay or register
*7) _s state mechine
*********************************************************************/
module uidelay#
(
	integer num = 100000000
)(
input  I_clk,
input  I_rstn,
output O_rst
);

reg[31:0] cnt = 32'd0;
reg rst_d0;

/*count for clock*/
always@(posedge I_clk or negedge I_rstn)begin 
    if(!I_rstn)
       cnt<=32'd0; 
    else if(cnt < num)
	   cnt <= cnt + 1'b1;
end

/*generate output signal*/
always@(posedge I_clk or negedge I_rstn)begin
    if(!I_rstn)
        rst_d0 <= 1'b0; 
    else 
	   rst_d0 <= ( cnt == num);
end	

assign O_rst = rst_d0;

endmodule

