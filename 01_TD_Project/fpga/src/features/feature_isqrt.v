`timescale 1ns/1ps
// Floor sqrt of an unsigned 64-bit integer, 32 cycles, no multiplier.
module feature_isqrt (
    input wire clk, input wire rst_n, input wire start,
    input wire [63:0] radicand,
    output reg busy, output reg done, output reg [31:0] root
);
    reg [63:0] operand;
    reg [65:0] remainder;
    reg [31:0] partial;
    reg [5:0] count;
    wire [65:0] shifted = (remainder << 2) | {64'b0,operand[63:62]};
    wire [65:0] trial = {32'b0,partial,2'b01};
    wire take = shifted >= trial;
    wire [31:0] next_root = {partial[30:0],take};
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin busy<=0; done<=0; root<=0; operand<=0;
            remainder<=0; partial<=0; count<=0;
        end else begin
            done<=0;
            if (start && !busy) begin
                busy<=1; operand<=radicand; remainder<=0; partial<=0; count<=32;
            end else if (busy) begin
                remainder<=take ? shifted-trial : shifted;
                operand<=operand<<2; partial<=next_root; count<=count-1'b1;
                if (count==1) begin busy<=0; done<=1; root<=next_root; end
            end
        end
    end
endmodule
