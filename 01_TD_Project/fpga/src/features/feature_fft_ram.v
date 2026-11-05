`timescale 1ns/1ps
// True dual-port synchronous RAM template. No reset on RAM or read registers.
// Port writes must never address the same word in the same clock cycle.
module feature_fft_ram (
    input wire clk,
    input wire [9:0] a_addr,b_addr,
    input wire a_we,b_we,
    input wire [63:0] a_wdata,b_wdata,
    output reg [63:0] a_rdata,b_rdata
);
    reg [63:0] memory[0:1023];
    always @(posedge clk) begin
        if (a_we) memory[a_addr]<=a_wdata;
        a_rdata<=memory[a_addr];
    end
    always @(posedge clk) begin
        if (b_we) memory[b_addr]<=b_wdata;
        b_rdata<=memory[b_addr];
    end
endmodule
