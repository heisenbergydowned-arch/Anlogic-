module design_0_pwm_0 
#(
    parameter CLK_FREQ = 50000000 ,
    parameter PWM_FREQ = 2 ,
    parameter DUTY_CYCLE = 50
)
(
    input             clk ,
    input             rst_n ,
    output            pwm_out
) ;

    pwm #(
        .CLK_FREQ(CLK_FREQ) ,
        .PWM_FREQ(PWM_FREQ) ,
        .DUTY_CYCLE(DUTY_CYCLE)
    ) pwm (
        .clk(clk) ,
        .rst_n(rst_n) ,
        .pwm_out(pwm_out)
    );


endmodule
