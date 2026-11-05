/************************************************************\
**	Copyright (c) 2012-2025 Anlogic Inc.
**	All Right Reserved.
\************************************************************/
/************************************************************\
**	Build time: Mar 28 2025 14:08:22
**	TD version	:	5.9.151508
************************************************************/
module design_0_Concat_0
(
  input   [0:0]                 In0,
  input   [0:0]                 In1,
  input   [0:0]                 In2,
  input   [0:0]                 In3,
  input   [0:0]                 In4,
  input   [0:0]                 In5,
  input   [0:0]                 In6,
  input   [0:0]                 In7,
  input   [0:0]                 In8,
  input   [0:0]                 In9,
  input   [0:0]                 In10,
  input   [0:0]                 In11,
  input   [0:0]                 In12,
  input   [0:0]                 In13,
  input   [0:0]                 In14,
  input   [0:0]                 In15,
  output  [15:0]                Dout
);

  Concat_c2552f36122b
  #(
      .PORT_NUM(16),
      .IN_WIDTH_0(1),
      .IN_WIDTH_1(1),
      .IN_WIDTH_2(1),
      .IN_WIDTH_3(1),
      .IN_WIDTH_4(1),
      .IN_WIDTH_5(1),
      .IN_WIDTH_6(1),
      .IN_WIDTH_7(1),
      .IN_WIDTH_8(1),
      .IN_WIDTH_9(1),
      .IN_WIDTH_10(1),
      .IN_WIDTH_11(1),
      .IN_WIDTH_12(1),
      .IN_WIDTH_13(1),
      .IN_WIDTH_14(1),
      .IN_WIDTH_15(1),
      .OUT_WIDTH(16)
  )Concat_c2552f36122b_Inst
  (
      .In0(In0),
      .In1(In1),
      .In2(In2),
      .In3(In3),
      .In4(In4),
      .In5(In5),
      .In6(In6),
      .In7(In7),
      .In8(In8),
      .In9(In9),
      .In10(In10),
      .In11(In11),
      .In12(In12),
      .In13(In13),
      .In14(In14),
      .In15(In15),
      .Dout(Dout)
  );
endmodule
