`timescale 1ns/1ps
module tb_temperature_pwm;
    reg clk=0,rst_n=0,tick=0,idle=1,adc_new=1,adc_valid=1,temp_valid=1,rpm_valid=1;
    reg signed [15:0] current_raw=16346,temp_raw=352;
    reg [15:0] rpm=1000;
    reg req=0,we=0;reg [7:0] addr=0;reg [31:0] data=0;
    wire response,armed,tripped,selected,driving,pwm;wire [31:0] result;wire [7:0] error;wire [15:0] duty;
    integer checks=0,t,expected,high_ticks;
    always #5 clk=~clk;
    temperature_pwm dut(.clk(clk),.rst_n(rst_n),.tick_ms(tick),.idle_allowed(idle),
        .adc_new(adc_new),.adc_valid(adc_valid),.temp_valid(temp_valid),.rpm_valid(rpm_valid),
        .current_raw(current_raw),.temp_raw(temp_raw),.rpm(rpm),
        .req(req),.write_en(we),.address(addr),.write_data(data),.response(response),
        .read_data(result),.error(error),.armed(armed),.tripped(tripped),.selected(selected),.driving(driving),.duty(duty));
    pwm_out #(.ENABLE_INHIBIT(1),.PIPELINE_DUTY(1)) out(.clk(clk),.rst_n(rst_n),
        .duty(duty),.inhibit(!driving),.pwm(pwm));
    task check;input ok;input [639:0] message;begin
        checks=checks+1;if(ok!==1'b1)$fatal(1,"FAIL %0s duty=%0d target=%0d causes=%h",message,duty,dut.target,dut.trip_reasons);
    end endtask
    task write;input [7:0] a;input [31:0] d;input [7:0] e;begin
        @(negedge clk);req=1;we=1;addr=a;data=d;@(posedge clk);#1;
        check(response && error==e,"CSR response and rejection");
        @(negedge clk);req=0;we=0;@(posedge clk);#1;
    end endtask
    task profile;begin
        write(8'h20,0,0);
        write(8'h10,{16'd1280,16'd400},0);
        write(8'h14,{16'd970,16'd16346},0);
        write(8'h18,{16'd6600,16'd2425},0);
        write(8'h1c,39,0);
        repeat(70)@(posedge clk);#1;
        check(dut.config_ok,"Fresh configuration is ready independently of current acquisition");
        write(8'h20,32'h54484d31,0);repeat(100)@(posedge clk);#1;
    end endtask
    task millisecond;begin
        @(negedge clk);tick=1;@(negedge clk);tick=0;@(posedge clk);#1;
    end endtask
    task trip;input [7:0] reason;begin
        repeat(2)@(posedge clk);#1;
        check(tripped && !armed && selected && duty==0 && (dut.trip_reasons & reason)!=0,"Fault latches output zero");
        write(8'h24,39,3);write(8'h20,32'h54484d31,3);
    end endtask
    initial begin
        repeat(4)@(negedge clk);rst_n=1;repeat(100)@(posedge clk);#1;
        check(!selected && duty==0,"Reset does not acquire actuator");
        write(8'h20,32'h54484d31,3);
        profile();
        // Independent exhaustive golden formula over the DS18B20 range.
        for(t=-880;t<=2000;t=t+1)begin
            @(negedge clk);temp_raw=t;repeat(80)@(posedge clk);#1;
            expected=t<=400 ? 0:(t>=1280 ? 4000:((t-400)*4000+440)/880);
            check(duty==expected,"Exhaustive temperature saturation and rounding");
        end
        temp_raw=840;repeat(6000)@(posedge clk);high_ticks=0;
        repeat(5000)begin @(posedge clk);#1;if(pwm)high_ticks=high_ticks+1;end
        check(duty==2000 && high_ticks==2500,"52.5 C produces 50 percent physical PWM in simulation");
        temp_raw=1280;repeat(6000)@(posedge clk);high_ticks=0;
        repeat(5000)begin @(posedge clk);#1;if(pwm)high_ticks=high_ticks+1;end
        check(duty==4000 && high_ticks==5000,"80 C produces continuous high PWM");
        temp_raw=352;repeat(6000)@(posedge clk);high_ticks=0;
        repeat(5000)begin @(posedge clk);#1;if(pwm)high_ticks=high_ticks+1;end
        check(duty==0 && high_ticks==0,"Room temperature produces zero PWM");
        write(8'h10,{16'd1200,16'd400},3);check(dut.cfg[0]=={16'd1280,16'd400},"Active profile immutable");
        for(t=0;t<499;t=t+1)millisecond();check(armed,"Watchdog valid before deadline");
        millisecond();check(armed && !tripped,"No heartbeat timeout cuts PWM");
        profile();temp_raw=840;repeat(100)@(posedge clk);temp_valid=0;temp_raw=-4096;repeat(100)@(posedge clk);check(armed && !tripped && duty==2000,"Invalid temperature data holds last valid PWM");temp_raw=840;temp_valid=1;
        profile();temp_raw=840;adc_valid=0;repeat(200)@(posedge clk);#1;
        check(armed && !tripped && duty==2000,"ADC invalid does not cut temperature PWM");
        profile();check(armed && duty==2000,"ARM does not require current mean or valid ADC");
        adc_valid=1;current_raw=16'sh7fff;repeat(200)@(posedge clk);#1;
        check(armed && !tripped && duty==2000,"Current ADC rail does not cut temperature PWM");
        profile();check(armed && duty==2000,"ARM permits ADC rail while temperature is valid");
        current_raw=16346;
        profile();temp_raw=840;current_raw=19346;repeat(200)@(posedge clk);#1;
        check(armed && !tripped && duty==2000 && dut.fault_causes==0,"Current peak no longer cuts temperature PWM");current_raw=16346;
        profile();current_raw=17846;repeat(200)@(posedge clk);#1;
        check(armed && !tripped && duty==2000 && dut.fault_causes==0,"Current mean no longer cuts temperature PWM");
        current_raw=19346;profile();check(armed && duty==2000,"High current telemetry does not reject ARM");current_raw=16346;
        profile();rpm=6700;repeat(100)@(posedge clk);check(armed && !tripped && duty==2000,"Overspeed is advisory only");rpm=1000;
        profile();idle=0;repeat(100)@(posedge clk);check(armed && !tripped && duty==2000,"Owner state does not interrupt active curve");idle=1;
        profile();temp_raw=840;rpm_valid=0;repeat(100)@(posedge clk);
        for(t=0;t<1999;t=t+1)begin millisecond();if(t%100==0)write(8'h24,39,0);end
        check(armed,"FG grace period before stalled-feedback trip");
        millisecond();check(armed && !tripped && duty==2000,"Missing FG is advisory only");rpm_valid=1;
        temp_raw=352;profile();
        // Continuous operation passes the former 30 s bench duration; leases remain mandatory.
        for(t=0;t<31000;t=t+1)begin millisecond();if(t%100==0)write(8'h24,39,0);end
        check(armed && !tripped && duty==0,"Continuous mode with healthy renewed lease");
        write(8'h20,0,0);check(!selected && duty==0,"Explicit disable releases ownership at zero");
        write(8'h10,{16'd400,16'd400},0);write(8'h14,{16'd970,16'd16346},0);
        write(8'h18,{16'd6600,16'd2425},0);write(8'h1c,40,0);repeat(70)@(posedge clk);
        write(8'h20,32'h54484d31,3);check(!armed,"Zero temperature span rejected");
        $display("ALL PASS tb_temperature_pwm checks=%0d",checks);$finish;
    end
    initial begin #10000000;$fatal(1,"TIMEOUT");end
endmodule
