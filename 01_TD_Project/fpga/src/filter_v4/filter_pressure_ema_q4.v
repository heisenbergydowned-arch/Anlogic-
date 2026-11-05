`timescale 1ns/1ps
module filter_pressure_ema_q4 #(
    parameter integer SHIFT_K = 2
) (
    input wire clk,
    input wire rst_n,
    input wire in_event,
    input wire signed [15:0] in_sample,
    input wire [7:0] in_quality,
    input wire [15:0] in_seq,
    input wire [63:0] in_obs_ts,
    input wire [63:0] in_token,
    input wire invalidate,
    input wire [7:0] invalidate_quality,
    output reg out_event,
    output reg out_has_sample,
    output reg out_valid,
    output reg out_warm,
    output reg signed [15:0] out_sample,
    output reg [7:0] out_quality,
    output reg [15:0] out_seq,
    output reg [63:0] out_obs_ts,
    output reg [63:0] out_token,
    output reg [31:0] out_epoch
);
    generate
        if (SHIFT_K < 1 || SHIFT_K > 4) begin : invalid_shift
            filter_v4_ema_shift_must_be_1_to_4 invalid_parameter();
        end
    endgenerate

    reg signed [19:0] state_q4;
    reg warm_state;
    reg [31:0] stream_epoch;
    wire signed [19:0] target_q4 = {in_sample, 4'b0000};
    wire signed [20:0] difference = {target_q4[19], target_q4} - {state_q4[19], state_q4};
    wire signed [21:0] difference_wide = {difference[20], difference};
    wire signed [21:0] bias = 22'sd1 << (SHIFT_K - 1);
    wire signed [21:0] delta = difference_wide[21]
        ? -(((-difference_wide) + bias) >>> SHIFT_K)
        : (difference_wide + bias) >>> SHIFT_K;
    wire signed [21:0] extended_state = {{2{state_q4[19]}}, state_q4};
    wire signed [21:0] next_state = warm_state
        ? extended_state + delta : {{2{target_q4[19]}}, target_q4};
    wire signed [21:0] rounded = next_state[21]
        ? -(((-next_state) + 22'sd8) >>> 4)
        : (next_state + 22'sd8) >>> 4;
    wire signed [15:0] clipped = rounded > 22'sd32767 ? 16'sh7fff
        : rounded < -22'sd32768 ? 16'sh8000 : rounded[15:0];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q4 <= 20'sd0;
            warm_state <= 1'b0;
            stream_epoch <= 32'd0;
            out_event <= 1'b0;
            out_has_sample <= 1'b0;
            out_valid <= 1'b0;
            out_warm <= 1'b0;
            out_sample <= 16'sd0;
            out_quality <= 8'h01;
            out_seq <= 16'd0;
            out_obs_ts <= 64'd0;
            out_token <= 64'd0;
            out_epoch <= 32'd0;
        end else begin
            out_event <= 1'b0;
            out_valid <= 1'b0;
            if (invalidate) begin
                state_q4 <= 20'sd0;
                warm_state <= 1'b0;
                stream_epoch <= stream_epoch + 32'd1;
                out_event <= 1'b1;
                out_has_sample <= 1'b0;
                out_warm <= 1'b0;
                out_sample <= 16'sd0;
                out_quality <= (invalidate_quality == 8'd0 ? 8'h02 : invalidate_quality) | 8'h01;
                out_seq <= 16'd0;
                out_obs_ts <= 64'd0;
                out_token <= 64'd0;
                out_epoch <= stream_epoch + 32'd1;
            end else if (in_event) begin
                out_event <= 1'b1;
                out_has_sample <= 1'b1;
                out_seq <= in_seq;
                out_obs_ts <= in_obs_ts;
                out_token <= in_token;
                out_epoch <= stream_epoch;
                if (in_quality != 8'd0) begin
                    state_q4 <= 20'sd0;
                    warm_state <= 1'b0;
                    stream_epoch <= stream_epoch + 32'd1;
                    out_epoch <= stream_epoch + 32'd1;
                    out_warm <= 1'b0;
                    out_sample <= 16'sd0;
                    out_quality <= in_quality | 8'h01;
                end else begin
                    state_q4 <= next_state[19:0];
                    warm_state <= 1'b1;
                    out_valid <= 1'b1;
                    out_warm <= 1'b1;
                    out_sample <= clipped;
                    out_quality <= 8'd0;
                end
            end
        end
    end
endmodule
