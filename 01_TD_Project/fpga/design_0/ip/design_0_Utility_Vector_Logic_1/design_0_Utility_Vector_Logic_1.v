/************************************************************\
**	Copyright (c) 2012-2025 Anlogic Inc.
**	All Right Reserved.
\************************************************************/
/************************************************************\
**	Build time: Nov 19 2025 22:30:25
**	TD version	:	6.2.178840
************************************************************/
module design_0_Utility_Vector_Logic_1
(
  input   [0:0]                 vector_a,
  output  [0:0]                 result_vector
);

  Utility_Vector_Logic_8db620011faa
  #(
      .OPERATION(3),
      .SIZE(1)
  )Utility_Vector_Logic_8db620011faa_Inst
  (
      .vector_a(vector_a),
      .result_vector(result_vector)
  );
endmodule
