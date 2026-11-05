
module Concat_c2552f36122b#(
    parameter   PORT_NUM    = 1,
    parameter   IN_WIDTH_0  = 1,

    parameter   IN_WIDTH_1  = 1,

    parameter   IN_WIDTH_2  = 1,

    parameter   IN_WIDTH_3  = 1,

    parameter   IN_WIDTH_4  = 1,

    parameter   IN_WIDTH_5  = 1,

    parameter   IN_WIDTH_6  = 1,

    parameter   IN_WIDTH_7  = 1,

    parameter   IN_WIDTH_8  = 1,

    parameter   IN_WIDTH_9  = 1,

    parameter   IN_WIDTH_10      = 1,

    parameter   IN_WIDTH_11      = 1,

    parameter   IN_WIDTH_12      = 1,

    parameter   IN_WIDTH_13      = 1,

    parameter   IN_WIDTH_14      = 1,

    parameter   IN_WIDTH_15      = 1,

    parameter   OUT_WIDTH        =  32
)
(
    input  wire  [IN_WIDTH_0-1 : 0]     In0,

    input  wire  [IN_WIDTH_1-1 : 0]     In1,

    input  wire  [IN_WIDTH_2-1 : 0]     In2,

    input  wire  [IN_WIDTH_3-1 : 0]     In3,

    input  wire  [IN_WIDTH_4-1 : 0]     In4,

    input  wire  [IN_WIDTH_5-1 : 0]     In5,

    input  wire  [IN_WIDTH_6-1 : 0]     In6,

    input  wire  [IN_WIDTH_7-1 : 0]     In7,

    input  wire  [IN_WIDTH_8-1 : 0]     In8,

    input  wire  [IN_WIDTH_9-1 : 0]     In9,

    input  wire  [IN_WIDTH_10-1 : 0]    In10,

    input  wire  [IN_WIDTH_11-1 : 0]    In11,

    input  wire  [IN_WIDTH_12-1 : 0]    In12,

    input  wire  [IN_WIDTH_13-1 : 0]    In13,

    input  wire  [IN_WIDTH_14-1 : 0]    In14,

    input  wire  [IN_WIDTH_15-1 : 0]    In15,

    output wire  [OUT_WIDTH-1 : 0]      Dout

);
    assign  Dout = {
         
            In15, 
         
            In14, 
         
            In13, 
         
            In12, 
         
            In11, 
         
            In10, 
         
            In9, 
         
            In8, 
         
            In7, 
         
            In6, 
         
            In5, 
         
            In4, 
         
            In3, 
         
            In2, 
         
            In1, 
         
            In0
        };

endmodule
