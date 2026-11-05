/************************************************************\
**	Copyright (c) 2012-2025 anlogic Inc.
**	All Right Reserved.
\************************************************************/
/************************************************************\
**	Gen time	:	2025-11-20 08:10:12
**	DI version	:	178912 2025/11/03
**	TD version	:	6.2.1(build number:178840)
\************************************************************/

module design_0_pwm_0_1 
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

    design_0_pwm_0 #(
        .CLK_FREQ(CLK_FREQ) ,
        .PWM_FREQ(PWM_FREQ) ,
        .DUTY_CYCLE(DUTY_CYCLE)
    ) design_0_pwm_0 (
        .clk(clk) ,
        .rst_n(rst_n) ,
        .pwm_out(pwm_out)
    );


endmodule
