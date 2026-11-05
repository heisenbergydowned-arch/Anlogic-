`timescale 1ns/1ps
// Two packed XYZ rings, 2048 samples/point. A frame owns 1024 samples until
// feature completion. New acquisition NEVER waits for FFT/PS. If retention is
// exhausted, abort the whole feature frame; never read overwritten samples.
// Pair the independently timestamped A/B half-window boundaries, not seq IDs.
module edge_window #(
    parameter CLK_HZ=100000000,parameter SAMPLE_HZ=4000,
    parameter ALIGN_CYCLES=CLK_HZ/SAMPLE_HZ,
    parameter TEMP_MAX_CYCLES=CLK_HZ*2,
    parameter PRESSURE_INDEPENDENT=0,parameter PRESSURE_MAX_MS=100
)(
    input wire clk,rst_n,input wire [63:0] now_cycles,input wire [31:0] now_ms,
    input wire a_new,b_new,input wire signed [15:0] ax,ay,az,bx,by,bz,
    input wire [15:0] a_seq,b_seq,input wire a_bad,b_bad,
    input wire adc_new,adc_bad,input wire signed [15:0] current_raw,pressure_raw,
    input wire pressure_new,pressure_bad,
    input wire temp_new,temp_bad,input wire signed [15:0] temp_raw,
    input wire fg_new,fg_bad,input wire [31:0] fg_period,
    input wire enable,input wire [3:0] control_mode,input wire feature_ready,feature_done,input wire sample_ready,
    output reg frame_start,frame_abort,output reg sample_valid,output reg signed [15:0] sample_data,
    output reg busy,output reg [31:0] frame_id,drop_count,
    output reg [63:0] window_start,window_end,
    output reg [31:0] end_ms,span_a,span_b,align_cycles,adc_count,fg_count,temp_age_ms,
    output reg [31:0] pressure_count,pressure_age_ms,
    output reg signed [47:0] current_sum,pressure_sum,
    output reg [63:0] period_sum,output reg signed [15:0] temperature,
    output reg [15:0] quality,output reg [31:0] sequences
);
    reg [47:0] ring_a[0:2047],ring_b[0:2047];
    reg [10:0] wa,wb,base_a,base_b;reg [9:0] index;reg [2:0] axis;
    reg [10:0] warm_a,warm_b;reg pa,pb,prev_a,prev_b;
    reg [63:0] last_a,last_b,first_a,first_b,previous_first_a,previous_first_b;
    reg [63:0] boundary_a,boundary_b,start_a,start_b,temp_stamp;
    reg [10:0] tail_a,tail_b;reg [15:0] last_seq_a,last_seq_b;
    reg [15:0] hop_quality_a,hop_quality_b,previous_quality_a,previous_quality_b,qa,qb;
    reg [47:0] read_a,read_b;reg [1:0] feed_state;
    reg signed [47:0] sum_i,sum_p,prev_i,prev_p,bound_i,bound_p;
    reg [31:0] count_adc,prev_adc,bound_adc;
    reg [31:0] count_pressure,prev_pressure,bound_pressure,last_pressure_ms,bound_pressure_age;
    reg [63:0] sum_fg,prev_fg,bound_fg;
    reg [31:0] count_fg,prev_count_fg,bound_count_fg;
    reg adc_seen,temp_seen,fg_seen,adc_hop_bad,adc_prev_bad,adc_bound_bad;
    reg pressure_seen,pressure_hop_bad,pressure_prev_bad,pressure_bound_bad;
    reg mode_hop_bad,mode_prev_bad,mode_seen;reg [3:0] last_mode;
    reg fg_hop_bad,fg_prev_bad,fg_bound_bad;
    reg [31:0] temp_ms,next_frame_id;
    localparam PERIOD=CLK_HZ/SAMPLE_HZ;
    wire gap_a=prev_a && ((now_cycles-last_a)<PERIOD/4 || (now_cycles-last_a)>PERIOD*7/4 || a_seq!=last_seq_a+16'd1);
    wire gap_b=prev_b && ((now_cycles-last_b)<PERIOD/4 || (now_cycles-last_b)>PERIOD*7/4 || b_seq!=last_seq_b+16'd1);
    wire rail_a=ax==16'sh7fff || ax==16'sh8000 || ay==16'sh7fff || ay==16'sh8000 || az==16'sh7fff || az==16'sh8000;
    wire rail_b=bx==16'sh7fff || bx==16'sh8000 || by==16'sh7fff || by==16'sh8000 || bz==16'sh7fff || bz==16'sh8000;
    wire [63:0] delta=boundary_a>boundary_b ? boundary_a-boundary_b:boundary_b-boundary_a;
    wire [10:0] read_a_address=base_a+{1'b0,index},read_b_address=base_b+{1'b0,index};
    localparam [63:0] EXPECTED_SPAN=64'd1023*CLK_HZ/SAMPLE_HZ;
    wire rate_a_bad=boundary_a-start_a<EXPECTED_SPAN*97/100 || boundary_a-start_a>EXPECTED_SPAN*103/100;
    wire rate_b_bad=boundary_b-start_b<EXPECTED_SPAN*97/100 || boundary_b-start_b>EXPECTED_SPAN*103/100;
    wire overwriting=busy && ((a_new && wa==base_a)||(b_new && wb==base_b));
    wire current_rail=adc_new && (current_raw==16'sh7fff || current_raw==16'sh8000);
    wire pressure_event=PRESSURE_INDEPENDENT ? pressure_new:adc_new;
    wire pressure_rail=pressure_event && (pressure_raw==16'sh7fff || pressure_raw==16'sh8000);
    wire adc_rail=current_rail || (!PRESSURE_INDEPENDENT && pressure_rail);
    wire pressure_fault=(PRESSURE_INDEPENDENT ? pressure_bad:adc_bad) || pressure_rail
        || (!PRESSURE_INDEPENDENT && current_rail);
    wire valid_adc=adc_new && !adc_bad && !adc_rail;
    wire valid_pressure=pressure_event && !pressure_fault;
    wire [31:0] latest_pressure_age=valid_pressure ? 0:
        (pressure_seen ? now_ms-last_pressure_ms:32'hffffffff);
    wire valid_fg=fg_new && !fg_bad && fg_period!=0;
    wire mode_bad=control_mode!=3 || (mode_seen && control_mode!=last_mode);
    // Synchronous RAM ports have no reset and no A/B mux on their outputs.
    // This is the same block-RAM inference template as feature_fft_ram.
    always @(posedge clk)begin
        if(a_new && rst_n)ring_a[wa]<={az,ay,ax};
        if(busy && feed_state==0 && !sample_valid)read_a<=ring_a[read_a_address];
    end
    always @(posedge clk)begin
        if(b_new && rst_n)ring_b[wb]<={bz,by,bx};
        if(busy && feed_state==0 && !sample_valid)read_b<=ring_b[read_b_address];
    end
    wire [47:0] read_word=axis<3 ? read_a:read_b;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            wa<=0;wb<=0;base_a<=0;base_b<=0;index<=0;axis<=0;warm_a<=0;warm_b<=0;
            pa<=0;pb<=0;prev_a<=0;prev_b<=0;last_a<=0;last_b<=0;first_a<=0;first_b<=0;
            previous_first_a<=0;previous_first_b<=0;boundary_a<=0;boundary_b<=0;start_a<=0;start_b<=0;
            tail_a<=0;tail_b<=0;last_seq_a<=0;last_seq_b<=0;
            hop_quality_a<=0;hop_quality_b<=0;previous_quality_a<=0;previous_quality_b<=0;qa<=0;qb<=0;
            feed_state<=0;frame_start<=0;frame_abort<=0;sample_valid<=0;sample_data<=0;
            busy<=0;frame_id<=0;drop_count<=0;window_start<=0;window_end<=0;end_ms<=0;
            span_a<=0;span_b<=0;align_cycles<=0;adc_count<=0;fg_count<=0;temp_age_ms<=0;
            pressure_count<=0;pressure_age_ms<=32'hffffffff;
            current_sum<=0;pressure_sum<=0;period_sum<=0;temperature<=0;quality<=0;sequences<=0;
            sum_i<=0;sum_p<=0;prev_i<=0;prev_p<=0;bound_i<=0;bound_p<=0;
            count_adc<=0;prev_adc<=0;bound_adc<=0;sum_fg<=0;prev_fg<=0;bound_fg<=0;
            count_pressure<=0;prev_pressure<=0;bound_pressure<=0;last_pressure_ms<=0;bound_pressure_age<=32'hffffffff;
            pressure_seen<=0;pressure_hop_bad<=0;pressure_prev_bad<=0;pressure_bound_bad<=0;
            count_fg<=0;prev_count_fg<=0;bound_count_fg<=0;adc_seen<=0;temp_seen<=0;fg_seen<=0;
            adc_hop_bad<=0;adc_prev_bad<=0;adc_bound_bad<=0;temp_stamp<=0;temp_ms<=0;next_frame_id<=0;
            mode_hop_bad<=0;mode_prev_bad<=0;mode_seen<=0;last_mode<=0;
            fg_hop_bad<=0;fg_prev_bad<=0;fg_bound_bad<=0;
        end else begin
            frame_start<=0;frame_abort<=0;
            if(temp_new && !temp_bad)begin temp_seen<=1;temp_stamp<=now_cycles;temp_ms<=now_ms;end
            if(adc_bad || adc_rail)adc_hop_bad<=1;
            if(pressure_fault)pressure_hop_bad<=1;
            last_mode<=control_mode;mode_seen<=1;
            if(mode_bad)mode_hop_bad<=1;
            if(fg_bad || (fg_new && fg_period==0))fg_hop_bad<=1;
            if(valid_adc) begin
                adc_seen<=1;
                sum_i<=sum_i+current_raw;count_adc<=count_adc+1;
            end
            if(valid_pressure)begin
                pressure_seen<=1;last_pressure_ms<=now_ms;
                sum_p<=sum_p+pressure_raw;count_pressure<=count_pressure+1;
            end
            if(valid_fg)begin
                fg_seen<=1;sum_fg<=sum_fg+fg_period;count_fg<=count_fg+1;
            end
            if(a_new)begin
                wa<=wa+1;
                if(warm_a<1024)warm_a<=warm_a+1;
                prev_a<=1;last_a<=now_cycles;last_seq_a<=a_seq;
                if(wa[8:0]==0)first_a<=now_cycles;
                if(gap_a || a_bad)hop_quality_a[4]<=1;
                if(rail_a)hop_quality_a[2]<=1;
                if(wa[8:0]==511)begin
                    boundary_a<=now_cycles;start_a<=previous_first_a;tail_a<=wa+1;pa<=1;
                    qa<=previous_quality_a | hop_quality_a | (gap_a || a_bad ? 16'h10:0) | (rail_a ? 16'h4:0)
                        | ((mode_prev_bad || mode_hop_bad || mode_bad)?16'h2000:0);
                    mode_prev_bad<=mode_hop_bad || mode_bad;mode_hop_bad<=0;
                    previous_first_a<=first_a;previous_quality_a<=hop_quality_a | (gap_a || a_bad ? 16'h10:0) | (rail_a ? 16'h4:0);hop_quality_a<=0;
                    bound_i<=prev_i+sum_i+(valid_adc ? current_raw:16'sd0);
                    bound_p<=prev_p+sum_p+(valid_pressure ? pressure_raw:16'sd0);
                    bound_adc<=prev_adc+count_adc+(valid_adc ? 1:0);
                    bound_pressure<=prev_pressure+count_pressure+(valid_pressure ? 1:0);
                    bound_pressure_age<=latest_pressure_age;
                    pressure_bound_bad<=pressure_prev_bad || pressure_hop_bad || pressure_fault
                        || latest_pressure_age>=PRESSURE_MAX_MS;
                    bound_fg<=prev_fg+sum_fg+(valid_fg ? fg_period:32'd0);
                    bound_count_fg<=prev_count_fg+count_fg+(valid_fg ? 1:0);
                    fg_bound_bad<=fg_prev_bad || fg_hop_bad || fg_bad || (fg_new && fg_period==0);
                    fg_prev_bad<=fg_hop_bad || fg_bad || (fg_new && fg_period==0);fg_hop_bad<=0;
                    adc_bound_bad<=adc_prev_bad || adc_hop_bad || adc_bad || adc_rail;
                    prev_i<=sum_i+(valid_adc ? current_raw:16'sd0);prev_p<=sum_p+(valid_pressure ? pressure_raw:16'sd0);
                    prev_adc<=count_adc+(valid_adc ? 1:0);sum_i<=0;sum_p<=0;count_adc<=0;
                    prev_pressure<=count_pressure+(valid_pressure ? 1:0);count_pressure<=0;
                    pressure_prev_bad<=pressure_hop_bad || pressure_fault;pressure_hop_bad<=0;
                    prev_fg<=sum_fg+(valid_fg ? fg_period:32'd0);
                    prev_count_fg<=count_fg+(valid_fg ? 1:0);sum_fg<=0;count_fg<=0;
                    adc_prev_bad<=adc_hop_bad || adc_bad || adc_rail;adc_hop_bad<=0;
                end
                // Exclude pre-acquisition process samples from the first hop.
                if(!prev_a)begin
                    sum_i<=0;sum_p<=0;count_adc<=0;count_pressure<=0;
                    sum_fg<=0;count_fg<=0;adc_hop_bad<=0;pressure_hop_bad<=0;
                end
            end
            if(b_new)begin
                wb<=wb+1;
                if(warm_b<1024)warm_b<=warm_b+1;
                prev_b<=1;last_b<=now_cycles;last_seq_b<=b_seq;
                if(wb[8:0]==0)first_b<=now_cycles;
                if(gap_b || b_bad)hop_quality_b[5]<=1;
                if(rail_b)hop_quality_b[2]<=1;
                if(wb[8:0]==511)begin
                    boundary_b<=now_cycles;start_b<=previous_first_b;tail_b<=wb+1;pb<=1;
                    qb<=previous_quality_b | hop_quality_b | (gap_b || b_bad ? 16'h20:0) | (rail_b ? 16'h4:0);
                    previous_first_b<=first_b;previous_quality_b<=hop_quality_b | (gap_b || b_bad ? 16'h20:0) | (rail_b ? 16'h4:0);hop_quality_b<=0;
                end
            end
            if(pa && pb)begin
                if(delta>ALIGN_CYCLES)begin
                    // Discard only the older boundary; never pair half windows
                    // separated by an entire hop after a sensor outage.
                    if(boundary_a<boundary_b)pa<=0;else pb<=0;
                    drop_count<=drop_count+1;
                end else begin
                    pa<=0;pb<=0;
                    if(warm_a>=1024 && warm_b>=1024)begin
                        next_frame_id<=next_frame_id+1;
                        if(!busy && feature_ready && enable)begin
                            frame_id<=next_frame_id+1;base_a<=tail_a-11'd1024;base_b<=tail_b-11'd1024;
                            window_start<=start_a<start_b ? start_a:start_b;
                            window_end<=boundary_a>boundary_b ? boundary_a:boundary_b;
                            end_ms<=now_ms;span_a<=boundary_a-start_a;span_b<=boundary_b-start_b;
                            align_cycles<=delta;adc_count<=bound_adc;fg_count<=bound_count_fg;
                            pressure_count<=bound_pressure;pressure_age_ms<=bound_pressure_age;
                            current_sum<=bound_i;pressure_sum<=bound_p;period_sum<=bound_fg;
                            temperature<=temp_raw;temp_age_ms<=temp_seen ? now_ms-temp_ms:32'hffffffff;
                            quality<=qa | qb | ((adc_bound_bad || !adc_seen || bound_adc==0)?16'h100:0)
                                | ((pressure_bound_bad || !pressure_seen || bound_pressure==0)?16'h400:0)
                                | ((PRESSURE_INDEPENDENT && (bound_adc>65535 || bound_pressure>65535))?16'h8:0)
                                | ((temp_bad || !temp_seen || now_cycles-temp_stamp>TEMP_MAX_CYCLES)?16'h200:0)
                                | ((fg_bound_bad || fg_bad || !fg_seen || bound_count_fg==0)?16'h800:0)
                                | (a_bad?16'h10:0) | (b_bad?16'h20:0)
                                | (rate_a_bad?16'h40:0) | (rate_b_bad?16'h80:0);
                            sequences<={last_seq_b,last_seq_a};
                            frame_start<=1;busy<=1;axis<=0;index<=0;feed_state<=0;sample_valid<=0;
                        end else drop_count<=drop_count+1;
                    end
                end
            end
            if(busy)begin
                if(feed_state==0 && !sample_valid)begin
                    feed_state<=1;
                end else if(feed_state==1)begin
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
                        else begin axis<=axis+1;feed_state<=0;end
                    end else begin index<=index+1;feed_state<=0;end
                end
                if(feature_done)begin busy<=0;sample_valid<=0;feed_state<=0;end
            end
            if(overwriting)begin
                busy<=0;frame_abort<=1;sample_valid<=0;drop_count<=drop_count+1;feed_state<=0;
            end
        end
    end
endmodule
