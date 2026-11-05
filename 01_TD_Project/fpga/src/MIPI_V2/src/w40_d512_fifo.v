`timescale 1ns / 1ps

module w40_d512_fifo (
	rst,
	di, re, clk, we,
	dout,
	empty_flag,full_flag,rdusedw,wrusedw
 
);

	input rst;
	input [39:0] di;
	input clk, we;
	input re;

	output [39:0] dout;
	output empty_flag;
	output full_flag;
	output [9:0] rdusedw;
	output [9:0] wrusedw;

DR1_LOGIC_RAMFIFO #(
 	.DATA_WIDTH(40),
	.ADDR_WIDTH(9),
	.SHOWAHEAD(0),
	.IMPLEMENT("20K")
)
logic_ramfifo(
	.rst(rst),
	.di(di),
	.clk(clk),
	.we(we),
	.dout(dout),
	.re(re),
	.empty_flag(empty_flag),
	.full_flag(full_flag),
	.rdusedw(rdusedw),
	.wrusedw(wrusedw)
);

endmodule
