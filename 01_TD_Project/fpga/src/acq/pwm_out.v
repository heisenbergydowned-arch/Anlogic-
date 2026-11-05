//============================================================================
// pwm_out.v — 风扇 PWM 输出（20kHz，归一化占空比）
//
// PWM_MAX = CLK_FREQ/PWM_HZ - 1（100MHz/20kHz → 4999）。
// duty 输入按 0..DUTY_FULL_SCALE 归一化，超出钳位，输出拍数四舍五入。
//============================================================================
module pwm_out #(
    parameter CLK_FREQ = 100_000_000,
    parameter PWM_HZ   = 20_000,
    parameter ENABLE_INHIBIT = 0,
    parameter DUTY_FULL_SCALE = 4000,
    // Optional one-cycle command latency; protection never uses this stage.
    parameter PIPELINE_DUTY = 0
)(
    input  wire        clk,
    input  wire        rst_n,
    input  wire [15:0] duty,
    input  wire        inhibit,   // qualified protection bypass, within one clock
    output reg         pwm
);
    localparam integer PWM_PERIOD = CLK_FREQ / PWM_HZ;
    localparam [15:0] PWM_MAX = PWM_PERIOD[15:0] - 16'd1;
    localparam [15:0] PWM_TOP = PWM_MAX + 16'd1;
    localparam [15:0] DUTY_TOP = DUTY_FULL_SCALE[15:0];

    wire kill = ENABLE_INHIBIT && inhibit;
    wire [15:0] duty_clamped = (duty > DUTY_TOP) ? DUTY_TOP : duty;
    wire [15:0] duty_eff;
    wire [31:0] duty_ticks;
    generate
        if (PIPELINE_DUTY) begin : command_stage
            reg [15:0] duty_q;
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) duty_q <= 16'd0;
                else if (kill) duty_q <= 16'd0;
                else duty_q <= duty_clamped;
            end
            assign duty_eff = duty_q;
        end else begin : direct_command
            assign duty_eff = duty_clamped;
        end
        if (CLK_FREQ / PWM_HZ == 5000 && DUTY_FULL_SCALE == 4000) begin : scale_five_fourths
            assign duty_ticks = ({16'd0, duty_eff} * 32'd5 + 32'd2) >> 2;
        end else begin : scale_general
            assign duty_ticks = (duty_eff * PWM_TOP + DUTY_FULL_SCALE / 2) / DUTY_FULL_SCALE;
        end
    endgenerate

    reg [15:0] cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 16'd0;
            pwm <= 1'b0;
        end else begin
            if (cnt >= PWM_MAX) cnt <= 16'd0;
            else                cnt <= cnt + 16'd1;
            // Use the current inhibit, not a delayed copy of the command.
            pwm <= kill ? 1'b0 : ({16'd0, cnt} < duty_ticks);
        end
    end

endmodule
