/************************************************************\
**	Copyright (c) 2012-2025 Anlogic Inc.
**	All Right Reserved.
\************************************************************/
/************************************************************\
**	Build time: May 29 2025 10:28:25
**	TD version	:	5.9.151508
************************************************************/
`timescale 1ns/1ps
module blk_mem_gen_awb_delay_signal
(
  input   [95:0]                dia,
  input   [10:0]                addra,
  input                         wea,
  input                         clka,
  input   [10:0]                addrb,
  input                         clkb,
  input   [95:0]                dib,
  input                         web,
  output  [95:0]                doa,
  output  [95:0]                dob
);

  ram_330dcd7b33e5
  #(
      .DATA_WIDTH_A(96),
      .ADDR_WIDTH_A(11),
      .DATA_DEPTH_A(2048),
      .DATA_WIDTH_B(96),
      .ADDR_WIDTH_B(11),
      .DATA_DEPTH_B(2048),
      .REGMODE_A("NOREG"),
      .WRITEMODE_A("NORMAL"),
      .RESETMODE_A("ASYNC"),
      .INIT_FILE("NONE"),
      .REGMODE_B("NOREG"),
      .FILL_ALL("NONE"),
      .WRITEMODE_B("READBEFOREWRITE"),
      .RESETMODE_B("ASYNC")
  )ram_330dcd7b33e5_Inst
  (
      .doa(doa),
      .dia(dia),
      .addra(addra),
      .wea(wea),
      .clka(clka),
      .dob(dob),
      .addrb(addrb),
      .clkb(clkb),
      .dib(dib),
      .web(web)
  );
endmodule
