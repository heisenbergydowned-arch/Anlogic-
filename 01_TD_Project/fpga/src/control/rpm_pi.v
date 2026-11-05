`timescale 1ns/1ps
// Q8 gains in PWM-count/RPM and PWM-count/RPM/update. A fixed-period step only
// integrates when at least one NEW valid FG measurement arrived. Three-cycle
// arithmetic pipeline; every override cancels it and tracks the actual output.
module rpm_pi(
    input wire clk, rst_n, enable, step,
    input wire [15:0] target_rpm, rpm, applied_duty, duty_min, duty_max, kp_q8, ki_q8,
    input wire rpm_new, rpm_valid,
    output reg [15:0] duty, output reg saturated
);
    reg fresh, was_enabled, primed;
    reg [1:0] state;
    reg signed [17:0] error;
    reg signed [35:0] p_term, i_delta;
    reg signed [39:0] integral;
    reg [15:0] seed;
    wire signed [39:0] min_q=$signed({1'b0,duty_min,8'd0});
    wire signed [39:0] max_q=$signed({1'b0,duty_max,8'd0});
    wire signed [39:0] p_ext={{4{p_term[35]}},p_term};
    wire signed [39:0] d_ext={{4{i_delta[35]}},i_delta};
    wire signed [39:0] i_candidate=integral+d_ext;
    wire signed [39:0] candidate=p_ext+i_candidate;
    wire signed [39:0] previous=p_ext+integral;
    wire pushing_out=(candidate>max_q && error>0) || (candidate<min_q && error<0);
    wire signed [39:0] chosen=pushing_out ? previous:candidate;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            duty<=0; saturated<=0; integral<=0; fresh<=0; was_enabled<=0; primed<=0;
            state<=0; error<=0; p_term<=0; i_delta<=0; seed<=0;
        end else if (!enable || !rpm_valid) begin
            duty<=applied_duty; saturated<=0; integral<=0; fresh<=0;
            was_enabled<=0; primed<=0; state<=0;
        end else begin
            was_enabled<=1;
            if (!was_enabled) begin seed<=applied_duty; duty<=applied_duty; fresh<=rpm_new; end
            else if (rpm_new) fresh<=1;
            case(state)
                0: if (step && (fresh || rpm_new) && was_enabled) begin
                    error<=$signed({2'b0,target_rpm})-$signed({2'b0,rpm}); fresh<=0; state<=1;
                end
                1: begin
                    p_term<=error*$signed({1'b0,kp_q8});
                    i_delta<=error*$signed({1'b0,ki_q8}); state<=2;
                end
                2: begin
                    if (!primed) begin
                        integral<=$signed({1'b0,seed,8'd0})-p_ext;
                        duty<=seed<duty_min ? duty_min:(seed>duty_max ? duty_max:seed);
                        primed<=1; saturated<=0;
                    end else begin
                        if (!pushing_out) integral<=i_candidate;
                        if (chosen>max_q) begin duty<=duty_max; saturated<=1; end
                        else if (chosen<min_q) begin duty<=duty_min; saturated<=1; end
                        else begin duty<=chosen[23:8]; saturated<=0; end
                    end
                    state<=0;
                end
                default: state<=0;
            endcase
        end
    end
endmodule
