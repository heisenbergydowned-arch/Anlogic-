`timescale 1ns/1ps
module filter_measurement_frontend #(
    parameter integer PROFILE=0,
    parameter integer PRESSURE_INDEPENDENT=1
) (
    input wire clk,rst_n,input wire [63:0] now_cycles,
    input wire [31:0] config_id,input wire invalidate,input wire [3:0] control_mode,
    input wire a_new,b_new,input wire [47:0] a_xyz,b_xyz,
    input wire [15:0] a_seq,b_seq,input wire a_bad,b_bad,
    input wire adc_new,adc_bad,input wire signed [15:0] current_raw,pressure_raw,
    input wire pressure_new,pressure_bad,temp_new,temp_bad,fg_new,fg_bad,
    input wire signed [15:0] temp_raw,input wire [31:0] fg_period,
    output reg a_event,b_event,output reg a_warm,b_warm,
    output reg [47:0] a_value,b_value,output reg [7:0] a_quality,b_quality,
    output reg [15:0] a_sequence,b_sequence,output reg [63:0] a_timestamp,b_timestamp,
    output reg [1343:0] a_snapshot,
    output reg abort_window,output wire engine_busy
);
    reg [63:0] a_token,b_token,last_a,last_b,last_adc;
    reg timeout_a,timeout_b,timeout_adc,previous_a_bad,previous_b_bad,previous_adc_bad;
    wire stale_a=!timeout_a && now_cycles-last_a>64'd43750;
    wire stale_b=!timeout_b && now_cycles-last_b>64'd43750;
    wire stale_adc=!timeout_adc && now_cycles-last_adc>64'd3000;
    wire invalidate_a=stale_a || (a_bad && !previous_a_bad) || invalidate;
    wire invalidate_b=stale_b || (b_bad && !previous_b_bad) || invalidate;
    wire invalidate_adc=stale_adc || (adc_bad && !previous_adc_bad) || invalidate;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_token<=0;b_token<=0;last_a<=0;last_b<=0;last_adc<=0;
            timeout_a<=0;timeout_b<=0;timeout_adc<=0;
            previous_a_bad<=0;previous_b_bad<=0;previous_adc_bad<=0;
        end else begin
            previous_a_bad<=a_bad;previous_b_bad<=b_bad;previous_adc_bad<=adc_bad;
            if (a_new)begin a_token<=a_token+64'd1;last_a<=now_cycles;timeout_a<=0;end
            else if (stale_a)timeout_a<=1;
            if (b_new)begin b_token<=b_token+64'd1;last_b<=now_cycles;timeout_b<=0;end
            else if (stale_b)timeout_b<=1;
            if (adc_new)begin last_adc<=now_cycles;timeout_adc<=0;end
            else if (stale_adc)timeout_adc<=1;
            if (invalidate)begin
                last_a<=now_cycles;last_b<=now_cycles;last_adc<=now_cycles;
                timeout_a<=0;timeout_b<=0;timeout_adc<=0;
            end
        end
    end
    wire fa_event,fb_event,fa_sample,fb_sample,fa_warm,fb_warm;
    wire [47:0] fa_xyz,fb_xyz;
    wire [7:0] fa_quality,fb_quality;
    wire [15:0] fa_seq,fb_seq;
    wire [63:0] fa_ts,fb_ts,fa_token;
    filter_vib_fir_shared #(.PROFILE(PROFILE)) fir(
        .clk(clk),.rst_n(rst_n),.a_event(a_new),.b_event(b_new),.a_xyz(a_xyz),.b_xyz(b_xyz),
        .a_raw_err(a_bad),.b_raw_err(b_bad),.a_seq(a_seq),.b_seq(b_seq),
        .a_obs_ts(now_cycles),.b_obs_ts(now_cycles),.a_token(a_token),.b_token(b_token),
        .a_invalidate(invalidate_a),.b_invalidate(invalidate_b),
        .a_invalidate_quality(invalidate ? 8'h80 : 8'h02),.b_invalidate_quality(invalidate ? 8'h80 : 8'h02),
        .a_out_event(fa_event),.b_out_event(fb_event),.a_out_has_sample(fa_sample),.b_out_has_sample(fb_sample),
        .a_out_valid(),.b_out_valid(),.a_out_warm(fa_warm),.b_out_warm(fb_warm),
        .a_out_xyz(fa_xyz),.b_out_xyz(fb_xyz),.a_out_quality(fa_quality),.b_out_quality(fb_quality),
        .a_out_seq(fa_seq),.b_out_seq(fb_seq),.a_out_obs_ts(fa_ts),.b_out_obs_ts(fb_ts),
        .a_out_token(fa_token),.b_out_token(),.a_out_epoch(),.b_out_epoch(),
        .busy(engine_busy)
    );
    reg [15:0] adc_sequence;
    always @(posedge clk or negedge rst_n)
        if (!rst_n)adc_sequence<=0;else if (adc_new)adc_sequence<=adc_sequence+16'd1;
    wire current_event,current_has_sample,current_valid;
    wire signed [15:0] current_value;
    wire [7:0] current_quality;
    wire [63:0] current_ts;
    filter_current_boxcar32 current_filter(
        .clk(clk),.rst_n(rst_n),.in_event(adc_new),.in_sample(current_raw),.in_raw_err(adc_bad),
        .in_seq(adc_sequence),.in_obs_ts(now_cycles),.in_token(64'd0),
        .invalidate(invalidate_adc),.invalidate_quality(invalidate ? 8'h80 : 8'h02),
        .out_event(current_event),.out_has_sample(current_has_sample),.out_valid(current_valid),
        .out_warm(),.out_sample(current_value),.out_quality(current_quality),
        .out_seq(),.out_obs_ts(current_ts),.out_token(),.out_epoch()
    );
    reg batch_valid,batch_a,batch_pressure,batch_temp,batch_fg;
    reg [63:0] batch_ts,batch_token;
    reg signed [15:0] batch_pressure_value,batch_temp_value;
    reg [31:0] batch_period;
    reg batch_pressure_bad,batch_temp_bad,batch_fg_bad,batch_mode_bad,mode_seen;
    reg [3:0] last_mode,batch_mode;
    wire raw_pressure_event=PRESSURE_INDEPENDENT!=0 ? pressure_new : adc_new;
    wire raw_pressure_bad=(PRESSURE_INDEPENDENT!=0 ? pressure_bad : adc_bad)
        || (raw_pressure_event && (pressure_raw==16'sh8000 || pressure_raw==16'sh7fff));
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            batch_valid<=0;batch_a<=0;batch_pressure<=0;batch_temp<=0;batch_fg<=0;batch_ts<=0;batch_token<=0;
            batch_pressure_value<=0;batch_temp_value<=0;batch_period<=0;
            batch_pressure_bad<=0;batch_temp_bad<=0;batch_fg_bad<=0;batch_mode_bad<=0;mode_seen<=0;last_mode<=0;batch_mode<=0;
        end else begin
            batch_valid<=1;batch_a<=a_new;batch_ts<=now_cycles;batch_token<=a_token;
            batch_pressure<=raw_pressure_event && !raw_pressure_bad;
            batch_pressure_value<=pressure_raw;batch_temp<=temp_new && !temp_bad;batch_temp_value<=temp_raw;
            batch_fg<=fg_new && !fg_bad && fg_period!=0;batch_period<=fg_period;
            batch_pressure_bad<=raw_pressure_bad;batch_temp_bad<=temp_bad;
            batch_fg_bad<=fg_bad || (fg_new && fg_period==0);
            batch_mode_bad<=control_mode!=3 || (mode_seen && control_mode!=last_mode);
            mode_seen<=1;last_mode<=control_mode;batch_mode<=control_mode;
        end
    end
    reg held_a_event,held_a_sample,held_a_warm;
    reg [47:0] held_a_xyz;
    reg [7:0] held_a_quality;
    reg [15:0] held_a_seq;
    reg [63:0] held_a_ts,held_a_token;
    wire lookup_found,prefix_fault;
    wire [1343:0] lookup_record;
    wire fir_fault=(fa_event && (fa_quality & 8'hde)!=0)
        || (fb_event && (fb_quality & 8'hde)!=0);
    wire [7:0] process_bad=(current_event && current_quality!=0 ? 8'h01 : 8'h00)
        | (batch_temp_bad ? 8'h02 : 8'h00)
        | (batch_pressure_bad ? 8'h04 : 8'h00)
        | (batch_fg_bad ? 8'h08 : 8'h00)
        | (batch_mode_bad ? 8'h80 : 8'h00);
    filter_prefix_snapshot #(.SYNC_LOOKUP(1)) prefix(
        .clk(clk),.rst_n(rst_n),.tick_valid(batch_valid),.obs_ts(batch_ts),.config_id(config_id),.observation_mode(batch_mode),
        .current_event(current_event && current_valid),.current_value(current_value),
        .pressure_event(batch_pressure),.pressure_value(batch_pressure_value),
        .fg_event(batch_fg),.fg_period(batch_period),.temp_event(batch_temp),.temperature(batch_temp_value),
        .bad_quality(process_bad),.invalidate(invalidate || fir_fault || (current_event && current_has_sample && current_ts!=batch_ts)),
        .invalidate_quality(invalidate ? 8'h80 : 8'h02),
        .capture(batch_valid && batch_a),.capture_token(batch_token),
        .release_snapshot(held_a_event && held_a_sample && lookup_found),.release_token(held_a_token),
        .lookup(fa_event && fa_sample),.lookup_token(fa_token),
        .lookup_found(lookup_found),.lookup_record(lookup_record),
        .capture_event(),.capture_ok(),.fault_event(prefix_fault),
        .fault_quality(),.stream_epoch()
    );
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            held_a_event<=0;held_a_sample<=0;held_a_warm<=0;
            held_a_xyz<=0;held_a_quality<=0;held_a_seq<=0;held_a_ts<=0;held_a_token<=0;
            a_event<=0;b_event<=0;a_warm<=0;b_warm<=0;a_value<=0;b_value<=0;
            a_quality<=0;b_quality<=0;a_sequence<=0;b_sequence<=0;a_timestamp<=0;b_timestamp<=0;
            a_snapshot<=0;abort_window<=0;
        end else begin
            held_a_event<=fa_event;held_a_sample<=fa_sample;held_a_warm<=fa_warm;
            held_a_xyz<=fa_xyz;held_a_quality<=fa_quality;held_a_seq<=fa_seq;held_a_ts<=fa_ts;held_a_token<=fa_token;
            a_event<=0;b_event<=0;abort_window<=invalidate || prefix_fault || fir_fault;
            if (held_a_event) begin
                if (held_a_sample && lookup_found && !prefix_fault && !invalidate) begin
                    a_event<=1;a_warm<=held_a_warm;a_value<=held_a_xyz;a_quality<=held_a_quality;
                    a_sequence<=held_a_seq;a_timestamp<=held_a_ts;a_snapshot<=lookup_record;
                end else abort_window<=1;
            end
            if (fb_event) begin
                if (fb_sample && !prefix_fault && !invalidate) begin
                    b_event<=1;b_warm<=fb_warm;b_value<=fb_xyz;b_quality<=fb_quality;
                    b_sequence<=fb_seq;b_timestamp<=fb_ts;
                end else abort_window<=1;
            end
        end
    end
endmodule
