/*****************************************************************
Company : MiLianKe Electronic Technology Co., Ltd.
WebSite:https://www.milianke.com
TechWeb:https://www.uisrc.com
tmall-shop:https://milianke.tmall.com
jd-shop:https://milianke.jd.com
taobao-shop: https://milianke.taobao.com
Description: 
The reference demo provided by Milianke is only used for learning. 
We cannot ensure that the demo itself is free of bugs, so users 
should be responsible for the technical problems and consequences
caused by the use of their own products.
@Author      :   XiaoQingquan 
@Time        :   2024/10/09 
version:     :   1.0
@Description :   divide
*****************************************************************/
`timescale 1ns / 1ps
module divide#(
   parameter I_W = 32,
   parameter D_W = 9
)(
    input  wire           I_clk   ,
    input  wire           I_rst_n ,		   
	input  wire           I_tvalid,   
    input  wire [I_W-1:0] dividend,  
    input  wire [D_W-1:0] divisor ,   	 
    output wire           O_tvalid,	  
    output wire [O_W-1:0] quotient,	
    output wire [D_W-1:0] remaind	
    );
    
    localparam O_W = I_W - D_W;
    localparam B_W = I_W + 1;
    genvar i;
    reg [D_W-1:0] divisor_buf [0:O_W+1];
    reg valid_buf [0:O_W+1];
    reg [B_W-1:0] dividend_buf [0:O_W+1];
    reg [O_W:0] quotient_buf [0:O_W+1];
    

    always @(*) begin
        dividend_buf[0] = {1'b0, dividend};
        divisor_buf[0] = divisor;
        valid_buf[0] = I_tvalid;
        quotient_buf[0] = 0;
    end    

   
    generate for(i=1;i<=(O_W+1);i=i+1)
	begin
    
    always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
            dividend_buf[i] <= 'b0;
		    quotient_buf[i] <= 'b0;
        end else if(valid_buf[i-1]) begin 
            if(divisor_buf[i-1] == 'b0) begin 
               dividend_buf[i] <= 'b0;
		       quotient_buf[i] <= 'b0;
		    end else if(dividend_buf[i-1][B_W-1:O_W] >= {1'b0, divisor_buf[i-1]}) begin 
			   dividend_buf[i][B_W-1:O_W+1] <= dividend_buf[i-1][B_W-1:O_W] - divisor_buf[i-1];
			   dividend_buf[i][O_W:0] <= {dividend_buf[i-1][O_W-1:0], 1'b0};
			   quotient_buf[i] <= {quotient_buf[i-1][O_W:0],1'b1};
			end else begin
			   dividend_buf[i][B_W-1:O_W+1] <= dividend_buf[i-1][B_W-1:O_W];
			   dividend_buf[i][O_W:0] <= {dividend_buf[i-1][O_W-1:0], 1'b0};
			   quotient_buf[i] <= {quotient_buf[i-1][O_W:0],1'b0};
			end
        end else begin
            dividend_buf[i] <= 'b0;
		    quotient_buf[i] <= 'b0;        
        end
    end

    always @(posedge I_clk ) begin
        valid_buf[i] <= valid_buf[i-1];
        divisor_buf[i] <= divisor_buf[i-1];
    end    
    
    end
    endgenerate    
    
    assign O_tvalid = valid_buf[O_W+1];
    assign quotient = quotient_buf[O_W+1];
    assign remaind  = dividend_buf[O_W+1][B_W-1:O_W+1];
    
endmodule




