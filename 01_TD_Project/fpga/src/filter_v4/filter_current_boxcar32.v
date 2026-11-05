`timescale 1ns/1ps
module filter_current_boxcar32 (
    input wire clk,
    input wire rst_n,
    input wire in_event,
    input wire signed [15:0] in_sample,
    input wire in_raw_err,
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
    reg signed [15:0] history [0:31];
    reg signed [20:0] total;
    reg [4:0] write_index;
    reg [5:0] warm_count;
    reg have_last;
    reg [15:0] last_seq;
    reg [63:0] last_ts;
    reg [31:0] stream_epoch;
    wire [63:0] interval_cycles = in_obs_ts - last_ts;
    wire seq_gap = have_last && in_seq != last_seq + 16'd1;
    wire time_gap = have_last && (interval_cycles < 64'd1000 || interval_cycles > 64'd3000);
    wire raw_rail = in_sample == 16'sh8000 || in_sample == 16'sh7fff;
    wire [7:0] source_quality = {3'b000, time_gap, seq_gap, raw_rail, in_raw_err, 1'b0};
    wire signed [21:0] previous_total = {total[20], total};
    wire signed [21:0] incoming = {{6{in_sample[15]}}, in_sample};
    wire signed [15:0] outgoing_sample = warm_count == 6'd32 ? history[write_index] : 16'sd0;
    wire signed [21:0] outgoing = {{6{outgoing_sample[15]}}, outgoing_sample};
    wire signed [21:0] next_total = previous_total + incoming - outgoing;
    wire signed [21:0] rounded = next_total[21]
        ? -(((-next_total) + 22'sd16) >>> 5)
        : (next_total + 22'sd16) >>> 5;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            total <= 21'sd0;
            write_index <= 5'd0;
            warm_count <= 6'd0;
            have_last <= 1'b0;
            last_seq <= 16'd0;
            last_ts <= 64'd0;
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
                total <= 21'sd0;
                write_index <= 5'd0;
                warm_count <= 6'd0;
                have_last <= 1'b0;
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
                have_last <= 1'b1;
                last_seq <= in_seq;
                last_ts <= in_obs_ts;
                out_event <= 1'b1;
                out_has_sample <= 1'b1;
                out_seq <= in_seq;
                out_obs_ts <= in_obs_ts;
                out_token <= in_token;
                out_epoch <= stream_epoch;
                if (source_quality != 8'd0) begin
                    total <= 21'sd0;
                    write_index <= 5'd0;
                    warm_count <= 6'd0;
                    stream_epoch <= stream_epoch + 32'd1;
                    out_epoch <= stream_epoch + 32'd1;
                    out_warm <= 1'b0;
                    out_sample <= in_sample;
                    out_quality <= source_quality | 8'h01;
                end else begin
                    history[write_index] <= in_sample;
                    write_index <= write_index + 5'd1;
                    total <= next_total[20:0];
                    if (warm_count < 6'd32)
                        warm_count <= warm_count + 6'd1;
                    out_warm <= warm_count >= 6'd31;
                    out_valid <= warm_count >= 6'd31;
                    out_sample <= warm_count >= 6'd31 ? rounded[15:0] : in_sample;
                    out_quality <= warm_count >= 6'd31 ? 8'h00 : 8'h01;
                end
            end
        end
    end
endmodule
