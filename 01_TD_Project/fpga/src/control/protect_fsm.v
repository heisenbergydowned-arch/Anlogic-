`timescale 1ns/1ps
// Cause recovery and drive latch release are independent. Only a local request
// can release a latch, with currently valid, stable recovery evidence.
module protect_fsm(
    input wire clk, rst_n,
    input wire [31:0] now_ms,
    input wire [767:0] cfg,
    input wire grace_done, desired_run, local_owner, degraded, feedback_valid,
    input wire stopping_confirmed, target_changed, tracking_ok,
    input wire [31:0] active,
    input wire local_reset, reset_safe,
    output reg [3:0] mode,
    output reg [31:0] latched,
    output reg reset_accepted, reset_rejected,
    output wire starting, stable_run
);
    // bits 0/3/4/7/8/9/11 latch: hard OC, thermal, lost current protection,
    // start failure, corroborated stall, overspeed, qualified mechanical rule.
    localparam [31:0] LATCH_MASK=32'h0000_0b99;
    reg [31:0] start_at, transient_at, safe_at;
    reg safe_pending, episode, transient_armed;
    wire [31:0] start_age=now_ms-start_at, transient_age=now_ms-transient_at, safe_age=now_ms-safe_at;
    wire [31:0] incoming=active & LATCH_MASK;
    assign starting=mode==2;
    assign stable_run=mode==3 && !degraded && latched==0;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            mode<=0;latched<=0;reset_accepted<=0;reset_rejected<=0;
            start_at<=0;transient_at<=0;safe_at<=0;safe_pending<=0;episode<=0;transient_armed<=0;
        end else begin
            reset_accepted<=0;reset_rejected<=0;
            if(!reset_safe) safe_pending<=0;
            else if(!safe_pending) begin safe_pending<=1;safe_at<=now_ms;end
            latched<=latched|incoming;
            if(local_reset) begin
                if(reset_safe && safe_pending && safe_age>=cfg[14*32+16 +:16] && incoming==0) begin
                    latched<=0;reset_accepted<=1;episode<=0;mode<=0;transient_armed<=0;
                end else reset_rejected<=1;
            end else if(latched!=0 || incoming!=0) mode<=7;
            else if(!grace_done) mode<=0;
            else if(!desired_run) begin
                transient_armed<=0;
                if(stopping_confirmed) begin mode<=1;episode<=0;end
                else mode<=5;
            end else if(!episode) begin
                episode<=1;start_at<=now_ms;mode<=2;
            end else if(mode==2) begin
                if(feedback_valid) begin mode<=local_owner ? 6:(degraded ? 8:3);transient_armed<=1;end
                else if(start_age>=cfg[15*32 +:16]) begin
                    latched<=latched|32'h80;mode<=7; // No automatic retries.
                end
            end else if(degraded) mode<=8;
            else if(local_owner) mode<=6;
            else if(target_changed && transient_armed) begin
                mode<=4;transient_at<=now_ms;transient_armed<=0;
            end else if(mode==4) begin
                // A repeated target command does not extend this deadline.
                if(transient_age>=cfg[15*32+16 +:16]) mode<=3;
            end else begin
                mode<=3;
                if(tracking_ok) transient_armed<=1;
            end
        end
    end
endmodule
