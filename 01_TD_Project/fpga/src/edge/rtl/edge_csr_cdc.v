`timescale 1ns/1ps
// One outstanding CSR, four-phase bundled-data handshake. Each domain may reset
// independently. Source reset abandons (but does not undo) an issued operation;
// the destination drains its old response before accepting a new source request.
// Destination reset returns error FF for an issued request, never auto-replays it.
// Command IDs/readback are still required to resolve ambiguous completed writes.
module edge_csr_cdc(
    input wire s_clk,s_rst_n,input wire s_req,s_write,
    input wire [15:0] s_address,input wire [31:0] s_wdata,
    output reg s_response,output reg [31:0] s_rdata,output reg [7:0] s_error,
    input wire d_clk,d_rst_n,output reg d_req,output reg d_write,
    output reg [15:0] d_address,output reg [31:0] d_wdata,
    input wire d_response,input wire [31:0] d_rdata,input wire [7:0] d_error
);
    localparam S_IDLE=0,S_PENDING=1,S_ACK=2,S_CLEAR=3;
    reg [1:0] source_state;
    reg request_level,ack_level,destination_busy,orphan;
    reg [48:0] request_payload;
    reg [39:0] response_payload;
    (* ASYNC_REG="TRUE" *) reg ack_meta,ack_sync,req_meta,req_sync;
    (* ASYNC_REG="TRUE" *) reg [1:0] source_online,destination_online;
    wire link_reset_n=s_rst_n && d_rst_n;
    // An asynchronous assertion records even a short peer-reset pulse. Each
    // online indication releases only after two clocks in its local domain.
    always @(posedge s_clk or negedge link_reset_n)
        if(!link_reset_n)destination_online<=0;
        else destination_online<={destination_online[0],1'b1};
    always @(posedge d_clk or negedge link_reset_n)
        if(!link_reset_n)begin source_online<=0;req_meta<=0;req_sync<=0;end
        else begin
            source_online<={source_online[0],1'b1};
            req_meta<=request_level;req_sync<=req_meta;
        end
    always @(posedge s_clk or negedge s_rst_n) begin
        if(!s_rst_n)begin
            request_level<=0;source_state<=S_IDLE;request_payload<=0;
            ack_meta<=0;ack_sync<=0;s_response<=0;s_rdata<=0;s_error<=0;
        end else begin
            ack_meta<=ack_level;ack_sync<=ack_meta;s_response<=0;
            if(!destination_online[1] && (source_state==S_ACK || source_state==S_CLEAR))begin
                request_level<=0;source_state<=S_IDLE;
                s_rdata<=0;s_error<=8'hff;s_response<=1;
            end else case(source_state)
                S_IDLE:if(s_req)begin
                    request_payload<={s_write,s_address,s_wdata};source_state<=S_PENDING;
                end
                // Queue a request through startup/old-ACK cleanup; a single
                // s_req pulse must not be lost just because ack is still high.
                S_PENDING:if(destination_online[1] && !ack_sync)begin
                    request_level<=1;source_state<=S_ACK;
                end
                S_ACK:if(ack_sync)begin
                    {s_error,s_rdata}<=response_payload;
                    request_level<=0;source_state<=S_CLEAR;
                end
                S_CLEAR:if(!ack_sync)begin source_state<=S_IDLE;s_response<=1;end
                default:begin source_state<=S_IDLE;request_level<=0;end
            endcase
        end
    end
    always @(posedge d_clk or negedge d_rst_n) begin
        if(!d_rst_n)begin
            ack_level<=0;destination_busy<=0;orphan<=0;response_payload<=0;
            d_req<=0;d_write<=0;d_address<=0;d_wdata<=0;
        end else begin
            d_req<=0;
            if(!source_online[1])begin
                ack_level<=0;
                if(destination_busy)orphan<=1;
            end
            if(source_online[1] && req_sync && !ack_level && !destination_busy && !orphan)begin
                {d_write,d_address,d_wdata}<=request_payload;
                d_req<=1;destination_busy<=1;
            end
            if(destination_busy && d_response)begin
                destination_busy<=0;orphan<=0;
                if(source_online[1] && !orphan)begin
                    response_payload<={d_error,d_rdata};ack_level<=1;
                end else ack_level<=0; // drain the abandoned transaction
            end
            if(ack_level && !req_sync)ack_level<=0;
        end
    end
endmodule
