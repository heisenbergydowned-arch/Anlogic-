`timescale 1ns/1ps
// KEY1: local manual step; KEY2 short: silence; KEY2 hold 2 s:
// local recovery request and 60 s maintenance/configuration authorization.
module cooling_buttons #(parameter DEBOUNCE_MS=20, parameter HOLD_MS=2000, parameter PERMIT_MS=60000)(
    input wire clk, rst_n, tick_ms, key1_n, key2_n,
    output reg manual_step, local_silence, local_reset,
    output wire local_permit
);
    reg [1:0] sync1,sync2;
    reg stable1,stable2,held;
    reg [15:0] debounce1,debounce2,hold_count,permit_count;
    assign local_permit=permit_count!=0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sync1<=3;sync2<=3;stable1<=1;stable2<=1;held<=0;
            debounce1<=0;debounce2<=0;hold_count<=0;permit_count<=0;
            manual_step<=0;local_silence<=0;local_reset<=0;
        end else begin
            sync1<={sync1[0],key1_n};sync2<={sync2[0],key2_n};
            manual_step<=0;local_silence<=0;local_reset<=0;
            if (tick_ms) begin
                if (permit_count!=0) permit_count<=permit_count-1'b1;
                if (sync1[1]==stable1) debounce1<=0;
                else if (debounce1>=DEBOUNCE_MS-1) begin
                    stable1<=sync1[1];debounce1<=0;
                    if (!sync1[1]) manual_step<=1;
                end else debounce1<=debounce1+1'b1;
                if (sync2[1]==stable2) debounce2<=0;
                else if (debounce2>=DEBOUNCE_MS-1) begin
                    stable2<=sync2[1];debounce2<=0;
                    if (sync2[1] && !held) local_silence<=1;
                    if (!sync2[1]) begin hold_count<=0;held<=0;end
                end else debounce2<=debounce2+1'b1;
                if (!stable2 && !held) begin
                    if (hold_count>=HOLD_MS-1) begin
                        held<=1;local_reset<=1;permit_count<=PERMIT_MS;
                    end else hold_count<=hold_count+1'b1;
                end
            end
        end
    end
endmodule
