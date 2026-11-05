`timescale 1ns/1ps
// Native-unit protection: ADC distance from calibrated zero (17-bit magnitude),
// DS18B20 signed 1/16 degree C, integer RPM, ICM raw int16 magnitudes.
// Numerical rules stay disabled until their qualification flags are committed.
module safety_monitor #(parameter PRESSURE_INDEPENDENT=0,parameter PRESSURE_MAX_MS=100)(
    input wire clk, rst_n, tick_ms,
    input wire [31:0] now_ms,
    input wire [767:0] cfg,
    input wire adc_new, adc_error,
    input wire signed [15:0] current_raw, pressure_raw,
    input wire pressure_new, pressure_error,
    input wire temp_new, temp_present, temp_stale, temp_short,
    input wire signed [15:0] temp_raw,
    input wire [15:0] rpm, input wire rpm_new, rpm_valid,
    input wire a_new, b_new,
    input wire signed [15:0] ax, ay, az, bx, by, bz,
    output wire adc_valid, temp_valid, pressure_valid,
    output reg [31:0] adc_age_ms, temp_age_ms,
    output wire [16:0] current_magnitude,
    output wire [31:0] rule_active,
    output reg [31:0] fast_trip
);
    wire current_en=cfg[0], temp_en=cfg[1], actuator_en=cfg[2], vib_en=cfg[4];
    wire signed [15:0] zero=cfg[7*32 +:16];
    wire [15:0] current_high=cfg[7*32+16 +:16], current_hard=cfg[8*32 +:16];
    wire [15:0] current_recover=cfg[8*32+16 +:16];
    wire signed [15:0] temp_warn=cfg[9*32 +:16], temp_hard=cfg[9*32+16 +:16];
    wire signed [15:0] temp_recover=cfg[10*32 +:16];
    wire [15:0] vib_limit=cfg[10*32+16 +:16], vib_hard=cfg[11*32 +:16];
    wire [15:0] recover_ms=cfg[14*32+16 +:16];
    wire signed [16:0] delta={current_raw[15],current_raw}-{zero[15],zero};
    assign current_magnitude=delta[16] ? -delta : delta;
    reg adc_seen, temp_seen, pressure_seen;
    reg [31:0] pressure_age_ms;
    wire current_rail=current_raw==16'sh8000 || current_raw==16'sh7fff;
    wire pressure_rail=pressure_raw==16'sh8000 || pressure_raw==16'sh7fff;
    wire temp_bad=!temp_present || temp_stale || temp_short || temp_raw< -16'sd880 || temp_raw>16'sd2000;
    reg last_current_good, last_pressure_good;
    assign adc_valid=adc_seen && last_current_good && !adc_error && adc_age_ms<cfg[13*32 +:16];
    assign pressure_valid=PRESSURE_INDEPENDENT ?
        (pressure_seen && last_pressure_good && !pressure_error && pressure_age_ms<PRESSURE_MAX_MS):
        (adc_seen && last_pressure_good && !adc_error && adc_age_ms<cfg[13*32 +:16]);
    assign temp_valid=temp_seen && !temp_bad && temp_age_ms<cfg[13*32+16 +:16];
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            adc_seen<=0; temp_seen<=0; pressure_seen<=0; last_current_good<=0; last_pressure_good<=0;
            adc_age_ms<=32'hffff_ffff; temp_age_ms<=32'hffff_ffff;
            pressure_age_ms<=32'hffff_ffff;
        end else begin
            if (tick_ms) begin
                if (adc_age_ms!=32'hffff_ffff) adc_age_ms<=adc_age_ms+1'b1;
                if (temp_age_ms!=32'hffff_ffff) temp_age_ms<=temp_age_ms+1'b1;
                if (pressure_age_ms!=32'hffff_ffff) pressure_age_ms<=pressure_age_ms+1'b1;
            end
            if (adc_new && !adc_error) begin
                adc_seen<=1; adc_age_ms<=0; last_current_good<=!current_rail;
                if(!PRESSURE_INDEPENDENT)last_pressure_good<=!pressure_rail;
            end
            if(PRESSURE_INDEPENDENT && pressure_new)begin
                last_pressure_good<=!pressure_error && !pressure_rail;
                if(!pressure_error && !pressure_rail)begin pressure_seen<=1;pressure_age_ms<=0;end
            end
            if (temp_new && !temp_bad) begin temp_seen<=1; temp_age_ms<=0; end
        end
    end
    wire current_good=adc_valid && !current_rail;
    wire oc_now=current_en && adc_new && !adc_error && !current_rail && current_magnitude>=current_hard;
    wire hot_now=temp_en && temp_new && !temp_bad && temp_raw>=temp_hard;
    wire over_now=actuator_en && rpm_new && rpm_valid && rpm>=cfg[23*32 +:16];
    wire oc_active, high_active, warm_active, hot_active, over_active;
    fault_filter u_oc(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.enable(current_en),.sample(adc_new),
        .valid(current_good),.enter_cond(current_magnitude>=current_hard),.recover_cond(current_magnitude<=current_recover),
        .now_ms(now_ms),.enter_ms(16'd0),.recover_ms(recover_ms),.active(oc_active));
    fault_filter u_high(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.enable(current_en),.sample(adc_new),
        .valid(current_good),.enter_cond(current_magnitude>=current_high),.recover_cond(current_magnitude<=current_recover),
        .now_ms(now_ms),.enter_ms(cfg[18*32 +:16]),.recover_ms(recover_ms),.active(high_active));
    fault_filter u_warm(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.enable(temp_en),.sample(temp_new),
        .valid(temp_valid),.enter_cond(temp_raw>=temp_warn),.recover_cond(temp_raw<=temp_recover),
        .now_ms(now_ms),.enter_ms(cfg[18*32+16 +:16]),.recover_ms(recover_ms),.active(warm_active));
    fault_filter u_hot(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.enable(temp_en),.sample(temp_new),
        .valid(temp_valid),.enter_cond(temp_raw>=temp_hard),.recover_cond(temp_raw<=temp_recover),
        .now_ms(now_ms),.enter_ms(16'd0),.recover_ms(recover_ms),.active(hot_active));
    fault_filter u_over(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.enable(actuator_en),.sample(rpm_new),
        .valid(rpm_valid),.enter_cond(rpm>=cfg[23*32 +:16]),.recover_cond(rpm<=cfg[5*32+16 +:16]),
        .now_ms(now_ms),.enter_ms(16'd0),.recover_ms(recover_ms),.active(over_active));
    function [15:0] magnitude;
        input signed [15:0] x;
        begin magnitude=x[15] ? -x : x; end
    endfunction
    function [15:0] max3;
        input [15:0] x,y,z;
        begin max3=(x>y ? (x>z ? x:z) : (y>z ? y:z)); end
    endfunction
    wire [15:0] peak_a=max3(magnitude(ax),magnitude(ay),magnitude(az));
    wire [15:0] peak_b=max3(magnitude(bx),magnitude(by),magnitude(bz));
    wire good_a=peak_a<32767, good_b=peak_b<32767;
    wire va, vb, vha, vhb;
    // Separate per-sensor filters prevent A/B alternating samples from breaking
    // each other's sustained evidence. Saturation is a quality fault, not proof.
    fault_filter u_va(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.enable(vib_en),.sample(a_new),.valid(good_a),
        .enter_cond(peak_a>=vib_limit),.recover_cond(peak_a<vib_limit),.now_ms(now_ms),
        .enter_ms(cfg[19*32+16 +:16]),.recover_ms(recover_ms),.active(va));
    fault_filter u_vb(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.enable(vib_en),.sample(b_new),.valid(good_b),
        .enter_cond(peak_b>=vib_limit),.recover_cond(peak_b<vib_limit),.now_ms(now_ms),
        .enter_ms(cfg[19*32+16 +:16]),.recover_ms(recover_ms),.active(vb));
    fault_filter u_vha(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.enable(vib_en),.sample(a_new),.valid(good_a),
        .enter_cond(peak_a>=vib_hard),.recover_cond(peak_a<vib_limit),.now_ms(now_ms),
        .enter_ms(16'd0),.recover_ms(recover_ms),.active(vha));
    fault_filter u_vhb(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.enable(vib_en),.sample(b_new),.valid(good_b),
        .enter_cond(peak_b>=vib_hard),.recover_cond(peak_b<vib_limit),.now_ms(now_ms),
        .enter_ms(16'd0),.recover_ms(recover_ms),.active(vhb));
    wire vib_now=vib_en && ((a_new && good_a && peak_a>=vib_hard) || (b_new && good_b && peak_b>=vib_hard));
    // Register fresh trip evidence before fan/event/CSR fanout. Protection does
    // not wait for a millisecond tick; PWM inhibition reaches the output within
    // two rising edges after the input's sample-valid/data become stable.
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) fast_trip<=0;
        else fast_trip<=(oc_now ? 32'h0000_0001:0) | (hot_now ? 32'h0000_0008:0)
                       | (over_now ? 32'h0000_0200:0) | (vib_now ? 32'h0000_0800:0);
    end
    assign rule_active=(oc_active ? 32'h1:0) | (high_active ? 32'h2:0) | (warm_active ? 32'h4:0)
                    | (hot_active ? 32'h8:0) | (over_active ? 32'h200:0)
                    | ((va||vb) ? 32'h400:0) | ((vha||vhb) ? 32'h800:0) | fast_trip;
endmodule
