`timescale 1ns/1ps
module ram0
(
  input   [31:0]                dia,
  input   [8:0]                 addra,
  input                         cea,
  input                         clka,
  output  [31:0]                dob,
  input   [8:0]                 addrb,
  input                         clkb
);

  ram_dca62376a38a
  #(
      .DATA_WIDTH_A(32),
      .ADDR_WIDTH_A(9),
      .DATA_DEPTH_A(512),
      .DATA_WIDTH_B(32),
      .ADDR_WIDTH_B(9),
      .DATA_DEPTH_B(512),
      .REGMODE_A("NOREG"),
      .WRITEMODE_A("NORMAL"),
      .RESETMODE_A("ASYNC"),
      .INIT_FILE("NONE"),
      .REGMODE_B("NOREG"),
      .FILL_ALL("NONE"),
      .WRITEMODE_B("NORMAL"),
      .RESETMODE_B("ASYNC")
  )ram_dca62376a38a_Inst
  (
      .dia(dia),
      .addra(addra),
      .cea(cea),
      .clka(clka),
      .dob(dob),
      .addrb(addrb),
      .clkb(clkb)
  );
endmodule
