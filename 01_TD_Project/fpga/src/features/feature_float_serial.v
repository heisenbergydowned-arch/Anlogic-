`timescale 1ns/1ps
// Bounded Q16.16 -> binary32 conversion: normalize one bit per clock.
// Round-to-nearest/ties-to-even. At most 35 clocks; no variable barrel shifter,
// priority-encoder/rounding cascade on a single 100MHz register path.
module feature_float_serial(
    input wire clk,rst_n,start,input wire signed [31:0] q16,
    output wire busy,output reg done,output reg [31:0] fp32
);
    reg [1:0] state;reg sign;reg [31:0] magnitude;reg [7:0] exponent;reg [24:0] rounded;
    assign busy=state!=0;
    wire round_up=magnitude[7] && ((|magnitude[6:0]) || magnitude[8]);
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin state<=0;sign<=0;magnitude<=0;exponent<=0;rounded<=0;done<=0;fp32<=0;end
        else begin
            done<=0;
            case(state)
                0:if(start)begin
                    sign<=q16[31];magnitude<=q16[31] ? (~q16+32'd1):q16;exponent<=142;
                    if(q16==0)begin fp32<=0;done<=1;end else state<=1;
                end
                1:if(!magnitude[31])begin magnitude<=magnitude<<1;exponent<=exponent-1;end
                  else begin rounded<={1'b0,magnitude[31:8]}+{24'd0,round_up};state<=2;end
                2:begin
                    if(rounded[24])fp32<={sign,exponent+8'd1,23'd0};
                    else fp32<={sign,exponent,rounded[22:0]};
                    done<=1;state<=0;
                end
                default:state<=0;
            endcase
        end
    end
endmodule
