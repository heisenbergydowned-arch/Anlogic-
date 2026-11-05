`timescale 1ns / 1ns
module pwm #(
    parameter CLK_FREQ = 50000000, 
    parameter PWM_FREQ = 2,     
    parameter DUTY_CYCLE = 50     
)(
    input wire clk,               
    input wire rst_n,              
    output reg pwm_out            
);

    localparam PERIOD = CLK_FREQ / PWM_FREQ; 
    localparam DUTY_COUNT = (DUTY_CYCLE)*( PERIOD / 100);
    reg [31:0] counter;                    

   
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            counter <= 32'd0;
        end else begin
            if (counter < PERIOD) begin
                counter <= counter + 1;
            end else begin
                counter <= 32'd0;
            end
        end
    end

    
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pwm_out <= 1'b0;
        end else begin
            if (counter < DUTY_COUNT) begin
                pwm_out <= 1'b1;
            end else begin
                pwm_out <= 1'b0;
            end
        end
    end

endmodule