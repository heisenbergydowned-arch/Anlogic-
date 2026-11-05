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
@Time        :   2024/09/28 
version:     :   1.0
@Description :       
    Y = 0.2989*R + 0.5870*G + 0.1140*B;
    R_new = -Y * value + R * (1+value);
    G_new = -Y * value + G * (1+value);
    B_new = -Y * value + B * (1+value);
    value = (-1~1) 
*****************************************************************/
`timescale 1ns / 1ps

module Saturation_adj#(
parameter [8:0]  ADJUST_VAL = 128
)  
(
    input                   I_clk  ,
    input                   I_rst_n,
    input                   I_tlast ,
    input                   I_tuser ,
    input  [95:0]           I_tdata ,
    input                   I_tvalid, 
    output                  I_tready,

    output                  O_tlast ,
    output                  O_tuser ,
    output [95:0]           O_tdata ,
    output                  O_tvalid,
    input                   O_tready
);
  
/*****************************************************************
                        24deta to RGB888                                        
*****************************************************************/

    wire [23:0] I_tdata_r1 = I_tdata[23:0] ;
    wire [23:0] I_tdata_r2 = I_tdata[47:24];
    wire [23:0] I_tdata_r3 = I_tdata[71:48];
    wire [23:0] I_tdata_r4 = I_tdata[95:72];

    wire [7:0]  rgb888_r[3:0];
    wire [7:0]  rgb888_g[3:0];
    wire [7:0]  rgb888_b[3:0];

    assign   rgb888_r[0] = I_tdata_r1[16+:8];
    assign   rgb888_g[0] = I_tdata_r1[8+:8] ;
    assign   rgb888_b[0] = I_tdata_r1[0+:8] ;

    assign   rgb888_r[1] = I_tdata_r2[16+:8];
    assign   rgb888_g[1] = I_tdata_r2[8+:8] ;
    assign   rgb888_b[1] = I_tdata_r2[0+:8] ;

    assign   rgb888_r[2] = I_tdata_r3[16+:8];
    assign   rgb888_g[2] = I_tdata_r3[8+:8] ;
    assign   rgb888_b[2] = I_tdata_r3[0+:8] ;

    assign   rgb888_r[3] = I_tdata_r4[16+:8];
    assign   rgb888_g[3] = I_tdata_r4[8+:8] ;
    assign   rgb888_b[3] = I_tdata_r4[0+:8] ;

/*****************************************************************
                        signals declaration                                          
*****************************************************************/
    wire [8:0]   adjust_val[3:0];

    assign adjust_val[0] = ADJUST_VAL;
    assign adjust_val[1] = ADJUST_VAL;
    assign adjust_val[2] = ADJUST_VAL;
    assign adjust_val[3] = ADJUST_VAL;
    
    reg  [3:0]   I_tlast_r ;
    reg  [3:0]   I_tuser_r ;
    reg  [3:0]   I_tvalid_r;

    reg  [16:0]  Y_R_m[3:0];
    reg  [17:0]  Y_G_m[3:0];
    reg  [14:0]  Y_B_m[3:0];

    reg  [7:0]   rgb888_r_r0[3:0];
    reg  [7:0]   rgb888_g_r0[3:0];
    reg  [7:0]   rgb888_b_r0[3:0];
    reg  [8:0]   RGB_C[3:0];
    
    wire [17:0]  Y_w[3:0];
    reg  [7:0]   Y[3:0];


    reg  [7:0]   rgb888_r_r1[3:0];
    reg  [7:0]   rgb888_g_r1[3:0];
    reg  [7:0]   rgb888_b_r1[3:0];

    reg          Y_C_sign[3:0];
    reg  [7:0]   Y_C_abs[3:0];


    reg  [16:0]   Y_m[3:0];

    reg  [16:0]   rgb888_r_r2[3:0];
    reg  [16:0]   rgb888_g_r2[3:0];
    reg  [16:0]   rgb888_b_r2[3:0];

    wire [18:0] Y_m_s[3:0];
    wire [18:0] Y_R_m_s[3:0];
    wire [18:0] Y_G_m_s[3:0];
    wire [18:0] Y_B_m_s[3:0];

    reg  [7:0]  R_new[3:0];
    reg  [7:0]  G_new[3:0];
    reg  [7:0]  B_new[3:0];
    


    parameter C0 = 9'd306;//0.299*1024;
    parameter C1 = 10'd601;//0.587*1024;
    parameter C2 = 7'd117;//0.114*1024;

/*****************************************************************
                    computing declaration                                          
*****************************************************************/

    genvar i;
    generate
        for(i = 0; i < 4; i = i + 1)
        begin: computing
        //Y=0.299*Rʮ0.587*G+0.114*B
        always @(posedge I_clk or negedge I_rst_n) begin
            if(!I_rst_n) begin
                {Y_R_m[i], Y_G_m[i], Y_B_m[i]} <= 0;
                {rgb888_r_r0[i], rgb888_g_r0[i], rgb888_b_r0[i]} <= 0;
                RGB_C[i] <= 0;
            end 
            else if(I_tvalid)begin
                Y_R_m[i] <= rgb888_r[i]*C0;
                Y_G_m[i] <= rgb888_g[i]*C1;
                Y_B_m[i] <= rgb888_b[i]*C2;
                {rgb888_r_r0[i], rgb888_g_r0[i], rgb888_b_r0[i]} <= {rgb888_r[i], rgb888_g[i], rgb888_b[i]};
                RGB_C[i] <= 255 + adjust_val[i];
            end
        end
        assign Y_w[i] = Y_R_m[i] + Y_G_m[i] + Y_B_m[i];
    
    
        always @(posedge I_clk or negedge I_rst_n) begin
            if(!I_rst_n) begin
                Y[i] <= 0;
                {rgb888_r_r1[i], rgb888_g_r1[i], rgb888_b_r1[i]} <= 0;
                {Y_C_sign[i], Y_C_abs[i]} <= 0;
            end 
            else if(I_tvalid_r[0])begin
                Y[i] <= Y_w[i][17:10];
                {rgb888_r_r1[i], rgb888_g_r1[i], rgb888_b_r1[i]} <= {rgb888_r_r0[i], rgb888_g_r0[i], rgb888_b_r0[i]};
                Y_C_sign[i] <= adjust_val[i][8];
                Y_C_abs[i] <= adjust_val[i][8] ? (~adjust_val[i][7:0] + 1) : adjust_val[i];//判断正负，然后去计算
            end
        end   
    
        always @(posedge I_clk or negedge I_rst_n) begin
            if(!I_rst_n) begin
                Y_m[i] <= 0;
                {rgb888_r_r2[i], rgb888_g_r2[i], rgb888_b_r2[i]} <= 0;
            end 
            else if(I_tvalid_r[1])begin
                Y_m[i] <= Y[i]*Y_C_abs[i];
                rgb888_r_r2[i] <= rgb888_r_r1[i]*RGB_C[i];
                rgb888_g_r2[i] <= rgb888_g_r1[i]*RGB_C[i];
                rgb888_b_r2[i] <= rgb888_b_r1[i]*RGB_C[i];
            end
        end
        
        assign Y_m_s[i] = (~Y_C_sign[i]) ? (~{2'b0, Y_m[i]} + 1) : {2'b0, Y_m[i]};
    
        assign Y_R_m_s[i] = Y_m_s[i] + rgb888_r_r2[i];
        assign Y_G_m_s[i] = Y_m_s[i] + rgb888_g_r2[i];
        assign Y_B_m_s[i] = Y_m_s[i] + rgb888_b_r2[i];
    
        always @(posedge I_clk or negedge I_rst_n) begin
            if(!I_rst_n) begin
                {R_new[i], G_new[i], B_new[i]} <= 0;
            end 
            else if(I_tvalid_r[2])begin
                R_new[i] <= Y_R_m_s[i][18] ? 0 : Y_R_m_s[i][17:16] > 0 ? 255 : Y_R_m_s[i][15:8];
                G_new[i] <= Y_G_m_s[i][18] ? 0 : Y_G_m_s[i][17:16] > 0 ? 255 : Y_G_m_s[i][15:8];
                B_new[i] <= Y_B_m_s[i][18] ? 0 : Y_B_m_s[i][17:16] > 0 ? 255 : Y_B_m_s[i][15:8];
            end
        end       
        end
    endgenerate
    
/*****************************************************************
                    synchronization signal                                         
*****************************************************************/

    always @(posedge I_clk or negedge I_rst_n) begin
        if(!I_rst_n) 
            {I_tlast_r,I_tuser_r,I_tvalid_r} <= 0;
        else begin
            I_tlast_r <= {I_tlast_r[2:0],I_tlast};
            I_tuser_r <= {I_tuser_r[2:0],I_tuser};
            I_tvalid_r <= {I_tvalid_r[2:0],I_tvalid};
        end
    end


    assign  O_tlast  = I_tlast_r[3];   
    assign  O_tuser  = I_tuser_r[3];   
    assign  O_tvalid = I_tvalid_r[3];

    assign  O_tdata = {R_new[3],G_new[3],B_new[3],
                       R_new[2],G_new[2],B_new[2],
                       R_new[1],G_new[1],B_new[1],
                       R_new[0],G_new[0],B_new[0]};
    // RGB88转RGB565
    // assign O_st_data = {R_new[7-:5],G_new[7-:6],B_new[7-:5]};
    assign  I_tready = O_tready;

endmodule
