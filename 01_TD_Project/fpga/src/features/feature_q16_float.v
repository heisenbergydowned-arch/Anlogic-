`timescale 1ns/1ps
// Signed Q16.16 -> IEEE754 binary32, round to nearest, ties to even.
module feature_q16_float(input wire signed [31:0] q16, output reg [31:0] fp32);
    integer i, position, shift;
    reg [31:0] magnitude, discarded, half;
    reg [24:0] significand;
    reg [7:0] exponent;
    always @* begin
        magnitude = q16[31] ? (~q16 + 1'b1) : q16;
        position=0; shift=0; discarded=0; half=0; significand=0; exponent=0;
        for (i=0;i<32;i=i+1) if (magnitude[i]) position=i;
        if (magnitude==0) fp32=0;
        else begin
            exponent=position+111; // bias 127 minus 16 fractional bits
            if (position>23) begin
                shift=position-23; significand=magnitude>>shift;
                discarded=magnitude & ((32'd1<<shift)-1'b1);
                half=32'd1<<(shift-1);
                if ((discarded>half) || ((discarded==half) && significand[0]))
                    significand=significand+1'b1;
                if (significand[24]) begin significand=significand>>1; exponent=exponent+1'b1; end
            end else significand=magnitude<<(23-position);
            fp32={q16[31],exponent,significand[22:0]};
        end
    end
endmodule
