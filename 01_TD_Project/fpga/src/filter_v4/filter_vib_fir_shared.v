`timescale 1ns/1ps
module filter_vib_fir_shared #(
    parameter integer PROFILE = 0
) (
    input wire clk, rst_n,
    input wire a_event, b_event,
    input wire [47:0] a_xyz, b_xyz,
    input wire a_raw_err, b_raw_err,
    input wire [15:0] a_seq, b_seq,
    input wire [63:0] a_obs_ts, b_obs_ts, a_token, b_token,
    input wire a_invalidate, b_invalidate,
    input wire [7:0] a_invalidate_quality, b_invalidate_quality,
    output wire a_out_event, b_out_event, a_out_has_sample, b_out_has_sample,
    output wire a_out_valid, b_out_valid, a_out_warm, b_out_warm,
    output wire [47:0] a_out_xyz, b_out_xyz,
    output wire [7:0] a_out_quality, b_out_quality,
    output wire [15:0] a_out_seq, b_out_seq,
    output wire [63:0] a_out_obs_ts, b_out_obs_ts, a_out_token, b_out_token,
    output wire [31:0] a_out_epoch, b_out_epoch,
    output reg busy
);
    localparam integer COEFF_BITS = 18;
    localparam integer FRAC_BITS = PROFILE == 0 ? 17 : 15;
    generate
        if (PROFILE != 0 && PROFILE != 1) begin : invalid_profile
            filter_v4_fir_profile_must_be_0_or_1 invalid_parameter();
        end
    endgenerate

    function signed [COEFF_BITS-1:0] coefficient;
        input [3:0] address;
        begin
            if (PROFILE == 0) begin
                case (address)
                    0: coefficient=0; 1: coefficient=-10; 2: coefficient=-24; 3: coefficient=133;
                    4: coefficient=46; 5: coefficient=-542; 6: coefficient=146; 7: coefficient=1436;
                    8: coefficient=-1066; 9: coefficient=-2868; 10: coefficient=3717; 11: coefficient=4575;
                    12: coefficient=-10523; 13: coefficient=-5997; 14: coefficient=40471; default: coefficient=72084;
                endcase
            end else begin
                case (address)
                    0: coefficient=0; 1: coefficient=3; 2: coefficient=-8; 3: coefficient=-21;
                    4: coefficient=70; 5: coefficient=0; 6: coefficient=-221; 7: coefficient=222;
                    8: coefficient=345; 9: coefficient=-843; 10: coefficient=0; 11: coefficient=1851;
                    12: coefficient=-1736; 13: coefficient=-2852; 14: coefficient=9743; default: coefficient=19662;
                endcase
            end
        end
    endfunction

    function [4:0] history_address;
        input [4:0] head, lag;
        begin
            history_address = head >= lag ? head-lag : head+5'd31-lag;
        end
    endfunction

    wire input_event [0:1];
    wire [47:0] input_xyz [0:1];
    wire invalidation [0:1];
    wire [7:0] invalidation_quality [0:1];
    wire [15:0] sequence_id [0:1];
    wire [63:0] observation [0:1], token [0:1];
    assign input_event[0]=a_event; assign input_event[1]=b_event;
    assign input_xyz[0]=a_xyz; assign input_xyz[1]=b_xyz;
    assign invalidation[0]=a_invalidate; assign invalidation[1]=b_invalidate;
    assign invalidation_quality[0]=a_invalidate_quality; assign invalidation_quality[1]=b_invalidate_quality;
    assign sequence_id[0]=a_seq; assign sequence_id[1]=b_seq;
    assign observation[0]=a_obs_ts; assign observation[1]=b_obs_ts;
    assign token[0]=a_token; assign token[1]=b_token;
    reg [47:0] history_a [0:31],history_b [0:31];
    reg [4:0] write_index [0:1];
    reg [5:0] warm_count [0:1];
    reg have_last [0:1], pending [0:1];
    reg [15:0] last_seq [0:1], job_seq [0:1];
    reg [63:0] last_ts [0:1], job_ts [0:1], job_token [0:1];
    reg [31:0] epoch [0:1];
    reg [4:0] job_head [0:1];
    wire [63:0] interval_a=a_obs_ts-last_ts[0], interval_b=b_obs_ts-last_ts[1];
    wire [7:0] source_quality [0:1];
    wire rail_a=a_xyz[15:0]==16'h7fff || a_xyz[15:0]==16'h8000
        || a_xyz[31:16]==16'h7fff || a_xyz[31:16]==16'h8000
        || a_xyz[47:32]==16'h7fff || a_xyz[47:32]==16'h8000;
    wire rail_b=b_xyz[15:0]==16'h7fff || b_xyz[15:0]==16'h8000
        || b_xyz[31:16]==16'h7fff || b_xyz[31:16]==16'h8000
        || b_xyz[47:32]==16'h7fff || b_xyz[47:32]==16'h8000;
    assign source_quality[0]={3'd0,
        have_last[0] && (interval_a<64'd6250 || interval_a>64'd43750),
        have_last[0] && a_seq!=last_seq[0]+16'd1, rail_a, a_raw_err, 1'b0};
    assign source_quality[1]={3'd0,
        have_last[1] && (interval_b<64'd6250 || interval_b>64'd43750),
        have_last[1] && b_seq!=last_seq[1]+16'd1, rail_b, b_raw_err, 1'b0};
    reg event_out [0:1], has_sample_out [0:1], valid_out [0:1], warm_out [0:1];
    reg [47:0] xyz_out [0:1];
    reg [7:0] quality_out [0:1];
    reg [15:0] seq_out [0:1];
    reg [63:0] ts_out [0:1], token_out [0:1];
    reg [31:0] epoch_out [0:1];
    assign a_out_event=event_out[0]; assign b_out_event=event_out[1];
    assign a_out_has_sample=has_sample_out[0]; assign b_out_has_sample=has_sample_out[1];
    assign a_out_valid=valid_out[0]; assign b_out_valid=valid_out[1];
    assign a_out_warm=warm_out[0]; assign b_out_warm=warm_out[1];
    assign a_out_xyz=xyz_out[0]; assign b_out_xyz=xyz_out[1];
    assign a_out_quality=quality_out[0]; assign b_out_quality=quality_out[1];
    assign a_out_seq=seq_out[0]; assign b_out_seq=seq_out[1];
    assign a_out_obs_ts=ts_out[0]; assign b_out_obs_ts=ts_out[1];
    assign a_out_token=token_out[0]; assign b_out_token=token_out[1];
    assign a_out_epoch=epoch_out[0]; assign b_out_epoch=epoch_out[1];
    reg active_point, last_point;
    reg [1:0] active_axis;
    reg [4:0] issued;
    reg product_valid, product_last;
    reg signed [COEFF_BITS+16:0] product;
    reg signed [39:0] accumulator;
    reg [31:0] result_xyz;
    reg result_saturated;
    wire eligible_a=pending[0] && !a_event && !a_invalidate;
    wire eligible_b=pending[1] && !b_event && !b_invalidate;
    wire selected_point=eligible_a && eligible_b ? !last_point : eligible_b;
    wire [4:0] tap=issued[3:0]==4'd15 ? 5'd15 : issued;
    wire [4:0] left_address=history_address(job_head[active_point],tap);
    wire [4:0] right_address=history_address(job_head[active_point],5'd30-tap);
    wire [47:0] left_xyz=active_point ? history_b[left_address] : history_a[left_address];
    wire [47:0] right_xyz=active_point ? history_b[right_address] : history_a[right_address];
    wire signed [15:0] left_sample=active_axis==0 ? left_xyz[15:0]
        : active_axis==1 ? left_xyz[31:16] : left_xyz[47:32];
    wire signed [15:0] right_sample=issued==5'd15 ? 16'sd0
        : active_axis==0 ? right_xyz[15:0]
        : active_axis==1 ? right_xyz[31:16] : right_xyz[47:32];
    wire signed [16:0] preadd={left_sample[15],left_sample}+{right_sample[15],right_sample};
    wire signed [39:0] extended_product={{(23-COEFF_BITS){product[COEFF_BITS+16]}},product};
    wire signed [39:0] final_accumulator=accumulator+extended_product;
    wire signed [40:0] rounding_input={final_accumulator[39],final_accumulator};
    wire signed [40:0] rounding_bias=41'sd1 << (FRAC_BITS-1);
    wire signed [40:0] rounded=rounding_input[40]
        ? -(((-rounding_input)+rounding_bias) >>> FRAC_BITS)
        : (rounding_input+rounding_bias) >>> FRAC_BITS;
    wire saturated=rounded>41'sd32767 || rounded < -41'sd32768;
    wire signed [15:0] clipped=rounded>41'sd32767 ? 16'sh7fff
        : rounded < -41'sd32768 ? 16'sh8000 : rounded[15:0];
    wire write_a=a_event && !a_invalidate && source_quality[0]==0 && !pending[0] && !(busy && !active_point);
    wire write_b=b_event && !b_invalidate && source_quality[1]==0 && !pending[1] && !(busy && active_point);
    always @(posedge clk) begin
        if (write_a)history_a[write_index[0]]<=a_xyz;
        if (write_b)history_b[write_index[1]]<=b_xyz;
    end
    integer point_index;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy<=0;active_point<=0;last_point<=1;active_axis<=0;issued<=0;
            product_valid<=0;product_last<=0;product<=0;accumulator<=0;result_xyz<=0;result_saturated<=0;
            for (point_index=0;point_index<2;point_index=point_index+1) begin
                write_index[point_index]<=0;warm_count[point_index]<=0;have_last[point_index]<=0;
                pending[point_index]<=0;last_seq[point_index]<=0;last_ts[point_index]<=0;
                job_seq[point_index]<=0;job_ts[point_index]<=0;job_token[point_index]<=0;job_head[point_index]<=0;
                epoch[point_index]<=0;event_out[point_index]<=0;has_sample_out[point_index]<=0;
                valid_out[point_index]<=0;warm_out[point_index]<=0;xyz_out[point_index]<=0;
                quality_out[point_index]<=8'h01;seq_out[point_index]<=0;ts_out[point_index]<=0;
                token_out[point_index]<=0;epoch_out[point_index]<=0;
            end
        end else begin
            for (point_index=0;point_index<2;point_index=point_index+1) begin
                event_out[point_index]<=0;valid_out[point_index]<=0;
            end
            if (!busy) begin
                product_valid<=0;
                if (eligible_a || eligible_b) begin
                    busy<=1;active_point<=selected_point;last_point<=selected_point;
                    pending[selected_point]<=0;active_axis<=0;issued<=0;
                    accumulator<=0;result_xyz<=0;result_saturated<=0;
                end
            end else begin
                product_valid<=issued<5'd16;
                if (issued<5'd16) begin
                    product<=preadd*coefficient(issued[3:0]);
                    product_last<=issued==5'd15;
                    issued<=issued+5'd1;
                end
                if (product_valid) begin
                    accumulator<=final_accumulator;
                    if (product_last) begin
                        if (active_axis==0)result_xyz[15:0]<=clipped;
                        else if (active_axis==1)result_xyz[31:16]<=clipped;
                        result_saturated<=result_saturated || saturated;
                        accumulator<=0;product_valid<=0;issued<=0;
                        if (active_axis==2) begin
                            busy<=0;event_out[active_point]<=1;has_sample_out[active_point]<=1;
                            warm_out[active_point]<=1;valid_out[active_point]<=!(result_saturated || saturated);
                            quality_out[active_point]<=(result_saturated || saturated) ? 8'h20 : 8'h00;
                            xyz_out[active_point]<={clipped,result_xyz[31:0]};
                            seq_out[active_point]<=job_seq[active_point];ts_out[active_point]<=job_ts[active_point];
                            token_out[active_point]<=job_token[active_point];epoch_out[active_point]<=epoch[active_point];
                        end else active_axis<=active_axis+2'd1;
                    end
                end
            end
            for (point_index=0;point_index<2;point_index=point_index+1) begin
                if (invalidation[point_index]) begin
                    warm_count[point_index]<=0;write_index[point_index]<=0;have_last[point_index]<=0;
                    pending[point_index]<=0;epoch[point_index]<=epoch[point_index]+32'd1;
                    event_out[point_index]<=1;has_sample_out[point_index]<=0;valid_out[point_index]<=0;
                    warm_out[point_index]<=0;xyz_out[point_index]<=0;
                    quality_out[point_index]<=(invalidation_quality[point_index]==0 ? 8'h02 : invalidation_quality[point_index]) | 8'h01;
                    seq_out[point_index]<=0;ts_out[point_index]<=0;token_out[point_index]<=0;
                    epoch_out[point_index]<=epoch[point_index]+32'd1;
                    if (busy && active_point==point_index[0]) begin busy<=0;product_valid<=0;end
                end else if (input_event[point_index]) begin
                    last_seq[point_index]<=sequence_id[point_index];last_ts[point_index]<=observation[point_index];
                    have_last[point_index]<=1;
                    if (source_quality[point_index]!=0 || pending[point_index] || (busy && active_point==point_index[0])) begin
                        warm_count[point_index]<=0;write_index[point_index]<=0;pending[point_index]<=0;
                        epoch[point_index]<=epoch[point_index]+32'd1;
                        event_out[point_index]<=1;has_sample_out[point_index]<=1;valid_out[point_index]<=0;
                        warm_out[point_index]<=0;xyz_out[point_index]<=input_xyz[point_index];
                        quality_out[point_index]<=source_quality[point_index] | 8'h01
                            | ((pending[point_index] || (busy && active_point==point_index[0])) ? 8'h40 : 8'h00);
                        seq_out[point_index]<=sequence_id[point_index];ts_out[point_index]<=observation[point_index];
                        token_out[point_index]<=token[point_index];epoch_out[point_index]<=epoch[point_index]+32'd1;
                        if (busy && active_point==point_index[0]) begin busy<=0;product_valid<=0;end
                    end else begin
                        write_index[point_index]<=write_index[point_index]==5'd30 ? 5'd0 : write_index[point_index]+5'd1;
                        if (warm_count[point_index]<6'd31)warm_count[point_index]<=warm_count[point_index]+6'd1;
                        if (warm_count[point_index]<6'd30) begin
                            event_out[point_index]<=1;has_sample_out[point_index]<=1;valid_out[point_index]<=0;
                            warm_out[point_index]<=0;xyz_out[point_index]<=input_xyz[point_index];quality_out[point_index]<=8'h01;
                            seq_out[point_index]<=sequence_id[point_index];ts_out[point_index]<=observation[point_index];
                            token_out[point_index]<=token[point_index];epoch_out[point_index]<=epoch[point_index];
                        end else begin
                            pending[point_index]<=1;job_head[point_index]<=write_index[point_index];
                            job_seq[point_index]<=sequence_id[point_index];job_ts[point_index]<=observation[point_index];
                            job_token[point_index]<=token[point_index];
                        end
                    end
                end
            end
        end
    end
endmodule
