`timescale 1ns/1ps
// Confirmation/recovery require NEW valid observations. An invalid/old value
// cannot clear an active fault. A saturating 16-bit millisecond counter is
// shared by entry/recovery, so global uptime wrap cannot restart either timer.
module fault_filter(
    input wire clk, rst_n, tick_ms, enable, sample, valid,
    input wire enter_cond, recover_cond,
    input wire [31:0] now_ms,
    input wire [15:0] enter_ms, recover_ms,
    output reg active
);
    reg pending;
    reg [15:0] elapsed_ms;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin active<=0; pending<=0; elapsed_ms<=0; end
        else if (!enable) begin active<=0; pending<=0; elapsed_ms<=0; end
        else if (!valid) begin pending<=0; elapsed_ms<=0; end
        else begin
            if(tick_ms && pending && elapsed_ms!=16'hffff) elapsed_ms<=elapsed_ms+1'b1;
            if(sample) begin
                if(!active) begin
                    if(!enter_cond) begin pending<=0;elapsed_ms<=0;end
                    else if(enter_ms==0 || (pending && elapsed_ms>=enter_ms)) begin active<=1;pending<=0;elapsed_ms<=0;end
                    else if(!pending) begin pending<=1;elapsed_ms<=0;end
                end else begin
                    if(!recover_cond) begin pending<=0;elapsed_ms<=0;end
                    else if(recover_ms==0 || (pending && elapsed_ms>=recover_ms)) begin active<=0;pending<=0;elapsed_ms<=0;end
                    else if(!pending) begin pending<=1;elapsed_ms<=0;end
                end
            end
        end
    end
endmodule
