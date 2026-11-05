`timescale 1ns/1ps
// Serialized 64-bit division (64 clocks), never on the fast protection path.
// PPR and all period limits belong to the qualified configuration.
module rpm_measure #(parameter CLK_FREQ=100_000_000)(
    input wire clk, rst_n, cfg_changed, tick_ms,
    input wire [767:0] cfg,
    input wire [31:0] period_count,
    input wire period_new, fg_timeout,
    output reg [15:0] rpm, output reg rpm_new,
    output wire valid, output reg [31:0] age_ms,
    output reg [31:0] rejected_periods
);
    wire [7:0] ppr=cfg[11*32+16 +:8];
    wire [31:0] min_period=cfg[21*32 +:32], max_period=cfg[22*32 +:32];
    wire [15:0] max_age=cfg[14*32 +:16];
    reg seen, latest_ok, calc_ok;
    reg [31:0] saved_config;
    reg start;
    reg [63:0] divisor;
    wire busy, done, zero;
    wire [63:0] quotient;
    wire acceptable=period_count>=min_period && period_count<=max_period && ppr!=0;
    wire [63:0] period_ext={32'd0,period_count};
    feature_udiv #(.WIDTH(64)) u_div(.clk(clk),.rst_n(rst_n),.start(start),
        .numerator(64'd60*CLK_FREQ),.denominator(divisor),
        .busy(busy),.done(done),.div_zero(zero),.quotient(quotient));
    assign valid=seen && latest_ok && age_ms<max_age && !fg_timeout;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rpm<=0; rpm_new<=0; age_ms<=32'hffff_ffff; rejected_periods<=0;
            seen<=0; latest_ok<=0; start<=0; divisor<=0; saved_config<=0; calc_ok<=0;
        end else begin
            rpm_new<=0; start<=0;
            if (tick_ms && age_ms!=32'hffff_ffff) age_ms<=age_ms+1'b1;
            if (cfg_changed) begin seen<=0; latest_ok<=0; calc_ok<=0; end
            else begin
                if (period_new) begin
                    if (!acceptable || busy || start) begin
                        latest_ok<=0; calc_ok<=0;
                        if (rejected_periods!=32'hffff_ffff) rejected_periods<=rejected_periods+1'b1;
                    end else begin
                        divisor<=period_ext*ppr; saved_config<=cfg[32 +:32];
                        start<=1; calc_ok<=1;
                    end
                end
                if (done && calc_ok && saved_config==cfg[32 +:32] && !(period_new && (!acceptable || busy || start))) begin
                    if (!zero && quotient!=0 && quotient<=65535 && !fg_timeout) begin
                        rpm<=quotient[15:0]; rpm_new<=1; seen<=1; latest_ok<=1; age_ms<=0;
                    end else begin latest_ok<=0; end
                    calc_ok<=0;
                end
            end
        end
    end
endmodule
