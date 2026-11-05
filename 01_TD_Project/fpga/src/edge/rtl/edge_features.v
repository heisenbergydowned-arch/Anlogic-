`timescale 1ns/1ps
module edge_features #(
    parameter CLK_HZ=100000000,parameter TEST_MODE=0,
    parameter PRESSURE_INDEPENDENT=0,parameter BUILD_ID=32'h202610f4,parameter HAS_ENVIRONMENT=0
)(
    input wire clk,rst_n,input wire [31:0] now_ms,
    input wire a_new,b_new,input wire signed [15:0] ax,ay,az,bx,by,bz,
    input wire [15:0] a_seq,b_seq,input wire a_bad,b_bad,
    input wire adc_new,adc_bad,input wire signed [15:0] current_raw,pressure_raw,
    input wire pressure_new,pressure_bad,
    input wire temp_new,temp_bad,input wire signed [15:0] temp_raw,
    input wire fg_new,fg_bad,input wire [31:0] fg_period,
    input wire [3:0] control_mode,input wire local_permit,input wire initial_config_permit,
    input wire req,write_en,input wire [15:0] address,input wire [31:0] wdata,
    output wire response,output wire [31:0] rdata,output wire [7:0] error,
    output wire frame_available,output wire busy,
    output wire [63:0] acquisition_cycles,
    output reg [31:0] latest_frame_id,
    output reg [63:0] latest_window_start,latest_window_end
);
    reg [63:0] now_cycles;always @(posedge clk or negedge rst_n)if(!rst_n)now_cycles<=0;else now_cycles<=now_cycles+1;
    assign acquisition_cycles=now_cycles;
    wire window_start_pulse,abort,sample_valid,sample_ready,feature_ready,feature_done;
    wire signed [15:0] sample_data;
    wire [31:0] frame_id,drops,end_ms,span_a,span_b,align_cycles,adc_count,fg_count,temp_age_ms,sequences;
    wire [31:0] pressure_count,pressure_age_ms;
    wire [63:0] window_start,window_end,period_sum;
    wire signed [47:0] current_sum,pressure_sum;wire signed [15:0] temperature;
    wire [15:0] window_quality;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin latest_frame_id<=0;latest_window_start<=0;latest_window_end<=0;end
        else if(feature_done)begin latest_frame_id<=frame_id;latest_window_start<=window_start;latest_window_end<=window_end;end
    end

    wire [543:0] cfg;wire config_changed;
    reg configuring;reg [3:0] config_index;
    reg start_convert,start_feature;
    wire [3:0] frame_mode;
    wire reset_engine=rst_n && !abort;
    wire mean_done,convert_done;
    wire signed [31:0] current_mean,pressure_mean,current_q16,temp_q16,pressure_q16,rpm_q16;
    wire [31:0] period_mean;wire [15:0] mean_quality,convert_quality;
    wire feature_busy,window_busy;
    assign busy=feature_busy || window_busy || configuring;
    // The extractor's abort reset also resets its edge registers. Reapply
    // the retained mailbox configuration before admitting another window.
    wire cfg_we=configuring && feature_ready && !abort && !config_changed;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin configuring<=1;config_index<=0;start_convert<=0;start_feature<=0;end
        else begin
            start_convert<=mean_done;start_feature<=convert_done;
            if(config_changed || abort)begin configuring<=1;config_index<=0;end
            else if(cfg_we)begin
                if(config_index==8)configuring<=0;else config_index<=config_index+1;
            end
            if(abort || config_changed || configuring)begin start_convert<=0;start_feature<=0;end
        end
    end
    filter_edge_window #(.CLK_HZ(CLK_HZ),.PRESSURE_INDEPENDENT(PRESSURE_INDEPENDENT)) windows(.clk(clk),.rst_n(rst_n),.now_cycles(now_cycles),.now_ms(now_ms),
        .feature_config_id(cfg[0+:32]),.config_changed(config_changed),
        .a_new(a_new),.b_new(b_new),.ax(ax),.ay(ay),.az(az),.bx(bx),.by(by),.bz(bz),
        .a_seq(a_seq),.b_seq(b_seq),.a_bad(a_bad),.b_bad(b_bad),
        .adc_new(adc_new),.adc_bad(adc_bad),.current_raw(current_raw),.pressure_raw(pressure_raw),
        .pressure_new(pressure_new),.pressure_bad(pressure_bad),
        .temp_new(temp_new),.temp_bad(temp_bad),.temp_raw(temp_raw),
        .fg_new(fg_new),.fg_bad(fg_bad),.fg_period(fg_period),
        .enable(!configuring && !config_changed),.control_mode(control_mode),.feature_ready(feature_ready),.feature_done(feature_done),.sample_ready(sample_ready),
        .frame_start(window_start_pulse),.frame_abort(abort),.sample_valid(sample_valid),.sample_data(sample_data),.busy(window_busy),
        .frame_id(frame_id),.drop_count(drops),.window_start(window_start),.window_end(window_end),.end_ms(end_ms),
        .span_a(span_a),.span_b(span_b),.align_cycles(align_cycles),.adc_count(adc_count),.fg_count(fg_count),.temp_age_ms(temp_age_ms),
        .pressure_count(pressure_count),.pressure_age_ms(pressure_age_ms),
        .current_sum(current_sum),.pressure_sum(pressure_sum),.period_sum(period_sum),.temperature(temperature),
        .quality(window_quality),.sequences(sequences),.frame_mode(frame_mode));
    edge_window_mean #(.PRESSURE_INDEPENDENT(PRESSURE_INDEPENDENT)) averages(.clk(clk),.rst_n(reset_engine),.start(window_start_pulse),
        .current_sum(current_sum),.pressure_sum(pressure_sum),.adc_count(adc_count),.period_sum(period_sum),.fg_count(fg_count),
        .pressure_count(pressure_count),
        .done(mean_done),.current_mean(current_mean),.pressure_mean(pressure_mean),.period_mean(period_mean),.quality(mean_quality));
    feature_process_convert #(.CLK_HZ(CLK_HZ),.RUNTIME_CONFIG(1)) process_convert(
        .clk(clk),.rst_n(reset_engine),.start(start_convert),.current_mean_code_q16(current_mean),.pressure_mean_code_q16(pressure_mean),
        .temperature_raw(temperature),.fg_mean_period(period_mean),.valid_mask({!window_quality[11],!window_quality[10],!window_quality[9],!window_quality[8]}),
        .cfg_current_zero(cfg[96+:32]),.cfg_pressure_zero(cfg[128+:32]),.cfg_current_slope(cfg[160+:32]),.cfg_pressure_slope(cfg[192+:32]),.cfg_ppr(cfg[224+:4]),
        .busy(),.done(convert_done),.current_q16(current_q16),.temp_q16(temp_q16),.pressure_q16(pressure_q16),.rpm_q16(rpm_q16),.quality(convert_quality));
    wire out_valid,out_last;wire [5:0] out_index;wire [31:0] out_fp32,out_frame_id;wire signed [31:0] out_q16;wire [15:0] out_quality;
    wire [15:0] input_quality=window_quality | mean_quality | convert_quality
        | ((cfg[64] && cfg[32+:32]!=0)?16'd0:16'h1000) | (TEST_MODE ? 16'h4000:16'd0);
    feature_extract extractor(.clk(clk),.rst_n(reset_engine),.frame_start(start_feature),.frame_ready(feature_ready),.frame_id(frame_id),
        .current_q16(current_q16),.temp_q16(temp_q16),.pressure_q16(pressure_q16),.rpm_q16(rpm_q16),.input_quality(input_quality),
        .sample_valid(sample_valid),.sample_ready(sample_ready),.sample_data(sample_data),
        .cfg_we(cfg_we),.cfg_index(config_index),.cfg_edge(cfg[(8+config_index)*32+:10]),
        .busy(feature_busy),.out_valid(out_valid),.out_ready(1'b1),.out_index(out_index),.out_q16(out_q16),.out_fp32(out_fp32),
        .out_last(out_last),.out_frame_id(out_frame_id),.out_quality(out_quality),.frame_done(feature_done));
    // All window/process/config fields are held while the engine is busy.
    // The acquisition drop counter alone may advance during output; freeze its
    // exact index-0 value so serial header storage sees one immutable snapshot.
    reg [31:0] header_drops;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)header_drops<=0;
        else if(out_valid && out_index==0)header_drops<=drops;
    end
    reg [1023:0] header;
    always @* begin
        header=0;
        header[0+:32]=32'h46524d31;header[32+:32]=32'h00010000;header[64+:32]=284;header[96+:32]=out_frame_id;
        header[128+:32]=end_ms;header[160+:64]=window_start;header[224+:64]=window_end;
        header[288+:32]=span_a;header[320+:32]=span_b;header[352+:32]=1024;header[384+:32]=1024;
        header[416+:32]=PRESSURE_INDEPENDENT ? {pressure_count[15:0],adc_count[15:0]}:adc_count;
        header[448+:32]=fg_count;header[480+:32]={16'd0,out_quality};
        header[512+:32]=cfg[0+:32];header[544+:32]=cfg[32+:32];header[576+:32]=PRESSURE_INDEPENDENT ? 2:1;
        header[608+:32]={28'd0,frame_mode};header[640+:32]=4000;header[672+:32]=CLK_HZ;
        header[704+:32]=50000;header[736+:32]=out_index==0 ? drops:header_drops;header[768+:32]=temp_age_ms;header[800+:32]=align_cycles;
        header[832+:32]=BUILD_ID;header[864+:32]=TEST_MODE;header[896+:32]=sequences;
        header[928+:32]=current_mean;header[960+:32]=pressure_mean;header[992+:32]=period_mean;
    end
    edge_mailbox #(.SERIAL_HEADER_STABLE(1),.PRESSURE_INDEPENDENT(PRESSURE_INDEPENDENT),.HAS_ENVIRONMENT(HAS_ENVIRONMENT)) mailbox(.clk(clk),.rst_n(rst_n),.engine_busy(busy),.local_permit(local_permit),.initial_config_permit(initial_config_permit),
        .in_valid(out_valid),.in_abort(abort),.in_index(out_index),.in_fp32(out_fp32),.in_header(header),
        .req(req),.write_en(write_en),.address(address),.wdata(wdata),.response(response),.rdata(rdata),.error(error),
        .config_words(cfg),.config_changed(config_changed),.frame_available(frame_available),.dropped());
endmodule
