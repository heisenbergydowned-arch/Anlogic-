`timescale 1ns/1ps
// PWM action arbitration; no supply switching output.
module control_arbiter(
    input wire [767:0] cfg,
    input wire [31:0] active, latched,
    input wire [15:0] normal_duty,
    input wire [2:0] normal_action,
    input wire force_fallback, off_allowed,
    output reg [15:0] applied_duty,
    output reg [2:0] fan_action,
    output wire inhibit, output wire cooling_lost
);
    wire [31:0] reasons=active|latched;
    wire electrical_or_mechanical=|(reasons & 32'h0000_0b81); // OC,start,stall,overspeed,vib hard
    wire fan_limit=|(reasons & 32'h0000_0402);
    wire severe_heat=reasons[3];
    wire boost=reasons[2] || severe_heat;
    wire fallback=force_fallback || |(reasons & 32'h0000_3070); // ADC,temp,FG,PS,lease
    wire [15:0] fallback_duty=cfg[2*32+16 +:16], boost_duty=cfg[3*32 +:16];
    wire [15:0] limit_duty=cfg[3*32+16 +:16], maximum=cfg[4*32+16 +:16];
    assign inhibit=electrical_or_mechanical;
    assign cooling_lost=electrical_or_mechanical || fan_limit || reasons[4] || reasons[5] || reasons[6];
    wire [15:0] normal_bounded=normal_duty>maximum ? maximum:normal_duty;
    wire [15:0] normal_limited=normal_duty>limit_duty ? limit_duty:normal_duty;
    wire [15:0] fallback_limited=fallback_duty>limit_duty ? limit_duty:fallback_duty;
    wire [15:0] boost_limited=boost_duty>limit_duty ? limit_duty:boost_duty;
    always @* begin
        applied_duty=normal_bounded; fan_action=normal_action;
        if (fallback) begin applied_duty=fallback_duty; fan_action=4; end
        if (boost) begin applied_duty=boost_duty; fan_action=1; end
        if (fan_limit) begin
            applied_duty=boost ? boost_limited:(fallback ? fallback_limited:normal_limited);
            fan_action=2;
        end
        if (electrical_or_mechanical) begin applied_duty=0; fan_action=3; end
        if (off_allowed && !boost && !fallback && !fan_limit && !electrical_or_mechanical) begin applied_duty=0; fan_action=5; end
    end
endmodule
