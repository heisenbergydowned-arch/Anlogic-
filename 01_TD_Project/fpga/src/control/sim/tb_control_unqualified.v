`timescale 1ns/1ps
// Production/bench-disabled startup must not drive an unqualified fallback.
module tb_control_unqualified;
    reg clk=0,rst_n=0;
    always #5 clk=~clk;
    reg req=0,write_en=0,manual_step=0;
    reg [15:0] address=0;
    reg [31:0] write_data=0;
    wire response,inhibit,buzzer;
    wire [31:0] read_data,active,latched;
    wire [7:0] error;
    wire [15:0] duty;
    wire [1:0] level;
    wire [2:0] fan_action;
    cooling_control #(.CLK_FREQ(1000000),.GRACE_MS(1),.STARTUP_MS(2),.BENCH_ENABLE(0)) dut(
        .clk(clk),.rst_n(rst_n),.adc_new(1'b0),.adc_error(1'b0),.current_raw(16'd0),.pressure_raw(16'd0),
        .temp_new(1'b0),.temp_present(1'b0),.temp_stale(1'b1),.temp_short(1'b0),.temp_raw(16'd0),
        .fg_new(1'b0),.fg_timeout(1'b1),.fg_period(32'd0),.fg_pulses(32'd0),
        .a_new(1'b0),.b_new(1'b0),.ax(16'd0),.ay(16'd0),.az(16'd0),.bx(16'd0),.by(16'd0),.bz(16'd0),
        .diagnostic_bad(1'b0),.auxiliary_bad(1'b0),.transport_bad_frames(32'd0),.transport_busy_drops(32'd0),
        .manual_step(manual_step),.local_silence(1'b0),.local_reset(1'b0),.local_permit(1'b1),
        .req(req),.write_en(write_en),.address(address),.write_data(write_data),.response(response),.read_data(read_data),.error(error),
        .applied_duty(duty),.hard_inhibit(inhibit),.buzzer(buzzer),.active(active),.latched(latched),
        .alarm_level(level),.fan_action(fan_action));
    integer checks=0;
    task check;input ok;input [639:0] name;begin checks=checks+1;if(ok!==1'b1)$fatal(1,"FAIL %0s",name);end endtask
    task write;input [15:0] addr;input [31:0] data;input [7:0] expected;begin
        @(negedge clk);req=1;write_en=1;address=addr;write_data=data;@(posedge clk);#1;
        check(response && error==expected,"Qualified command validation");
        @(negedge clk);req=0;@(posedge clk);#1;
    end endtask
    initial begin
        repeat(4)@(negedge clk);rst_n=1;repeat(15000)@(posedge clk);#1;
        check(inhibit && duty==0 && fan_action==3,"Unqualified non-bench output is inhibited");
        check(latched==0 && !active[7] && !dut.u_fsm.episode && !dut.desired_run && (dut.mode==1 || dut.mode==5),
            "No false startup episode while held off; FG quiet confirmation may still be pending");
        check(level==1 && !buzzer,"Configuration missing is explicit and silent");
        write(16'hc,1,0);write(16'h10,0,0);write(16'h14,3,0);
        write(16'hc,2,0);write(16'h10,6000,0);write(16'h14,1,2);
        @(negedge clk);manual_step=1;@(negedge clk);manual_step=0;repeat(10)@(posedge clk);#1;
        check(inhibit && duty==0 && !dut.ps_owned,"Local permit cannot qualify uncalibrated control");
        $display("ALL PASS tb_control_unqualified checks=%0d",checks);$finish;
    end
    initial begin #500000;$fatal(1,"TIMEOUT tb_control_unqualified");end
endmodule
