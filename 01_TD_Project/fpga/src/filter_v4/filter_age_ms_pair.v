`timescale 1ns/1ps
module filter_age_ms_pair(
    input wire clk,rst_n,start,cancel,
    input wire temp_seen,pressure_seen,
    input wire [63:0] temp_age,pressure_age,
    output reg busy,done,fault,
    output reg [31:0] temp_ms,pressure_ms
);
    reg [31:0] temp_dividend,pressure_dividend;
    reg [14:0] temp_quotient,pressure_quotient;
    reg [16:0] temp_remainder,pressure_remainder;
    reg [4:0] step;
    reg temp_unknown,pressure_unknown;
    wire [17:0] expanded_temp={temp_remainder,temp_dividend[31]};
    wire [17:0] expanded_pressure={pressure_remainder,pressure_dividend[31]};
    wire temp_ge=expanded_temp>=18'd100000,pressure_ge=expanded_pressure>=18'd100000;
    wire [16:0] reduced_temp=expanded_temp[16:0]-17'd100000;
    wire [16:0] reduced_pressure=expanded_pressure[16:0]-17'd100000;
    wire [15:0] next_temp_quotient={temp_quotient,temp_ge};
    wire [15:0] next_pressure_quotient={pressure_quotient,pressure_ge};
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy<=0;done<=0;fault<=0;temp_ms<=32'hffffffff;pressure_ms<=32'hffffffff;
            temp_dividend<=0;pressure_dividend<=0;temp_quotient<=0;pressure_quotient<=0;
            temp_remainder<=0;pressure_remainder<=0;step<=0;temp_unknown<=1;pressure_unknown<=1;
        end else begin
            done<=0;fault<=0;
            if (cancel)busy<=0;
            else if (start) begin
                if (busy) begin
                    busy<=0;done<=1;fault<=1;temp_ms<=32'hffffffff;pressure_ms<=32'hffffffff;
                end else begin
                    busy<=1;step<=0;temp_remainder<=0;pressure_remainder<=0;
                    temp_quotient<=0;pressure_quotient<=0;
                    temp_dividend<=temp_age[31:0];pressure_dividend<=pressure_age[31:0];
                    temp_unknown<=!temp_seen || temp_age[63:32]!=0;
                    pressure_unknown<=!pressure_seen || pressure_age[63:32]!=0;
                end
            end else if (busy) begin
                temp_dividend<={temp_dividend[30:0],1'b0};pressure_dividend<={pressure_dividend[30:0],1'b0};
                temp_remainder<=temp_ge ? reduced_temp : expanded_temp[16:0];
                pressure_remainder<=pressure_ge ? reduced_pressure : expanded_pressure[16:0];
                temp_quotient<=next_temp_quotient[14:0];pressure_quotient<=next_pressure_quotient[14:0];
                if (step==31) begin
                    busy<=0;done<=1;
                    temp_ms<=temp_unknown ? 32'hffffffff : {16'd0,next_temp_quotient};
                    pressure_ms<=pressure_unknown ? 32'hffffffff : {16'd0,next_pressure_quotient};
                end else step<=step+5'd1;
            end
        end
    end
endmodule
