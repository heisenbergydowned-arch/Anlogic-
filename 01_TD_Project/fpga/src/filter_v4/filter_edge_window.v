`timescale 1ns/1ps
module filter_edge_window #(
    parameter CLK_HZ=100000000,SAMPLE_HZ=4000,ALIGN_CYCLES=CLK_HZ/SAMPLE_HZ,
    parameter TEMP_MAX_CYCLES=CLK_HZ*2,PRESSURE_INDEPENDENT=1,PRESSURE_MAX_MS=100,
    parameter integer FIR_PROFILE=0
) (
    input wire clk,rst_n,input wire [63:0] now_cycles,input wire [31:0] now_ms,
    input wire [31:0] feature_config_id,input wire config_changed,
    input wire a_new,b_new,input wire signed [15:0] ax,ay,az,bx,by,bz,
    input wire [15:0] a_seq,b_seq,input wire a_bad,b_bad,
    input wire adc_new,adc_bad,input wire signed [15:0] current_raw,pressure_raw,
    input wire pressure_new,pressure_bad,temp_new,temp_bad,input wire signed [15:0] temp_raw,
    input wire fg_new,fg_bad,input wire [31:0] fg_period,
    input wire enable,input wire [3:0] control_mode,input wire feature_ready,feature_done,sample_ready,
    output reg frame_start,frame_abort,sample_valid,output reg signed [15:0] sample_data,
    output reg busy,output reg [31:0] frame_id,drop_count,
    output reg [63:0] window_start,window_end,
    output reg [31:0] end_ms,span_a,span_b,align_cycles,adc_count,fg_count,temp_age_ms,
    output reg [31:0] pressure_count,pressure_age_ms,
    output reg signed [47:0] current_sum,pressure_sum,
    output reg [63:0] period_sum,output reg signed [15:0] temperature,
    output reg [15:0] quality,output reg [31:0] sequences,output reg [3:0] frame_mode
);
    generate
        if (CLK_HZ!=100000000 || SAMPLE_HZ!=4000) begin : invalid_clock_contract
            filter_v4_requires_100MHz_4kHz invalid_parameter();
        end
    endgenerate
    wire event_a,event_b,warm_a_now,warm_b_now,abort_frontend,engine_busy;
    wire [47:0] xyz_a,xyz_b;
    wire [7:0] quality_a,quality_b;
    wire [15:0] sequence_a,sequence_b;
    wire [63:0] timestamp_a,timestamp_b;
    wire [1343:0] snapshot_a;
    filter_measurement_frontend #(.PROFILE(FIR_PROFILE),.PRESSURE_INDEPENDENT(PRESSURE_INDEPENDENT)) frontend(
        .clk(clk),.rst_n(rst_n),.now_cycles(now_cycles),.config_id(feature_config_id),.invalidate(config_changed),.control_mode(control_mode),
        .a_new(a_new),.b_new(b_new),.a_xyz({az,ay,ax}),.b_xyz({bz,by,bx}),
        .a_seq(a_seq),.b_seq(b_seq),.a_bad(a_bad),.b_bad(b_bad),
        .adc_new(adc_new),.adc_bad(adc_bad),.current_raw(current_raw),.pressure_raw(pressure_raw),
        .pressure_new(pressure_new),.pressure_bad(pressure_bad),.temp_new(temp_new),.temp_bad(temp_bad),
        .temp_raw(temp_raw),.fg_new(fg_new),.fg_bad(fg_bad),.fg_period(fg_period),
        .a_event(event_a),.b_event(event_b),.a_warm(warm_a_now),.b_warm(warm_b_now),
        .a_value(xyz_a),.b_value(xyz_b),.a_quality(quality_a),.b_quality(quality_b),
        .a_sequence(sequence_a),.b_sequence(sequence_b),.a_timestamp(timestamp_a),.b_timestamp(timestamp_b),
        .a_snapshot(snapshot_a),.abort_window(abort_frontend),.engine_busy(engine_busy)
    );
    reg ready_a,ready_b,have_prefix;
    wire accept_a=event_a && warm_a_now && (ready_b || (event_b && warm_b_now));
    wire accept_b=event_b && warm_b_now && (ready_a || (event_a && warm_a_now));
    reg [47:0] ring_a[0:2047],ring_b[0:2047],read_a,read_b;
    // R46: freeze metadata from the exact B samples selected by base_b.
    // Synchronous RAM avoids a large distributed timestamp/quality register bank.
    reg [95:0] metadata_b[0:2047],metadata_b_read;
    reg metadata_pending,metadata_read_wait,start_pending;
    reg [9:0] metadata_index;
    reg [63:0] selected_start_b,frozen_start_a,frozen_end_a;
    reg [15:0] selected_quality_b;
    wire [63:0] selected_end_b=metadata_b_read[95:32];
    wire [63:0] selected_span_b=selected_end_b-selected_start_b;
    wire [63:0] selected_alignment=frozen_end_a>selected_end_b ? frozen_end_a-selected_end_b : selected_end_b-frozen_end_a;
    reg [10:0] wa,wb,base_a,base_b,tail_a,warm_a,warm_b;
    wire [10:0] metadata_address=base_b+{1'b0,metadata_index};
    reg [9:0] index;
    reg [2:0] axis;
    reg [1:0] feed_state;
    reg pa;
    reg [63:0] first_a,previous_first_a,start_a,boundary_a;
    reg [1343:0] last_prefix,hop_prefix,previous_hop_prefix,bound_start,bound_end;
    reg [15:0] hop_quality_a,previous_quality_a,qa;
    reg [31:0] next_frame_id;
    reg [15:0] last_sequence_a;
    
    wire [10:0] read_a_address=base_a+{1'b0,index},read_b_address=base_b+{1'b0,index};
    wire [47:0] read_word=axis<3 ? read_a : read_b;
    wire [63:0] span64_a=boundary_a-start_a;
    localparam [63:0] EXPECTED_SPAN=64'd1023*CLK_HZ/SAMPLE_HZ;
    wire selected_rate_bad_b=selected_span_b<EXPECTED_SPAN*97/100 || selected_span_b>EXPECTED_SPAN*103/100;
    wire rate_bad_a=span64_a<EXPECTED_SPAN*97/100 || span64_a>EXPECTED_SPAN*103/100;
    wire [63:0] count_i=bound_end[192+:64]-bound_start[192+:64];
    wire [63:0] count_p=bound_end[320+:64]-bound_start[320+:64];
    wire [63:0] count_f=bound_end[448+:64]-bound_start[448+:64];
    wire signed [64:0] delta_i={bound_end[191],bound_end[128+:64]}-{bound_start[191],bound_start[128+:64]};
    wire signed [64:0] delta_p={bound_end[319],bound_end[256+:64]}-{bound_start[319],bound_start[256+:64]};
    wire [63:0] delta_f=bound_end[384+:64]-bound_start[384+:64];
    wire [63:0] endpoint=bound_end[64+:64];
    wire [63:0] age_i=endpoint-bound_end[608+:64],age_p=endpoint-bound_end[672+:64];
    wire [63:0] age_t=endpoint-bound_end[544+:64],age_f=endpoint-bound_end[736+:64];
    wire process_config_bad=bound_start[0+:64]!=bound_end[0+:64]
        || bound_end[32+:32]!=feature_config_id
        || feature_config_id[31:8]!=(FIR_PROFILE==0 ? 24'h2026f4 : 24'h2026f5);
    wire process_overflow=count_i>65535 || count_p>65535 || count_f>64'hffffffff
        || delta_i>65'sd140737488355327 || delta_i < -65'sd140737488355328
        || delta_p>65'sd140737488355327 || delta_p < -65'sd140737488355328;
    wire current_fault=bound_end[832+:64]!=bound_start[832+:64];
    wire temperature_fault=bound_end[896+:64]!=bound_start[896+:64];
    wire pressure_fault=bound_end[960+:64]!=bound_start[960+:64];
    wire fg_fault=bound_end[1024+:64]!=bound_start[1024+:64];
    wire reserved_fault=bound_end[1088+:192]!=bound_start[1088+:192];
    localparam [63:0] PRESSURE_LIMIT=64'd100000*PRESSURE_MAX_MS;
    localparam [63:0] TEMP_LIMIT=TEMP_MAX_CYCLES;
    wire [15:0] process_quality=(process_config_bad ? 16'h1000 : 16'h0000)
        | (bound_end[1280+:64]!=bound_start[1280+:64] ? 16'h2000 : 16'h0000)
        | (process_overflow ? 16'h0008 : 16'h0000)
        | (reserved_fault ? 16'h1000 : 16'h0000)
        | ((current_fault || !bound_end[800] || count_i==0 || age_i>3000) ? 16'h0100 : 16'h0000)
        | ((pressure_fault || !bound_end[801] || count_p==0 || age_p>PRESSURE_LIMIT) ? 16'h0400 : 16'h0000)
        | ((temperature_fault || !bound_end[803] || age_t>TEMP_LIMIT) ? 16'h0200 : 16'h0000)
        | ((fg_fault || !bound_end[802] || count_f==0 || age_f>64'd200000000) ? 16'h0800 : 16'h0000);
    wire rail_a=xyz_a[15:0]==16'h7fff || xyz_a[15:0]==16'h8000
        || xyz_a[31:16]==16'h7fff || xyz_a[31:16]==16'h8000
        || xyz_a[47:32]==16'h7fff || xyz_a[47:32]==16'h8000;
    wire rail_b=xyz_b[15:0]==16'h7fff || xyz_b[15:0]==16'h8000
        || xyz_b[31:16]==16'h7fff || xyz_b[31:16]==16'h8000
        || xyz_b[47:32]==16'h7fff || xyz_b[47:32]==16'h8000;
    wire [15:0] point_quality_a=(quality_a!=0 ? 16'h0010 : 16'h0000)
        | ((quality_a & 8'h24)!=0 || rail_a ? 16'h0004 : 16'h0000);
    wire [15:0] point_quality_b=(quality_b!=0 ? 16'h0020 : 16'h0000)
        | ((quality_b & 8'h24)!=0 || rail_b ? 16'h0004 : 16'h0000);
    wire overwriting=busy && ((accept_a && wa==base_a) || (accept_b && wb==base_b));
    reg age_start,age_pending;
    wire age_done,age_fault;
    wire [31:0] divided_temp_ms,divided_pressure_ms;
    filter_age_ms_pair age_converter(
        .clk(clk),.rst_n(rst_n),.start(age_start),
        .cancel(abort_frontend || config_changed || overwriting),
        .temp_seen(bound_end[803]),.pressure_seen(bound_end[801]),
        .temp_age(age_t),.pressure_age(age_p),.busy(),.done(age_done),.fault(age_fault),
        .temp_ms(divided_temp_ms),.pressure_ms(divided_pressure_ms)
    );
    always @(posedge clk) begin
        if (accept_a)ring_a[wa]<=xyz_a;
        if (busy && feed_state==0 && !sample_valid)read_a<=ring_a[read_a_address];
    end
    always @(posedge clk) begin
        if (accept_b)begin
            ring_b[wb]<=xyz_b;
            metadata_b[wb]<={timestamp_b,sequence_b,point_quality_b};
        end
        if (busy && metadata_pending && !metadata_read_wait)metadata_b_read<=metadata_b[metadata_address];
        if (busy && feed_state==0 && !sample_valid)read_b<=ring_b[read_b_address];
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ready_a<=0;ready_b<=0;have_prefix<=0;last_prefix<=0;hop_prefix<=0;previous_hop_prefix<=0;bound_start<=0;bound_end<=0;
            wa<=0;wb<=0;base_a<=0;base_b<=0;tail_a<=0;warm_a<=0;warm_b<=0;index<=0;axis<=0;feed_state<=0;
            pa<=0;first_a<=0;previous_first_a<=0;
            start_a<=0;boundary_a<=0;
            hop_quality_a<=0;previous_quality_a<=0;qa<=0;
            next_frame_id<=0;last_sequence_a<=0;
            frame_start<=0;frame_abort<=0;sample_valid<=0;sample_data<=0;busy<=0;frame_id<=0;drop_count<=0;
            window_start<=0;window_end<=0;end_ms<=0;span_a<=0;span_b<=0;align_cycles<=0;
            adc_count<=0;fg_count<=0;temp_age_ms<=0;pressure_count<=0;pressure_age_ms<=0;
            current_sum<=0;pressure_sum<=0;period_sum<=0;temperature<=0;quality<=0;sequences<=0;frame_mode<=0;
            age_start<=0;age_pending<=0;
            metadata_pending<=0;metadata_read_wait<=0;start_pending<=0;metadata_index<=0;
            selected_start_b<=0;selected_quality_b<=0;frozen_start_a<=0;frozen_end_a<=0;
        end else begin
            frame_start<=0;frame_abort<=0;age_start<=0;
            if (event_a)begin ready_a<=warm_a_now;last_prefix<=snapshot_a;have_prefix<=1;end
            if (event_b)ready_b<=warm_b_now;
            if (accept_a) begin
                wa<=wa+11'd1;if(warm_a<1024)warm_a<=warm_a+11'd1;
                hop_quality_a<=hop_quality_a | point_quality_a;
                if (wa[8:0]==0) begin
                    first_a<=timestamp_a;hop_prefix<=last_prefix;
                    if (!have_prefix || last_prefix[0+:64]!=snapshot_a[0+:64])hop_quality_a<=hop_quality_a | point_quality_a | 16'h1000;
                end
                if (wa[8:0]==511) begin
                    boundary_a<=timestamp_a;start_a<=previous_first_a;tail_a<=wa+11'd1;pa<=1;
                    last_sequence_a<=sequence_a;
                    qa<=previous_quality_a | hop_quality_a | point_quality_a;
                    previous_first_a<=first_a;previous_quality_a<=hop_quality_a | point_quality_a;hop_quality_a<=0;
                    bound_start<=previous_hop_prefix;bound_end<=snapshot_a;previous_hop_prefix<=hop_prefix;
                end
            end
            if (accept_b) begin
                wb<=wb+11'd1;if(warm_b<1024)warm_b<=warm_b+11'd1;

            end
            if(pa) begin
                pa<=0;
                if(warm_a>=1024 && warm_b>=1024)begin
                    next_frame_id<=next_frame_id+32'd1;
                    if(!busy && feature_ready && enable)begin
                        frame_id<=next_frame_id+32'd1;base_a<=tail_a-11'd1024;base_b<=wb-11'd1024;
                        frozen_start_a<=start_a;frozen_end_a<=boundary_a;
                        window_start<=start_a;window_end<=boundary_a;
                        metadata_pending<=1;metadata_read_wait<=0;metadata_index<=0;
                        selected_quality_b<=0;start_pending<=1;
                        end_ms<=now_ms;span_a<=span64_a[31:0];span_b<=0;align_cycles<=0;
                        adc_count<=count_i[31:0];pressure_count<=count_p[31:0];fg_count<=count_f[31:0];
                        current_sum<=delta_i[47:0];pressure_sum<=delta_p[47:0];period_sum<=delta_f;
                        temperature<=bound_end[512+:16];
                        frame_mode<=bound_end[804+:4];
                        quality<=qa | process_quality | (rate_bad_a ? 16'h0040 : 16'h0000);
                        sequences<={16'd0,last_sequence_a};
                        age_start<=1;age_pending<=1;busy<=1;axis<=0;index<=0;feed_state<=0;sample_valid<=0;
                    end else drop_count<=drop_count+32'd1;
                end
            end
            if(age_done && age_pending && !age_fault) begin
                temp_age_ms<=divided_temp_ms;pressure_age_ms<=divided_pressure_ms;
                age_pending<=0;
            end
            if(busy && metadata_pending)begin
                if(!metadata_read_wait)metadata_read_wait<=1;
                else begin
                    metadata_read_wait<=0;
                    selected_quality_b<=selected_quality_b | metadata_b_read[15:0];
                    if(metadata_index==0)selected_start_b<=metadata_b_read[95:32];
                    if(metadata_index==1023)begin
                        metadata_pending<=0;
                        span_b<=selected_span_b[31:0];align_cycles<=selected_alignment[31:0];
                        window_start<=frozen_start_a<selected_start_b ? frozen_start_a : selected_start_b;
                        window_end<=frozen_end_a>selected_end_b ? frozen_end_a : selected_end_b;
                        sequences[31:16]<=metadata_b_read[31:16];
                        quality<=quality | selected_quality_b | metadata_b_read[15:0] | (selected_rate_bad_b ? 16'h0080 : 16'h0000);
                        // Unpairable windows never become an apparently valid frame.
                        if(selected_alignment>ALIGN_CYCLES || selected_alignment>64'hffffffff || selected_span_b>64'hffffffff)begin
                            busy<=0;frame_abort<=1;start_pending<=0;age_pending<=0;
                            sample_valid<=0;drop_count<=drop_count+32'd1;
                        end
                    end else metadata_index<=metadata_index+10'd1;
                end
            end
            if(busy && !metadata_pending && !age_pending && start_pending)begin
                frame_start<=1;start_pending<=0;
            end
            if(busy && !age_pending && !metadata_pending && !start_pending)begin
                if(feed_state==0 && !sample_valid)feed_state<=1;
                else if(feed_state==1)begin
                    case(axis)
                        0,3:sample_data<=read_word[15:0];
                        1,4:sample_data<=read_word[31:16];
                        default:sample_data<=read_word[47:32];
                    endcase
                    sample_valid<=1;feed_state<=2;
                end else if(sample_valid && sample_ready)begin
                    sample_valid<=0;
                    if(index==1023)begin
                        index<=0;
                        if(axis==5)feed_state<=3;
                        else begin axis<=axis+3'd1;feed_state<=0;end
                    end else begin index<=index+10'd1;feed_state<=0;end
                end
                if(feature_done)begin busy<=0;sample_valid<=0;feed_state<=0;end
            end
            if(abort_frontend || config_changed || overwriting || age_fault)begin
                ready_a<=0;ready_b<=0;wa<=0;wb<=0;warm_a<=0;warm_b<=0;pa<=0;
                hop_quality_a<=0;previous_quality_a<=0;
                busy<=0;frame_start<=0;frame_abort<=1;sample_valid<=0;feed_state<=0;
                age_start<=0;age_pending<=0;metadata_pending<=0;metadata_read_wait<=0;start_pending<=0;
                if(busy || pa)drop_count<=drop_count+32'd1;
                if(config_changed)have_prefix<=0;
            end
        end
    end
endmodule
