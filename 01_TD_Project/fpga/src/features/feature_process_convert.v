`timescale 1ns/1ps
// Convert window snapshots into A, degC, kPa, RPM, signed Q16.16.
// Input ADC window means are signed Q16.16 *raw codes* (not volts).
// Nominal defaults: AD7606 +/-5V, ACS712-05B 185mV/A, MPXV7002DP 1V/kPa,
// both zero outputs 2.5V. Replace coefficients after real zero/gain calibration.
module feature_process_convert #(
    parameter CLK_HZ=100000000, parameter FG_PULSES_PER_REV=2, parameter RUNTIME_CONFIG=0,
    parameter signed [31:0] CURRENT_ZERO_Q16=32'sd1073741824,
    parameter signed [31:0] PRESSURE_ZERO_Q16=32'sd1073741824,
    parameter signed [31:0] CURRENT_SLOPE_Q30=32'sd885622,
    parameter signed [31:0] PRESSURE_SLOPE_Q30=32'sd163840
) (
    input wire clk,input wire rst_n,input wire start,
    input wire signed [31:0] current_mean_code_q16,pressure_mean_code_q16,
    input wire signed [15:0] temperature_raw,
    input wire [31:0] fg_mean_period,
    input wire [3:0] valid_mask, // bit0=current, bit1=temp, bit2=pressure, bit3=FG
    input wire signed [31:0] cfg_current_zero,cfg_pressure_zero,cfg_current_slope,cfg_pressure_slope,
    input wire [3:0] cfg_ppr,
    output reg busy,output reg done,
    output reg signed [31:0] current_q16,temp_q16,pressure_q16,rpm_q16,
    output reg [15:0] quality
);
    wire signed [31:0] current_zero=RUNTIME_CONFIG ? cfg_current_zero:CURRENT_ZERO_Q16;
    wire signed [31:0] pressure_zero=RUNTIME_CONFIG ? cfg_pressure_zero:PRESSURE_ZERO_Q16;
    wire signed [31:0] current_slope=RUNTIME_CONFIG ? cfg_current_slope:CURRENT_SLOPE_Q30;
    wire signed [31:0] pressure_slope=RUNTIME_CONFIG ? cfg_pressure_slope:PRESSURE_SLOPE_Q30;
    wire [3:0] ppr=RUNTIME_CONFIG ? cfg_ppr:FG_PULSES_PER_REV;
    wire signed [32:0] current_delta=$signed({current_mean_code_q16[31],current_mean_code_q16})-
        $signed({current_zero[31],current_zero});
    wire signed [32:0] pressure_delta=$signed({pressure_mean_code_q16[31],pressure_mean_code_q16})-
        $signed({pressure_zero[31],pressure_zero});
    wire signed [64:0] current_product=current_delta*current_slope;
    wire signed [64:0] pressure_product=pressure_delta*pressure_slope;
    wire signed [64:0] current_scaled=current_product>>>30;
    wire signed [64:0] pressure_scaled=pressure_product>>>30;
    wire current_overflow=current_scaled>65'sd2147483647 || current_scaled< -65'sd2147483648;
    wire pressure_overflow=pressure_scaled>65'sd2147483647 || pressure_scaled< -65'sd2147483648;
    reg div_start;
    reg [95:0] numerator,denominator;
    wire div_busy,div_done,div_zero;
    wire [95:0] result;
    feature_udiv divider(.clk(clk),.rst_n(rst_n),.start(div_start),
        .numerator(numerator),.denominator(denominator),.busy(div_busy),
        .done(div_done),.div_zero(div_zero),.quotient(result));
    localparam [95:0] RPM_NUM=96'd60*CLK_HZ*65536;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy<=0;done<=0;div_start<=0;numerator<=0;denominator<=0;
            current_q16<=0;temp_q16<=0;pressure_q16<=0;rpm_q16<=0;quality<=0;
        end else begin
            done<=0;div_start<=0;
            if (start && !busy) begin
                quality<={4'd0,~valid_mask,8'd0};
                if (valid_mask[0]) current_q16<=current_overflow ?
                    (current_scaled[64] ? 32'sh80000000 : 32'sh7fffffff) : current_scaled[31:0];
                else current_q16<=0;
                if (valid_mask[1]) temp_q16<=$signed(temperature_raw)*32'sd4096;
                else temp_q16<=0;
                if (valid_mask[2]) pressure_q16<=pressure_overflow ?
                    (pressure_scaled[64] ? 32'sh80000000 : 32'sh7fffffff) : pressure_scaled[31:0];
                else pressure_q16<=0;
                if ((valid_mask[0] && current_overflow) || (valid_mask[2] && pressure_overflow)) quality[3]<=1;
                if (!valid_mask[3] || fg_mean_period==0 || ppr==0) begin
                    rpm_q16<=0;quality[11]<=1;done<=1;
                end else begin
                    numerator<=RPM_NUM;denominator<=96'd1*fg_mean_period*ppr;
                    div_start<=1;busy<=1;
                end
            end else if (busy && div_done) begin
                rpm_q16<=result>96'h7fffffff ? 32'sh7fffffff : result[31:0];
                if (result>96'h7fffffff) quality[3]<=1;
                busy<=0;done<=1;
            end
        end
    end
endmodule
