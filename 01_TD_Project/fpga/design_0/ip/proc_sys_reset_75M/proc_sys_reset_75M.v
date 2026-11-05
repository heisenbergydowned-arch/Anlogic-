`timescale 1ns/1ns
module proc_sys_reset_75M
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

  proc_sys_reset_c36d787ffe77
  #(
      .EXTERNAL_RESET_PULSE_WIDTH(4),
      .AUXILIARY_RESET_PULSE_WIDTH(4),
      .EXTERNAL_RESET_IS_HIGH(1),
      .AUXILIARY_RESET_IS_HIGH(1),
      .NUMBER_BUS_OF_RESET(1),
      .NUMBER_OF_PERIPHERALS_RESET(1),
      .NUMBER_OF_INTERCONNECT_ARESETN(1),
      .NUMBER_OF_PERIPHERALS_ARESETN(1)
  )proc_sys_reset_c36d787ffe77_Inst
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
