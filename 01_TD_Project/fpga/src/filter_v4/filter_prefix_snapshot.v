`timescale 1ns/1ps
module filter_prefix_snapshot #(
    parameter integer SLOT_BITS=2,parameter integer SYNC_LOOKUP=0
) (
    input wire clk,rst_n,
    input wire tick_valid,input wire [63:0] obs_ts,
    input wire [31:0] config_id,
    input wire [3:0] observation_mode,
    input wire current_event,pressure_event,fg_event,temp_event,
    input wire signed [15:0] current_value,pressure_value,temperature,
    input wire [31:0] fg_period,input wire [7:0] bad_quality,
    input wire invalidate,input wire [7:0] invalidate_quality,
    input wire capture,input wire [63:0] capture_token,
    input wire release_snapshot,input wire [63:0] release_token,
    input wire lookup,input wire [63:0] lookup_token,
    output wire lookup_found,output wire [1343:0] lookup_record,
    output reg capture_event,capture_ok,fault_event,
    output reg [7:0] fault_quality,
    output reg [31:0] stream_epoch
);
    localparam integer SLOTS=1<<SLOT_BITS;
    generate
        if (SLOT_BITS<1 || SLOT_BITS>4) begin : invalid_capacity
            filter_v4_snapshot_slot_bits_must_be_1_to_4 invalid_parameter();
        end
    endgenerate
    reg [SLOTS-1:0] occupied;
    reg [63:0] tokens [0:SLOTS-1];
    reg signed [63:0] current_sum,pressure_sum;
    reg [63:0] current_count,pressure_count,period_sum,period_count;
    reg [63:0] last_ts,temp_ts,current_ts,pressure_ts,fg_ts;
    reg signed [15:0] latest_temperature;
    reg [3:0] seen;
    reg have_timestamp;
    reg [31:0] active_config;
    reg config_initialized;
    reg [511:0] bad_counts;
    wire [SLOT_BITS-1:0] capture_index=capture_token[SLOT_BITS-1:0];
    wire [SLOT_BITS-1:0] release_index=release_token[SLOT_BITS-1:0];
    wire [SLOT_BITS-1:0] lookup_index=lookup_token[SLOT_BITS-1:0];
    wire release_found=occupied[release_index] && tokens[release_index]==release_token;
    wire signed [64:0] added_current={current_sum[63],current_sum}
        + (current_event ? {{49{current_value[15]}},current_value} : 65'sd0);
    wire signed [64:0] added_pressure={pressure_sum[63],pressure_sum}
        + (pressure_event ? {{49{pressure_value[15]}},pressure_value} : 65'sd0);
    wire [64:0] added_period={1'b0,period_sum}+(fg_event ? {33'd0,fg_period} : 65'd0);
    wire [63:0] next_current_count=current_count+(current_event ? 64'd1 : 64'd0);
    wire [63:0] next_pressure_count=pressure_count+(pressure_event ? 64'd1 : 64'd0);
    wire [63:0] next_period_count=period_count+(fg_event ? 64'd1 : 64'd0);
    reg bad_counter_overflow;
    integer bad_index;
    always @* begin
        bad_counter_overflow=0;
        for (bad_index=0;bad_index<8;bad_index=bad_index+1)
            if (bad_quality[bad_index] && bad_counts[bad_index*64+:64]==64'hffffffffffffffff)
                bad_counter_overflow=1;
    end
    wire overflow=added_current[64]!=added_current[63] || added_pressure[64]!=added_pressure[63]
        || added_period[64] || (current_event && current_count==64'hffffffffffffffff)
        || (pressure_event && pressure_count==64'hffffffffffffffff)
        || (fg_event && period_count==64'hffffffffffffffff) || bad_counter_overflow;
    wire capture_collision=capture && occupied[capture_index]
        && !(release_snapshot && release_found && release_index==capture_index);
    wire protocol_fault=(capture && !tick_valid) || (release_snapshot && !release_found)
        || (tick_valid && have_timestamp && obs_ts<=last_ts)
        || (tick_valid && fg_event && fg_period==0);
    wire [31:0] effective_config=config_initialized ? active_config : config_id;
    wire configuration_fault=config_initialized && config_id!=active_config;
    wire fatal_fault=capture_collision || protocol_fault || configuration_fault || (tick_valid && overflow);
    reg [1343:0] next_record;
    integer record_index;
    always @* begin
        next_record=0;
        next_record[0+:32]=stream_epoch;
        next_record[32+:32]=effective_config;
        next_record[64+:64]=obs_ts;
        next_record[128+:64]=added_current[63:0];
        next_record[192+:64]=next_current_count;
        next_record[256+:64]=added_pressure[63:0];
        next_record[320+:64]=next_pressure_count;
        next_record[384+:64]=added_period[63:0];
        next_record[448+:64]=next_period_count;
        next_record[512+:32]=temp_event ? {{16{temperature[15]}},temperature} : {{16{latest_temperature[15]}},latest_temperature};
        next_record[544+:64]=temp_event ? obs_ts : temp_ts;
        next_record[608+:64]=current_event ? obs_ts : current_ts;
        next_record[672+:64]=pressure_event ? obs_ts : pressure_ts;
        next_record[736+:64]=fg_event ? obs_ts : fg_ts;
        next_record[800+:32]={24'd0,observation_mode,(seen | {temp_event,fg_event,pressure_event,current_event})};
        for (record_index=0;record_index<8;record_index=record_index+1)
            next_record[832+record_index*64+:64]=bad_counts[record_index*64+:64]+(bad_quality[record_index] ? 64'd1 : 64'd0);
    end
    wire record_write=rst_n && !invalidate && !fatal_fault && capture;
    generate
        if(SYNC_LOOKUP!=0)begin:synchronous_records
            (* ram_style="bram" *) reg [1343:0] records[0:SLOTS-1];
            reg [1343:0] read_data;
            reg lookup_held;
            reg [63:0] token_held;
            reg forward_write;
            reg [3:0] committed_mode;
            reg [1343:0] committed_record;
            integer quality_index;
            wire [SLOT_BITS-1:0] held_index=token_held[SLOT_BITS-1:0];
            always @(posedge clk)begin
                read_data<=records[lookup_index];
            end
            always @(posedge clk or negedge rst_n)begin
                if(!rst_n)begin end
                else if(record_write)records[capture_index]<=next_record;
            end
            always @(posedge clk or negedge rst_n)begin
                if(!rst_n)begin lookup_held<=0;token_held<=0;forward_write<=0;committed_mode<=0;end
                else begin
                    lookup_held<=lookup;token_held<=lookup_token;
                    forward_write<=record_write && lookup && capture_index==lookup_index;
                    if(record_write)committed_mode<=observation_mode;
                end
            end
            always @* begin
                committed_record=0;
                committed_record[0+:32]=stream_epoch;
                committed_record[32+:32]=active_config;
                committed_record[64+:64]=last_ts;
                committed_record[128+:64]=current_sum;
                committed_record[192+:64]=current_count;
                committed_record[256+:64]=pressure_sum;
                committed_record[320+:64]=pressure_count;
                committed_record[384+:64]=period_sum;
                committed_record[448+:64]=period_count;
                committed_record[512+:32]={{16{latest_temperature[15]}},latest_temperature};
                committed_record[544+:64]=temp_ts;
                committed_record[608+:64]=current_ts;
                committed_record[672+:64]=pressure_ts;
                committed_record[736+:64]=fg_ts;
                committed_record[800+:32]={24'd0,committed_mode,seen};
                for(quality_index=0;quality_index<8;quality_index=quality_index+1)
                    committed_record[832+quality_index*64+:64]=bad_counts[quality_index*64+:64];
            end
            assign lookup_found=lookup_held && occupied[held_index] && tokens[held_index]==token_held;
            assign lookup_record=lookup_found ? (forward_write ? committed_record : read_data) : 1344'd0;
        end else begin:asynchronous_records
            reg [1343:0] records[0:SLOTS-1];
            always @(posedge clk or negedge rst_n)begin
                if(!rst_n)begin end
                else if(record_write)records[capture_index]<=next_record;
            end
            assign lookup_found=lookup && occupied[lookup_index] && tokens[lookup_index]==lookup_token;
            assign lookup_record=lookup_found ? records[lookup_index] : 1344'd0;
        end
    endgenerate
    integer state_index;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            occupied<=0;stream_epoch<=0;active_config<=0;config_initialized<=0;
            current_sum<=0;pressure_sum<=0;current_count<=0;pressure_count<=0;period_sum<=0;period_count<=0;
            last_ts<=0;temp_ts<=0;current_ts<=0;pressure_ts<=0;fg_ts<=0;latest_temperature<=0;
            seen<=0;have_timestamp<=0;capture_event<=0;capture_ok<=0;fault_event<=0;fault_quality<=0;
            bad_counts<=0;
        end else begin
            capture_event<=0;capture_ok<=0;fault_event<=0;
            if (!config_initialized)begin active_config<=config_id;config_initialized<=1;end
            if (invalidate || fatal_fault) begin
                occupied<=0;stream_epoch<=stream_epoch+32'd1;
                if (invalidate)active_config<=config_id;
                current_sum<=0;pressure_sum<=0;current_count<=0;pressure_count<=0;period_sum<=0;period_count<=0;
                last_ts<=0;temp_ts<=0;current_ts<=0;pressure_ts<=0;fg_ts<=0;latest_temperature<=0;
                seen<=0;have_timestamp<=0;
                bad_counts<=0;
                capture_event<=capture;fault_event<=1;
                fault_quality<=(invalidate ? (invalidate_quality==0 ? 8'h02 : invalidate_quality)
                    : configuration_fault ? 8'h80 : capture_collision ? 8'h40 : 8'h02) | 8'h01;
            end else begin
                if (tick_valid) begin
                    last_ts<=obs_ts;have_timestamp<=1;
                    current_sum<=added_current[63:0];pressure_sum<=added_pressure[63:0];
                    current_count<=next_current_count;pressure_count<=next_pressure_count;
                    period_sum<=added_period[63:0];period_count<=next_period_count;
                    if (current_event)current_ts<=obs_ts;
                    if (pressure_event)pressure_ts<=obs_ts;
                    if (fg_event)fg_ts<=obs_ts;
                    if (temp_event)begin temp_ts<=obs_ts;latest_temperature<=temperature;end
                    seen<=seen | {temp_event,fg_event,pressure_event,current_event};
                    for (state_index=0;state_index<8;state_index=state_index+1)
                        bad_counts[state_index*64+:64]<=bad_counts[state_index*64+:64]+(bad_quality[state_index] ? 64'd1 : 64'd0);
                end
                if (release_snapshot)occupied[release_index]<=0;
                if (capture) begin
                    occupied[capture_index]<=1;tokens[capture_index]<=capture_token;
                    capture_event<=1;capture_ok<=1;
                end
            end
        end
    end
endmodule
