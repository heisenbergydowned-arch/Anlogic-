/*****************************************************************
Company : Nanjing Weiku Robot Technology Co., Ltd.
Brand   : VLKUS
Technical forum:www.uisrc.com
@Author      :   XiaoQingquan 
@Time        :   2024/08/23 
@Description :   ISP  gamma(伽马矫正)
*****************************************************************/
module gamma #(
    parameter [4:0] GAMMA_10x = 22
) (
    input wire I_clk,
    input wire I_rst_n,

    input  wire        I_tlast,
    input  wire        I_tuser,
    input  wire [95:0] I_tdata,
    input  wire        I_tvalid,
    output wire        I_tready,

    output wire        O_tlast,
    output wire        O_tuser,
    output wire [95:0] O_tdata,
    output wire        O_tvalid,
    input  wire        O_tready
);

  /*****************************************************************
                        24deta to RGB888                                        
*****************************************************************/

  wire [23:0] I_tdata_r1 = I_tdata[23:0];
  wire [23:0] I_tdata_r2 = I_tdata[47:24];
  wire [23:0] I_tdata_r3 = I_tdata[71:48];
  wire [23:0] I_tdata_r4 = I_tdata[95:72];

  wire [7:0] rgb888_r[3:0];
  wire [7:0] rgb888_g[3:0];
  wire [7:0] rgb888_b[3:0];

  assign rgb888_r[0] = I_tdata_r1[16+:8];
  assign rgb888_g[0] = I_tdata_r1[8+:8];
  assign rgb888_b[0] = I_tdata_r1[0+:8];

  assign rgb888_r[1] = I_tdata_r2[16+:8];
  assign rgb888_g[1] = I_tdata_r2[8+:8];
  assign rgb888_b[1] = I_tdata_r2[0+:8];

  assign rgb888_r[2] = I_tdata_r3[16+:8];
  assign rgb888_g[2] = I_tdata_r3[8+:8];
  assign rgb888_b[2] = I_tdata_r3[0+:8];

  assign rgb888_r[3] = I_tdata_r4[16+:8];
  assign rgb888_g[3] = I_tdata_r4[8+:8];
  assign rgb888_b[3] = I_tdata_r4[0+:8];

  /*****************************************************************
                    wire signals declaration                                       
*****************************************************************/

  wire [11:0] O_LUT_2_6_data_r[3:0];
  wire [11:0] O_LUT_2_6_data_g[3:0];
  wire [11:0] O_LUT_2_6_data_b[3:0];


  wire [11:0] O_LUT_2_4_data_r[3:0];
  wire [11:0] O_LUT_2_4_data_g[3:0];
  wire [11:0] O_LUT_2_4_data_b[3:0];


  wire [11:0] O_LUT_2_2_data_r[3:0];
  wire [11:0] O_LUT_2_2_data_g[3:0];
  wire [11:0] O_LUT_2_2_data_b[3:0];


  wire [11:0] O_LUT_2_0_data_r[3:0];
  wire [11:0] O_LUT_2_0_data_g[3:0];
  wire [11:0] O_LUT_2_0_data_b[3:0];


  wire [11:0] O_LUT_1_8_data_r[3:0];
  wire [11:0] O_LUT_1_8_data_g[3:0];
  wire [11:0] O_LUT_1_8_data_b[3:0];


  wire [11:0] O_LUT_1_6_data_r[3:0];
  wire [11:0] O_LUT_1_6_data_g[3:0];
  wire [11:0] O_LUT_1_6_data_b[3:0];


  wire [11:0] O_LUT_1_4_data_r[3:0];
  wire [11:0] O_LUT_1_4_data_g[3:0];
  wire [11:0] O_LUT_1_4_data_b[3:0];


  wire [11:0] O_LUT_1_2_data_r[3:0];
  wire [11:0] O_LUT_1_2_data_g[3:0];
  wire [11:0] O_LUT_1_2_data_b[3:0];


  wire [11:0] O_LUT_0_8_data_r[3:0];
  wire [11:0] O_LUT_0_8_data_g[3:0];
  wire [11:0] O_LUT_0_8_data_b[3:0];


  wire [7:0] R_new[3:0];
  wire [7:0] G_new[3:0];
  wire [7:0] B_new[3:0];



  /*****************************************************************
                    reg signals declaration                                       
*****************************************************************/

  reg [11:0] acc_rgb888_r[3:0];
  reg [11:0] acc_rgb888_g[3:0];
  reg [11:0] acc_rgb888_b[3:0];


  reg [3:0] I_tlast_r;
  reg [3:0] I_tuser_r;
  reg [3:0] I_tvalid_r;


  reg [20:0] acc_rgb888_r_x0[3:0];
  reg [20:0] acc_rgb888_g_x0[3:0];
  reg [20:0] acc_rgb888_b_x0[3:0];


  reg [20:0] acc_rgb888_r_x1[3:0];
  reg [20:0] acc_rgb888_g_x1[3:0];
  reg [20:0] acc_rgb888_b_x1[3:0];


  reg [7:0] acc_rgb888_r_x2[3:0];
  reg [7:0] acc_rgb888_g_x2[3:0];
  reg [7:0] acc_rgb888_b_x2[3:0];


  /*****************************************************************
                       Gamma SIZE                                       
*****************************************************************/
  genvar i;
  generate
    for (i = 0; i < 4; i = i + 1) begin : LUT
      lut_2_6 lut_2_6_R (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_2_6_data(rgb888_r[i]),
          /*output [11:0]     */.O_LUT_2_6_data(O_LUT_2_6_data_r[i])
      );

      lut_2_6 lut_2_6_G (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_2_6_data(rgb888_g[i]),
          /*output [11:0]     */.O_LUT_2_6_data(O_LUT_2_6_data_g[i])
      );
      lut_2_6 lut_2_6_B (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_2_6_data(rgb888_b[i]),
          /*output [11:0]     */.O_LUT_2_6_data(O_LUT_2_6_data_b[i])
      );


      lut_2_4 lut_2_4_R (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_2_4_data(rgb888_r[i]),
          /*output [11:0]     */.O_LUT_2_4_data(O_LUT_2_4_data_r[i])
      );

      lut_2_4 lut_2_4_G (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_2_4_data(rgb888_g[i]),
          /*output [11:0]     */.O_LUT_2_4_data(O_LUT_2_4_data_g[i])
      );
      lut_2_4 lut_2_4_B (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_2_4_data(rgb888_b[i]),
          /*output [11:0]     */.O_LUT_2_4_data(O_LUT_2_4_data_b[i])
      );



      lut_2_2 lut_2_2_R (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_2_2_data(rgb888_r[i]),
          /*output [11:0]     */.O_LUT_2_2_data(O_LUT_2_2_data_r[i])
      );

      lut_2_2 lut_2_2_G (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_2_2_data(rgb888_g[i]),
          /*output [11:0]     */.O_LUT_2_2_data(O_LUT_2_2_data_g[i])
      );
      lut_2_2 lut_2_2_B (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_2_2_data(rgb888_b[i]),
          /*output [11:0]     */.O_LUT_2_2_data(O_LUT_2_2_data_b[i])
      );



      lut_2_0 lut_2_0_R (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_2_0_data(rgb888_r[i]),
          /*output [11:0]     */.O_LUT_2_0_data(O_LUT_2_0_data_r[i])
      );

      lut_2_0 lut_2_0_G (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_2_0_data(rgb888_g[i]),
          /*output [11:0]     */.O_LUT_2_0_data(O_LUT_2_0_data_g[i])
      );

      lut_2_0 lut_2_0_B (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_2_0_data(rgb888_b[i]),
          /*output [11:0]     */.O_LUT_2_0_data(O_LUT_2_0_data_b[i])
      );




      lut_1_8 lut_1_8_R (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_1_8_data(rgb888_r[i]),
          /*output [11:0]     */.O_LUT_1_8_data(O_LUT_1_8_data_r[i])
      );
      lut_1_8 lut_1_8_G (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_1_8_data(rgb888_g[i]),
          /*output [11:0]     */.O_LUT_1_8_data(O_LUT_1_8_data_g[i])
      );

      lut_1_8 lut_1_8_B (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_1_8_data(rgb888_b[i]),
          /*output [11:0]     */.O_LUT_1_8_data(O_LUT_1_8_data_b[i])
      );




      lut_1_6 lut_1_6_R (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_1_6_data(rgb888_r[i]),
          /*output [11:0]     */.O_LUT_1_6_data(O_LUT_1_6_data_r[i])
      );

      lut_1_6 lut_1_6_G (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_1_6_data(rgb888_g[i]),
          /*output [11:0]     */.O_LUT_1_6_data(O_LUT_1_6_data_g[i])
      );

      lut_1_6 lut_1_6_B (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_1_6_data(rgb888_b[i]),
          /*output [11:0]     */.O_LUT_1_6_data(O_LUT_1_6_data_b[i])
      );




      lut_1_4 lut_1_4_R (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_1_4_data(rgb888_r[i]),
          /*output [11:0]     */.O_LUT_1_4_data(O_LUT_1_4_data_r[i])
      );

      lut_1_4 lut_1_4_G (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_1_4_data(rgb888_g[i]),
          /*output [11:0]     */.O_LUT_1_4_data(O_LUT_1_4_data_g[i])
      );

      lut_1_4 lut_1_4_B (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_1_4_data(rgb888_b[i]),
          /*output [11:0]     */.O_LUT_1_4_data(O_LUT_1_4_data_b[i])
      );




      lut_1_2 lut_1_2_R (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_1_2_data(rgb888_r[i]),
          /*output [11:0]     */.O_LUT_1_2_data(O_LUT_1_2_data_r[i])
      );

      lut_1_2 lut_1_2_G (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_1_2_data(rgb888_g[i]),
          /*output [11:0]     */.O_LUT_1_2_data(O_LUT_1_2_data_g[i])
      );

      lut_1_2 lut_1_2_B (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_1_2_data(rgb888_b[i]),
          /*output [11:0]     */.O_LUT_1_2_data(O_LUT_1_2_data_b[i])
      );




      lut_0_8 lut_0_8_R (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_0_8_data(rgb888_r[i]),
          /*output [11:0]     */.O_LUT_0_8_data(O_LUT_0_8_data_r[i])
      );

      lut_0_8 lut_0_8_G (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_0_8_data(rgb888_g[i]),
          /*output [11:0]     */.O_LUT_0_8_data(O_LUT_0_8_data_g[i])
      );

      lut_0_8 lut_0_8_B (
          /*input             */.I_clk         (I_clk),
          /*input             */.I_rst_n       (I_rst_n),
          /*input  [7:0]     */ .I_LUT_0_8_data(rgb888_b[i]),
          /*output [11:0]     */.O_LUT_0_8_data(O_LUT_0_8_data_b[i])
      );

    end
  endgenerate
  /*****************************************************************
                       select gamma                                      
*****************************************************************/

  always @(posedge I_clk or negedge I_rst_n) begin
    if (!I_rst_n) begin
      acc_rgb888_r[0] <= 12'd0;
      acc_rgb888_g[0] <= 12'd0;
      acc_rgb888_b[0] <= 12'd0;
      acc_rgb888_r[1] <= 12'd0;
      acc_rgb888_g[1] <= 12'd0;
      acc_rgb888_b[1] <= 12'd0;
      acc_rgb888_r[2] <= 12'd0;
      acc_rgb888_g[2] <= 12'd0;
      acc_rgb888_b[2] <= 12'd0;
      acc_rgb888_r[3] <= 12'd0;
      acc_rgb888_g[3] <= 12'd0;
      acc_rgb888_b[3] <= 12'd0;
    end else begin
      case (GAMMA_10x)
        5'd26: begin
          acc_rgb888_r[0] <= O_LUT_2_6_data_r[0];
          acc_rgb888_g[0] <= O_LUT_2_6_data_g[0];
          acc_rgb888_b[0] <= O_LUT_2_6_data_b[0];
          acc_rgb888_r[1] <= O_LUT_2_6_data_r[1];
          acc_rgb888_g[1] <= O_LUT_2_6_data_g[1];
          acc_rgb888_b[1] <= O_LUT_2_6_data_b[1];
          acc_rgb888_r[2] <= O_LUT_2_6_data_r[2];
          acc_rgb888_g[2] <= O_LUT_2_6_data_g[2];
          acc_rgb888_b[2] <= O_LUT_2_6_data_b[2];
          acc_rgb888_r[3] <= O_LUT_2_6_data_r[3];
          acc_rgb888_g[3] <= O_LUT_2_6_data_g[3];
          acc_rgb888_b[3] <= O_LUT_2_6_data_b[3];
        end
        5'd24: begin
          acc_rgb888_r[0] <= O_LUT_2_4_data_r[0];
          acc_rgb888_g[0] <= O_LUT_2_4_data_g[0];
          acc_rgb888_b[0] <= O_LUT_2_4_data_b[0];
          acc_rgb888_r[1] <= O_LUT_2_4_data_r[1];
          acc_rgb888_g[1] <= O_LUT_2_4_data_g[1];
          acc_rgb888_b[1] <= O_LUT_2_4_data_b[1];
          acc_rgb888_r[2] <= O_LUT_2_4_data_r[2];
          acc_rgb888_g[2] <= O_LUT_2_4_data_g[2];
          acc_rgb888_b[2] <= O_LUT_2_4_data_b[2];
          acc_rgb888_r[3] <= O_LUT_2_4_data_r[3];
          acc_rgb888_g[3] <= O_LUT_2_4_data_g[3];
          acc_rgb888_b[3] <= O_LUT_2_4_data_b[3];
        end
        5'd22: begin
          acc_rgb888_r[0] <= O_LUT_2_2_data_r[0];
          acc_rgb888_g[0] <= O_LUT_2_2_data_g[0];
          acc_rgb888_b[0] <= O_LUT_2_2_data_b[0];
          acc_rgb888_r[1] <= O_LUT_2_2_data_r[1];
          acc_rgb888_g[1] <= O_LUT_2_2_data_g[1];
          acc_rgb888_b[1] <= O_LUT_2_2_data_b[1];
          acc_rgb888_r[2] <= O_LUT_2_2_data_r[2];
          acc_rgb888_g[2] <= O_LUT_2_2_data_g[2];
          acc_rgb888_b[2] <= O_LUT_2_2_data_b[2];
          acc_rgb888_r[3] <= O_LUT_2_2_data_r[3];
          acc_rgb888_g[3] <= O_LUT_2_2_data_g[3];
          acc_rgb888_b[3] <= O_LUT_2_2_data_b[3];
        end
        5'd20: begin
          acc_rgb888_r[0] <= O_LUT_2_0_data_r[0];
          acc_rgb888_g[0] <= O_LUT_2_0_data_g[0];
          acc_rgb888_b[0] <= O_LUT_2_0_data_b[0];
          acc_rgb888_r[1] <= O_LUT_2_0_data_r[1];
          acc_rgb888_g[1] <= O_LUT_2_0_data_g[1];
          acc_rgb888_b[1] <= O_LUT_2_0_data_b[1];
          acc_rgb888_r[2] <= O_LUT_2_0_data_r[2];
          acc_rgb888_g[2] <= O_LUT_2_0_data_g[2];
          acc_rgb888_b[2] <= O_LUT_2_0_data_b[2];
          acc_rgb888_r[3] <= O_LUT_2_0_data_r[3];
          acc_rgb888_g[3] <= O_LUT_2_0_data_g[3];
          acc_rgb888_b[3] <= O_LUT_2_0_data_b[3];
        end
        5'd18: begin
          acc_rgb888_r[0] <= O_LUT_1_8_data_r[0];
          acc_rgb888_g[0] <= O_LUT_1_8_data_g[0];
          acc_rgb888_b[0] <= O_LUT_1_8_data_b[0];
          acc_rgb888_r[1] <= O_LUT_1_8_data_r[1];
          acc_rgb888_g[1] <= O_LUT_1_8_data_g[1];
          acc_rgb888_b[1] <= O_LUT_1_8_data_b[1];
          acc_rgb888_r[2] <= O_LUT_1_8_data_r[2];
          acc_rgb888_g[2] <= O_LUT_1_8_data_g[2];
          acc_rgb888_b[2] <= O_LUT_1_8_data_b[2];
          acc_rgb888_r[3] <= O_LUT_1_8_data_r[3];
          acc_rgb888_g[3] <= O_LUT_1_8_data_g[3];
          acc_rgb888_b[3] <= O_LUT_1_8_data_b[3];
        end
        5'd16: begin
          acc_rgb888_r[0] <= O_LUT_1_6_data_r[0];
          acc_rgb888_g[0] <= O_LUT_1_6_data_g[0];
          acc_rgb888_b[0] <= O_LUT_1_6_data_b[0];
          acc_rgb888_r[1] <= O_LUT_1_6_data_r[1];
          acc_rgb888_g[1] <= O_LUT_1_6_data_g[1];
          acc_rgb888_b[1] <= O_LUT_1_6_data_b[1];
          acc_rgb888_r[2] <= O_LUT_1_6_data_r[2];
          acc_rgb888_g[2] <= O_LUT_1_6_data_g[2];
          acc_rgb888_b[2] <= O_LUT_1_6_data_b[2];
          acc_rgb888_r[3] <= O_LUT_1_6_data_r[3];
          acc_rgb888_g[3] <= O_LUT_1_6_data_g[3];
          acc_rgb888_b[3] <= O_LUT_1_6_data_b[3];
        end
        5'd14: begin
          acc_rgb888_r[0] <= O_LUT_1_4_data_r[0];
          acc_rgb888_g[0] <= O_LUT_1_4_data_g[0];
          acc_rgb888_b[0] <= O_LUT_1_4_data_b[0];
          acc_rgb888_r[1] <= O_LUT_1_4_data_r[1];
          acc_rgb888_g[1] <= O_LUT_1_4_data_g[1];
          acc_rgb888_b[1] <= O_LUT_1_4_data_b[1];
          acc_rgb888_r[2] <= O_LUT_1_4_data_r[2];
          acc_rgb888_g[2] <= O_LUT_1_4_data_g[2];
          acc_rgb888_b[2] <= O_LUT_1_4_data_b[2];
          acc_rgb888_r[3] <= O_LUT_1_4_data_r[3];
          acc_rgb888_g[3] <= O_LUT_1_4_data_g[3];
          acc_rgb888_b[3] <= O_LUT_1_4_data_b[3];

        end
        5'd12: begin
          acc_rgb888_r[0] <= O_LUT_1_2_data_r[0];
          acc_rgb888_g[0] <= O_LUT_1_2_data_g[0];
          acc_rgb888_b[0] <= O_LUT_1_2_data_b[0];
          acc_rgb888_r[1] <= O_LUT_1_2_data_r[1];
          acc_rgb888_g[1] <= O_LUT_1_2_data_g[1];
          acc_rgb888_b[1] <= O_LUT_1_2_data_b[1];
          acc_rgb888_r[2] <= O_LUT_1_2_data_r[2];
          acc_rgb888_g[2] <= O_LUT_1_2_data_g[2];
          acc_rgb888_b[2] <= O_LUT_1_2_data_b[2];
          acc_rgb888_r[3] <= O_LUT_1_2_data_r[3];
          acc_rgb888_g[3] <= O_LUT_1_2_data_g[3];
          acc_rgb888_b[3] <= O_LUT_1_2_data_b[3];
        end
        5'd8: begin
          acc_rgb888_r[0] <= O_LUT_0_8_data_r[0];
          acc_rgb888_g[0] <= O_LUT_0_8_data_g[0];
          acc_rgb888_b[0] <= O_LUT_0_8_data_b[0];
          acc_rgb888_r[1] <= O_LUT_0_8_data_r[1];
          acc_rgb888_g[1] <= O_LUT_0_8_data_g[1];
          acc_rgb888_b[1] <= O_LUT_0_8_data_b[1];
          acc_rgb888_r[2] <= O_LUT_0_8_data_r[2];
          acc_rgb888_g[2] <= O_LUT_0_8_data_g[2];
          acc_rgb888_b[2] <= O_LUT_0_8_data_b[2];
          acc_rgb888_r[3] <= O_LUT_0_8_data_r[3];
          acc_rgb888_g[3] <= O_LUT_0_8_data_g[3];
          acc_rgb888_b[3] <= O_LUT_0_8_data_b[3];
        end
        default: begin
          acc_rgb888_r[0] <= O_LUT_2_2_data_r[0];
          acc_rgb888_g[0] <= O_LUT_2_2_data_g[0];
          acc_rgb888_b[0] <= O_LUT_2_2_data_b[0];
          acc_rgb888_r[1] <= O_LUT_2_2_data_r[1];
          acc_rgb888_g[1] <= O_LUT_2_2_data_g[1];
          acc_rgb888_b[1] <= O_LUT_2_2_data_b[1];
          acc_rgb888_r[2] <= O_LUT_2_2_data_r[2];
          acc_rgb888_g[2] <= O_LUT_2_2_data_g[2];
          acc_rgb888_b[2] <= O_LUT_2_2_data_b[2];
          acc_rgb888_r[3] <= O_LUT_2_2_data_r[3];
          acc_rgb888_g[3] <= O_LUT_2_2_data_g[3];
          acc_rgb888_b[3] <= O_LUT_2_2_data_b[3];
        end
      endcase
    end
  end

  /*****************************************************************
                       Anti normalization                                      
*****************************************************************/

  genvar t;
  generate
    for (t = 0; t < 4; t = t + 1) begin : Anti_normalization
      always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
          acc_rgb888_r_x0[t] <= 0;
          acc_rgb888_g_x0[t] <= 0;
          acc_rgb888_b_x0[t] <= 0;
        end else if (I_tvalid_r[0]) begin
          acc_rgb888_r_x0[t] <= acc_rgb888_r[t] << 8;
          acc_rgb888_g_x0[t] <= acc_rgb888_g[t] << 8;
          acc_rgb888_b_x0[t] <= acc_rgb888_b[t] << 8;
        end else begin
          acc_rgb888_r_x0[t] <= acc_rgb888_r_x0[t];
          acc_rgb888_g_x0[t] <= acc_rgb888_g_x0[t];
          acc_rgb888_b_x0[t] <= acc_rgb888_b_x0[t];
        end
      end



      always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
          acc_rgb888_r_x1[t] <= 0;
          acc_rgb888_g_x1[t] <= 0;
          acc_rgb888_b_x1[t] <= 0;
        end else if (I_tvalid_r[1]) begin
          acc_rgb888_r_x1[t] <= acc_rgb888_r_x0[t] - 2048;
          acc_rgb888_g_x1[t] <= acc_rgb888_g_x0[t] - 2048;
          acc_rgb888_b_x1[t] <= acc_rgb888_b_x0[t] - 2048;
        end else begin
          acc_rgb888_r_x1[t] <= acc_rgb888_r_x1[t];
          acc_rgb888_g_x1[t] <= acc_rgb888_g_x1[t];
          acc_rgb888_b_x1[t] <= acc_rgb888_b_x1[t];
        end
      end


      // limit  RGB
      always @(posedge I_clk or negedge I_rst_n) begin
        if (!I_rst_n) begin
          acc_rgb888_r_x2[t] <= 0;
          acc_rgb888_g_x2[t] <= 0;
          acc_rgb888_b_x2[t] <= 0;
        end else if (I_tvalid_r[2]) begin
          acc_rgb888_r_x2[t] <= (acc_rgb888_r_x1[t][20]) ? 8'd255 : (acc_rgb888_r_x1[t][19:12]);
          acc_rgb888_g_x2[t] <= (acc_rgb888_g_x1[t][20]) ? 8'd255 : (acc_rgb888_g_x1[t][19:12]);
          acc_rgb888_b_x2[t] <= (acc_rgb888_b_x1[t][20]) ? 8'd255 : (acc_rgb888_b_x1[t][19:12]);
        end else begin
          acc_rgb888_r_x2[t] <= acc_rgb888_r_x2[t];
          acc_rgb888_g_x2[t] <= acc_rgb888_g_x2[t];
          acc_rgb888_b_x2[t] <= acc_rgb888_b_x2[t];
        end
      end


    end
  endgenerate
  /*****************************************************************
                        RGB�?                                       
*****************************************************************/


  assign R_new[0] = acc_rgb888_r_x2[0];
  assign G_new[0] = acc_rgb888_g_x2[0];
  assign B_new[0] = acc_rgb888_b_x2[0];

  assign R_new[1] = acc_rgb888_r_x2[1];
  assign G_new[1] = acc_rgb888_g_x2[1];
  assign B_new[1] = acc_rgb888_b_x2[1];

  assign R_new[2] = acc_rgb888_r_x2[2];
  assign G_new[2] = acc_rgb888_g_x2[2];
  assign B_new[2] = acc_rgb888_b_x2[2];

  assign R_new[3] = acc_rgb888_r_x2[3];
  assign G_new[3] = acc_rgb888_g_x2[3];
  assign B_new[3] = acc_rgb888_b_x2[3];

  /*****************************************************************
                        同步信号                                       
*****************************************************************/


  always @(posedge I_clk or negedge I_rst_n) begin
    if (!I_rst_n) {I_tlast_r, I_tuser_r, I_tvalid_r} <= 0;
    else begin
      I_tlast_r  <= {I_tlast_r[2:0], I_tlast};
      I_tuser_r  <= {I_tuser_r[2:0], I_tuser};
      I_tvalid_r <= {I_tvalid_r[2:0], I_tvalid};
    end
  end


  assign O_tlast = I_tlast_r[3];
  assign O_tuser = I_tuser_r[3];
  assign O_tvalid = I_tvalid_r[3];


  assign O_tdata = {
    R_new[3],
    G_new[3],
    B_new[3],
    R_new[2],
    G_new[2],
    B_new[2],
    R_new[1],
    G_new[1],
    B_new[1],
    R_new[0],
    G_new[0],
    B_new[0]
  };
  assign I_tready = O_tready;

endmodule
