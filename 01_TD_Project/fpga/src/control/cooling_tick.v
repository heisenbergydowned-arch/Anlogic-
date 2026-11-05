`timescale 1ns/1ps
// One monotonic millisecond time base. No wall-clock dependence.
module cooling_tick #(parameter CLK_FREQ=100_000_000)(
    input wire clk, rst_n, output reg tick_ms, output reg [31:0] now_ms
);
    localparam integer TICKS=CLK_FREQ/1000;
    reg [31:0] count;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin count<=0; tick_ms<=0; now_ms<=0; end
        else begin
            tick_ms<=0;
            if (count==TICKS-1) begin count<=0; tick_ms<=1; now_ms<=now_ms+1'b1; end
            else count<=count+1'b1;
        end
    end
endmodule
