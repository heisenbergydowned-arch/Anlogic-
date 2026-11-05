`timescale 1ns/1ps
module tb_temperature_owner;
    reg clk=0,rst_n=0,req=0,we=0;
    reg [15:0] address=0;reg [31:0] data=0,pulses=0;
    reg signed [15:0] current=16346,temp=840;
    wire response,inhibit;wire [31:0] result,active,latched;wire [7:0] error;
    wire [15:0] duty;wire [1:0] alarm;wire [1023:0] status;
    integer checks=0;
    always #5 clk=~clk;
    always @(posedge clk)pulses<=pulses+1'b1;
    cooling_control #(.CLK_FREQ(1000000),.GRACE_MS(1),.BENCH_ENABLE(0)) dut(
        .clk(clk),.rst_n(rst_n),.adc_new(1'b1),.adc_error(1'b0),.current_raw(current),.pressure_raw(16'd0),
        .pressure_new(1'b0),.pressure_error(1'b0),.temp_new(1'b1),.temp_present(1'b1),
        .temp_stale(1'b0),.temp_short(1'b0),.temp_raw(temp),
        .fg_new(1'b1),.fg_timeout(1'b0),.fg_period(32'd30000),.fg_pulses(pulses),
        .a_new(1'b1),.b_new(1'b1),.ax(16'd0),.ay(16'd0),.az(16'd0),.bx(16'd0),.by(16'd0),.bz(16'd0),
        .diagnostic_bad(1'b0),.auxiliary_bad(1'b0),.transport_bad_frames(32'd0),.transport_busy_drops(32'd0),
        .manual_step(1'b0),.local_silence(1'b0),.local_reset(1'b0),.local_permit(1'b0),
        .req(req),.write_en(we),.address(address),.write_data(data),.response(response),.read_data(result),.error(error),
        .applied_duty(duty),.hard_inhibit(inhibit),.active(active),.latched(latched),.alarm_level(alarm),.monitor_status(status));
    task check;input ok;input [639:0] name;begin
        checks=checks+1;if(ok!==1'b1)$fatal(1,"FAIL %0s result=%h error=%d active=%h latched=%h",name,result,error,active,latched);
    end endtask
    task write;input [15:0] a;input [31:0] d;input [7:0] e;begin
        @(negedge clk);req=1;we=1;address=a;data=d;@(posedge clk);#1;
        check(response && error==e,"CSR write arbitration");@(negedge clk);req=0;we=0;@(posedge clk);#1;
    end endtask
    task read;input [15:0] a;input [31:0] expected;begin
        @(negedge clk);req=1;we=0;address=a;@(posedge clk);#1;
        check(response && error==0 && result==expected,"CSR read routing");@(negedge clk);req=0;@(posedge clk);#1;
    end endtask
    initial begin
        repeat(4)@(negedge clk);rst_n=1;repeat(5000)@(posedge clk);#1;
        check(status[22] && !status[14] && inhibit && duty==0,"Capability exposed without granting PI qualification");
        read(16'h0a00,32'h54505731);read(16'h0a04,32'h10000);
        write(16'h0a10,{16'd1280,16'd400},0);write(16'h0a14,{16'd970,16'd16346},0);
        write(16'h0a18,{16'd6600,16'd2425},0);write(16'h0a1c,39,0);
        repeat(70)@(posedge clk);write(16'h0a20,32'h54484d31,0);repeat(100)@(posedge clk);#1;
        check(duty==2000 && !inhibit && !dut.initial_config_permit,"Temperature owns actual duty without KEY2");
        check(status[7*32+:16]==2000 && !status[14],"Actual status duty and unchanged qualification");
        write(16'h0910,4000,3);write(16'h0928,32'h41524d32,3);
        current=19346;repeat(10)@(posedge clk);#1;
        check(duty==0 && inhibit && active[0] && alarm==3 && latched==0,"Thermal fault alarms without creating legacy KEY reset dependency");
        write(16'h0a24,39,3);current=16346;write(16'h0a20,0,0);repeat(100)@(posedge clk);#1;
        check(!active[0] && latched==0 && duty==0,"Explicit stop clears only thermal ownership/fault");
        write(16'h0910,4000,0);write(16'h0914,16346,0);write(16'h0918,512,0);
        write(16'h091c,1600,0);write(16'h0920,1000,0);write(16'h0924,1000,0);
        write(16'h0928,32'h41524d32,0);
        write(16'h0a10,{16'd1280,16'd400},3);write(16'h0a20,32'h54484d31,3);
        write(16'h0930,0,0);read(16'h0904,32'h20000);
        $display("ALL PASS tb_temperature_owner checks=%0d",checks);$finish;
    end
    initial begin #1000000;$fatal(1,"TIMEOUT");end
endmodule
