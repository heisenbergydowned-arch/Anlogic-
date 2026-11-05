`timescale 1ns/1ps
// Shared unsigned restoring divider. All operands are unsigned; latency = WIDTH.
module feature_udiv #(parameter WIDTH = 96) (
    input wire clk, input wire rst_n, input wire start,
    input wire [WIDTH-1:0] numerator, denominator,
    output reg busy, output reg done, output reg div_zero,
    output reg [WIDTH-1:0] quotient
);
    // q combines unread dividend bits and generated quotient bits.
    reg [WIDTH-1:0] divisor, q;
    reg [WIDTH:0] remainder;
    reg [7:0] count;
    wire [WIDTH:0] trial = {remainder[WIDTH-1:0], q[WIDTH-1]};
    // The extra subtraction bit is the borrow: reuse this result for both
    // comparison and remainder update rather than a second wide comparator.
    wire [WIDTH+1:0] difference={1'b0,trial}-{2'b00,divisor};
    wire take = !difference[WIDTH+1];
    wire [WIDTH-1:0] q_next = (q<<1) | {{(WIDTH-1){1'b0}},take};
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy<=0; done<=0; div_zero<=0; quotient<=0;
            divisor<=0; q<=0; remainder<=0; count<=0;
        end else begin
            done<=0;
            if (start && !busy) begin
                div_zero <= denominator == 0;
                if (denominator == 0) begin quotient<=0; done<=1; end
                else begin
                    busy<=1; divisor<=denominator;
                    q<=numerator; remainder<=0; count<=WIDTH;
                end
            end else if (busy) begin
                remainder <= take ? difference[WIDTH:0] : trial;
                q<=q_next; count<=count-1'b1;
                if (count==1) begin busy<=0; done<=1; quotient<=q_next; end
            end
        end
    end
endmodule
