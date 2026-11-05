`timescale 1ns/1ps
// Exact unsigned 64-bit square using one registered 16x16 multiplier.
// Ten diagonal/cross terms are evaluated in increasing base-65536 columns.
// A 36-bit carry accumulator replaces a shifted 128-bit term and wide adder.
// Each column has at most two terms of at most 33 bits plus an 18-bit carry,
// hence its sum is below 2^34. All 128 product bits are retained exactly.
// start is accepted only while idle; done pulses 21 clocks after that edge.
// result is valid on done and held until the next accepted start; reset aborts.
module feature_square64 (
    input wire clk,rst_n,start,
    input wire [63:0] operand,
    output reg busy,done,
    output wire [127:0] result
);
    localparam S_IDLE=2'd0,S_MUL=2'd1,S_ACC=2'd2,S_DONE=2'd3;
    reg [1:0] st;
    reg [63:0] op;
    reg [3:0] idx;
    reg [15:0] la,lb;
    reg [31:0] pp;
    reg off,last_in_column;
    reg [35:0] acc;
    reg [127:0] product_words;
    assign result=product_words;
    function [15:0] limb;
        input [63:0] v;input [1:0] n;
        case(n)
            0:limb=v[15:0];1:limb=v[31:16];2:limb=v[47:32];default:limb=v[63:48];
        endcase
    endfunction
    // (0,0),(0,1),(0,2),(1,1),(0,3),(1,2),(1,3),(2,2),(2,3),(3,3)
    function [1:0] term_i;
        input [3:0] k;
        case(k)
            3,5,6:term_i=1;7,8:term_i=2;9:term_i=3;default:term_i=0;
        endcase
    endfunction
    function [1:0] term_j;
        input [3:0] k;
        case(k)
            0:term_j=0;1,3:term_j=1;2,5,7:term_j=2;default:term_j=3;
        endcase
    endfunction
    wire [3:0] next_idx=idx+1'b1;
    wire [32:0] term=off ? {pp,1'b0}:{1'b0,pp};
    wire [35:0] column_sum=acc+{3'd0,term};
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            st<=S_IDLE;op<=0;idx<=0;la<=0;lb<=0;pp<=0;
            off<=0;last_in_column<=0;acc<=0;product_words<=0;busy<=0;done<=0;
        end else begin
            done<=0;
            case(st)
                S_IDLE:if(start)begin
                    op<=operand;idx<=0;acc<=0;product_words<=0;busy<=1;
                    la<=operand[15:0];lb<=operand[15:0];st<=S_MUL;
                end
                S_MUL:begin
                    pp<=la*lb;off<=term_i(idx)!=term_j(idx);
                    last_in_column<=idx!=2 && idx!=4 && idx!=6;
                    la<=limb(op,term_i(next_idx));lb<=limb(op,term_j(next_idx));st<=S_ACC;
                end
                S_ACC:begin
                    if(last_in_column)begin
                        product_words<={column_sum[15:0],product_words[127:16]};
                        acc<=column_sum>>16;
                    end else acc<=column_sum;
                    if(idx==9)st<=S_DONE;else begin idx<=next_idx;st<=S_MUL;end
                end
                S_DONE:begin
                    product_words<={acc[15:0],product_words[127:16]};
                    busy<=0;done<=1;st<=S_IDLE;
                end
                default:st<=S_IDLE;
            endcase
        end
    end
endmodule
