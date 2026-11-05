/************************************************************\
**	Copyright (c) 2012-2025 Anlogic Inc.
**	All Right Reserved.
\************************************************************/
/************************************************************\
**	Build time: Nov 09 2025 22:59:29
**	TD version	:	6.3.175085
************************************************************/
`timescale 1ps/1ps
module design_0_AXI4_Stream_to_Video_Out_0
(
  input                         aclk,
  input                         aclken,
  input                         aresetn,
  input   [23:0]                s_axis_video_tdata,
  input                         s_axis_video_tvalid,
  output                        s_axis_video_tready,
  input                         s_axis_video_tuser,
  input                         s_axis_video_tlast,
  input                         fid,
  input                         vid_io_out_clk,
  input                         vid_io_out_reset,
  input                         vid_io_out_ce,
  output                        vid_active_video,
  output                        vid_vsync,
  output                        vid_hsync,
  output                        vid_vblank,
  output                        vid_hblank,
  output                        vid_field_id,
  output  [23:0]                vid_data,
  input                         vtg_vsync,
  input                         vtg_hsync,
  input                         vtg_vblank,
  input                         vtg_hblank,
  input                         vtg_active_video,
  input                         vtg_field_id,
  output                        vtg_ce,
  output                        locked,
  output                        overflow,
  output                        underflow,
  output  [5:0]                 fifo_read_level,
  output  [31:0]                status,
  output                        sof_state_out
);

  alc_axi4s_vid_out_7d63f5fadd80
  #(
      .AXIS2Vid_PIXELS_PER_CLOCK(1),
      .AXIS2Vid_COMPONENTS_PER_PIXEL(3),
      .AXIS2Vid_S_AXIS_COMPONENT_WIDTH(8),
      .AXIS2Vid_NATIVE_COMPONENT_WIDTH(8),
      .AXIS2Vid_NATIVE_DATA_WIDTH(24),
      .AXIS2Vid_S_AXIS_TDATA_WIDTH(24),
      .AXIS2Vid_HAS_ASYNC_CLK(1),
      .AXIS2Vid_ADDR_WIDTH(5),
      .AXIS2Vid_VTG_MASTER_SLAVE(0),
      .AXIS2Vid_HYSTERESIS_LEVEL(12)
  )alc_axi4s_vid_out_7d63f5fadd80_Inst
  (
      .aclk(aclk),
      .aclken(aclken),
      .aresetn(aresetn),
      .s_axis_video_tdata(s_axis_video_tdata),
      .s_axis_video_tvalid(s_axis_video_tvalid),
      .s_axis_video_tready(s_axis_video_tready),
      .s_axis_video_tuser(s_axis_video_tuser),
      .s_axis_video_tlast(s_axis_video_tlast),
      .fid(fid),
      .vid_io_out_clk(vid_io_out_clk),
      .vid_io_out_reset(vid_io_out_reset),
      .vid_io_out_ce(vid_io_out_ce),
      .vid_active_video(vid_active_video),
      .vid_vsync(vid_vsync),
      .vid_hsync(vid_hsync),
      .vid_vblank(vid_vblank),
      .vid_hblank(vid_hblank),
      .vid_field_id(vid_field_id),
      .vid_data(vid_data),
      .vtg_vsync(vtg_vsync),
      .vtg_hsync(vtg_hsync),
      .vtg_vblank(vtg_vblank),
      .vtg_hblank(vtg_hblank),
      .vtg_active_video(vtg_active_video),
      .vtg_field_id(vtg_field_id),
      .vtg_ce(vtg_ce),
      .locked(locked),
      .overflow(overflow),
      .underflow(underflow),
      .fifo_read_level(fifo_read_level),
      .status(status),
      .sof_state_out(sof_state_out)
  );
endmodule
