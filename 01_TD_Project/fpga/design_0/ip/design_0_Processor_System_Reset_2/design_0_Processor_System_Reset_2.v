/************************************************************\
**	Copyright (c) 2012-2025 Anlogic Inc.
**	All Right Reserved.
\************************************************************/
/************************************************************\
**	Build time: Mar 31 2025 15:32:04
**	TD version	:	5.9.151508
************************************************************/
`timescale 1ns/1ns
module design_0_Processor_System_Reset_2
(
  input                         clk,
  input                         external_reset,
  input                         aux_rst,
  input                         system_rst,
  input                         pll_locked,
  output                        soc_reset,
  output  [0:0]                 bus_reset,
  output  [0:0]                 peripheral_reset,
  output  [0:0]                 interconnect_aresetn,
  output  [0:0]                 peripheral_aresetn
);

  proc_sys_reset_e972b90c3049
  #(
      .EXTERNAL_RESET_PULSE_WIDTH(4),
      .AUXILIARY_RESET_PULSE_WIDTH(4),
      .EXTERNAL_RESET_IS_HIGH(1),
      .AUXILIARY_RESET_IS_HIGH(0),
      .NUMBER_BUS_OF_RESET(1),
      .NUMBER_OF_PERIPHERALS_RESET(1),
      .NUMBER_OF_INTERCONNECT_ARESETN(1),
      .NUMBER_OF_PERIPHERALS_ARESETN(1)
  )proc_sys_reset_e972b90c3049_Inst
  (
      .clk(clk),
      .external_reset(external_reset),
      .aux_rst(aux_rst),
      .system_rst(system_rst),
      .pll_locked(pll_locked),
      .soc_reset(soc_reset),
      .bus_reset(bus_reset),
      .peripheral_reset(peripheral_reset),
      .interconnect_aresetn(interconnect_aresetn),
      .peripheral_aresetn(peripheral_aresetn)
  );
endmodule
