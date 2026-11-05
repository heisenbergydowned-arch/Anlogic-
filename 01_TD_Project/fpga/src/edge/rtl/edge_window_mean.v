`timescale 1ns/1ps
// Sequential unsigned divider, signed ADC sums -> signed raw-code Q16.16.
// No combinational division or unbounded sample accumulation on the fast path.
module edge_window_mean #(parameter PRESSURE_INDEPENDENT=0)(
    input wire clk,rst_n,start,
    input wire signed [47:0] current_sum,pressure_sum,input wire [31:0] adc_count,
    input wire [31:0] pressure_count,
    input wire [63:0] period_sum,input wire [31:0] fg_count,
    output reg done,output reg signed [31:0] current_mean,pressure_mean,
    output reg [31:0] period_mean,output reg [15:0] quality
);
    reg [2:0] state;reg run,negative;
    reg [63:0] numerator,denominator;wire d_done,d_busy,d_zero;wire [63:0] result;
    wire [31:0] pressure_divisor=PRESSURE_INDEPENDENT ? pressure_count:adc_count;
    feature_udiv #(.WIDTH(64)) divider(.clk(clk),.rst_n(rst_n),.start(run),
        .numerator(numerator),.denominator(denominator),.busy(d_busy),.done(d_done),.div_zero(d_zero),.quotient(result));
    function [63:0] magnitude;input signed [47:0] value;
        begin magnitude=value[47] ? -$signed({{16{value[47]}},value}):{{16{value[47]}},value};end
    endfunction
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin state<=0;run<=0;negative<=0;numerator<=0;denominator<=0;
            done<=0;current_mean<=0;pressure_mean<=0;period_mean<=0;quality<=0;end
        else begin
            run<=0;done<=0;
            case(state)
                0:if(start)begin
                    quality<=0;current_mean<=0;pressure_mean<=0;period_mean<=0;
                    if(adc_count==0)begin quality[8]<=1;state<=2;end
                    else begin numerator<=magnitude(current_sum)<<16;denominator<=adc_count;
                        negative<=current_sum[47];run<=1;state<=1;end
                end
                1:if(d_done)begin
                    if(result>(negative ? 64'h80000000:64'h7fffffff))quality[3]<=1;
                    current_mean<=negative ? -result[31:0]:result[31:0];
                    state<=2;
                end
                2:begin
                    if(pressure_divisor==0)begin quality[10]<=1;state<=4;end
                    else begin
                        numerator<=magnitude(pressure_sum)<<16;denominator<=pressure_divisor;
                        negative<=pressure_sum[47];run<=1;state<=3;
                    end
                end
                3:if(d_done)begin
                    if(result>(negative ? 64'h80000000:64'h7fffffff))quality[3]<=1;
                    pressure_mean<=negative ? -result[31:0]:result[31:0];state<=4;
                end
                4:begin
                    if(fg_count==0)begin quality[11]<=1;state<=6;end
                    else begin numerator<=period_sum;denominator<=fg_count;run<=1;state<=5;end
                end
                5:if(d_done)begin period_mean<=result[31:0];if(result>64'hffffffff)quality[3]<=1;state<=6;end
                6:begin done<=1;state<=0;end
            endcase
        end
    end
endmodule
