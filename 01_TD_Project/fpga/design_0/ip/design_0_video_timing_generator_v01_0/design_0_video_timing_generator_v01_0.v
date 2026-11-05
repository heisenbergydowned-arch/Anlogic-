/************************************************************\
**	Copyright (c) 2012-2025 Anlogic Inc.
**	All Right Reserved.
\************************************************************/
/************************************************************\
**	Build time: Nov 09 2025 22:58:13
**	TD version	:	6.3.175085
************************************************************/
`timescale 1 ns / 1 ps
module design_0_video_timing_generator_v01_0
(
  input                         aclk,
  input                         arst_n,
  input   [12:0]                s_axi_awaddr,
  input                         s_axi_awvalid,
  output                        s_axi_awready,
  input   [31:0]                s_axi_wdata,
  input   [3:0]                 s_axi_wstrb,
  input                         s_axi_wvalid,
  output                        s_axi_wready,
  output  [1:0]                 s_axi_bresp,
  output                        s_axi_bvalid,
  input                         s_axi_bready,
  input   [12:0]                s_axi_araddr,
  input                         s_axi_arvalid,
  output                        s_axi_arready,
  output  [31:0]                s_axi_rdata,
  output  [1:0]                 s_axi_rresp,
  output                        s_axi_rvalid,
  input                         s_axi_rready,
  input                         ref_clk,
  input                         vtg_ce,
  output                        vtg_pclk_locked,
  output                        vtg_pclk,
  output                        vtg_hsync,
  output                        vtg_vsync,
  output                        vtg_hblank,
  output                        vtg_vblank,
  output                        vtg_active_video
);

  video_timing_generator_v01_e2dadf6740ca
  #(
      .REF_CLK_FREQ(75),
      .FPS(60),
      .H_FRONT(16'd110),
      .H_ACTIVE(16'd1280),
      .H_SYNC(16'd40),
      .H_BACK(16'd220),
      .V_FRONT(16'd5),
      .V_ACTIVE(16'd720),
      .V_SYNC(16'd5),
      .V_BACK(16'd20)
  )video_timing_generator_v01_e2dadf6740ca_Inst
  (
      .aclk(aclk),
      .arst_n(arst_n),
      .s_axi_awaddr(s_axi_awaddr),
      .s_axi_awvalid(s_axi_awvalid),
      .s_axi_awready(s_axi_awready),
      .s_axi_wdata(s_axi_wdata),
      .s_axi_wstrb(s_axi_wstrb),
      .s_axi_wvalid(s_axi_wvalid),
      .s_axi_wready(s_axi_wready),
      .s_axi_bresp(s_axi_bresp),
      .s_axi_bvalid(s_axi_bvalid),
      .s_axi_bready(s_axi_bready),
      .s_axi_araddr(s_axi_araddr),
      .s_axi_arvalid(s_axi_arvalid),
      .s_axi_arready(s_axi_arready),
      .s_axi_rdata(s_axi_rdata),
      .s_axi_rresp(s_axi_rresp),
      .s_axi_rvalid(s_axi_rvalid),
      .s_axi_rready(s_axi_rready),
      .ref_clk(ref_clk),
      .vtg_ce(vtg_ce),
      .vtg_pclk_locked(vtg_pclk_locked),
      .vtg_pclk(vtg_pclk),
      .vtg_hsync(vtg_hsync),
      .vtg_vsync(vtg_vsync),
      .vtg_hblank(vtg_hblank),
      .vtg_vblank(vtg_vblank),
      .vtg_active_video(vtg_active_video)
  );
endmodule
