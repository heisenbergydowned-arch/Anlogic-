`timescale 1ns/1ps
// Small I/O wrapper for a resource/timing ESTIMATE, not a board top or bitstream.
// Serial sensor injection preserves all control paths without hundreds of pads.
module control_synth_top(
    input wire clk,rst_n,shift_en,load_sensors,input wire [31:0] sensor_word,
    input wire [11:0] sensor_flags,input wire rx,key1_n,key2_n,
    output wire tx,pwm,buzzer,red,output wire [31:0] observed
);
    reg [255:0] shift,snapshot;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin shift<=0;snapshot<=0;end
        else begin if(shift_en)shift<={shift[223:0],sensor_word};if(load_sensors)snapshot<=shift;end
    end
    wire ms;wire [31:0] now_ms;
    wire manual,silence,reset,permit;
    cooling_tick u_tick(.clk(clk),.rst_n(rst_n),.tick_ms(ms),.now_ms(now_ms));
    cooling_buttons u_buttons(.clk(clk),.rst_n(rst_n),.tick_ms(ms),.key1_n(key1_n),.key2_n(key2_n),
        .manual_step(manual),.local_silence(silence),.local_reset(reset),.local_permit(permit));
    wire req,wr,response,holdoff,tx_active;
    wire [15:0] addr,duty;wire [31:0] wd,rd,bad,drops,active,latched;wire [7:0] error;
    wire inhibit,flash,stable;wire [1:0] level;wire [2:0] action;wire [3:0] mode;wire [767:0] cfg;
    cooling_uart u_uart(.clk(clk),.rst_n(rst_n),.rx(rx),.dbg_busy(1'b0),.dbg_holdoff(holdoff),.tx(tx),.tx_active(tx_active),
        .req(req),.write_en(wr),.address(addr),.write_data(wd),.response(response),.read_data(rd),.error(error),.bad_frames(bad),.busy_drops(drops));
    cooling_control u_control(.clk(clk),.rst_n(rst_n),.adc_new(sensor_flags[0]),.adc_error(sensor_flags[1]),
        .current_raw(snapshot[15:0]),.pressure_raw(snapshot[31:16]),.temp_raw(snapshot[47:32]),
        .temp_new(sensor_flags[2]),.temp_present(sensor_flags[3]),.temp_stale(sensor_flags[4]),.temp_short(sensor_flags[5]),
        .fg_new(sensor_flags[6]),.fg_timeout(sensor_flags[7]),.fg_period(snapshot[79:48]),.fg_pulses(snapshot[111:80]),
        .a_new(sensor_flags[8]),.b_new(sensor_flags[9]),.ax(snapshot[127:112]),.ay(snapshot[143:128]),.az(snapshot[159:144]),
        .bx(snapshot[175:160]),.by(snapshot[191:176]),.bz(snapshot[207:192]),
        .diagnostic_bad(sensor_flags[10]),.auxiliary_bad(sensor_flags[11]),.transport_bad_frames(bad),.transport_busy_drops(drops),
        .manual_step(manual),.local_silence(silence),.local_reset(reset),.local_permit(permit),
        .req(req),.write_en(wr),.address(addr),.write_data(wd),.response(response),.read_data(rd),.error(error),
        .applied_duty(duty),.hard_inhibit(inhibit),.buzzer(buzzer),.red_on(red),.red_flash(flash),
        .active(active),.latched(latched),.alarm_level(level),.fan_action(action),.mode(mode),.stable_run(stable),.active_config(cfg));
    pwm_out #(.ENABLE_INHIBIT(1)) u_pwm(.clk(clk),.rst_n(rst_n),.duty(duty),.inhibit(inhibit),.pwm(pwm));
    assign observed=active^latched^{11'd0,duty,mode,stable};
endmodule
