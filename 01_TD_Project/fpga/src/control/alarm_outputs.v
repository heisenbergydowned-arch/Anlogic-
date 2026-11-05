`timescale 1ns/1ps
// Active-high enable for an active buzzer; polarity/circuit acceptance is physical.
// ACK is intentionally absent: acknowledgement never silences an alarm.
module alarm_outputs(
    input wire clk, rst_n, tick_ms,
    input wire [1:0] level, audible_level,
    input wire [31:0] sources,
    input wire local_silence,
    input wire [15:0] silence_ms,
    output reg buzzer, output reg red_flash,
    output wire red_on, output wire silenced
);
    reg [15:0] remaining;
    reg [10:0] phase;
    reg [31:0] previous_sources;
    reg [1:0] previous_level;
    wire new_fault=|(sources & ~previous_sources) || audible_level>previous_level;
    assign red_on=level!=0;
    assign silenced=remaining!=0;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            remaining<=0; phase<=0; previous_sources<=0; previous_level<=0; buzzer<=0; red_flash<=0;
        end else begin
            previous_sources<=sources; previous_level<=audible_level;
            if (new_fault) begin remaining<=0; phase<=0; end
            else if (local_silence && audible_level>=2) remaining<=silence_ms;
            else if (tick_ms && remaining!=0) remaining<=remaining-1'b1;
            if (!new_fault && tick_ms) phase<=phase==1999 ? 0:phase+1'b1;
            red_flash<=level==3 ? phase[7] : (level==2 ? phase[8] : (level==1 && phase[9]));
            if (remaining!=0 || audible_level<2) buzzer<=0;
            else if (audible_level==3) buzzer<=phase<200 || (phase>=400 && phase<600) || (phase>=1000 && phase<1200) || (phase>=1400 && phase<1600);
            else buzzer<=phase<200;
        end
    end
endmodule
