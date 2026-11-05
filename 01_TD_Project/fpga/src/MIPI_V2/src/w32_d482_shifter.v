`timescale 1ns / 1ps

module w32_d482_shifter(dataout,
	clk, en, datain);

    input                     clk;
    input                     en;
    input       [31:0]      datain;
    output      [31:0]      dataout;
    DR1_LOGIC_SHIFTER#(
        .DATA_WIDTH(32),
        .DATA_DEPTH(482),
        .INIT_FILE("NONE"),
        .SHIFT_TYPE("FIXED"))
        inst(
         .depth({1{1'b0}}),
         .dataout(dataout),
         .clk(clk),
         .en(en),
         .datain(datain));

endmodule
