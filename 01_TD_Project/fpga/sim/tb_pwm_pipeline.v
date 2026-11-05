`timescale 1ns/1ps
module tb_pwm_pipeline;
    reg clk=0, rst_n=1, inhibit=0;
    reg [15:0] duty=0;
    wire pwm, ignored_inhibit_pwm, general_pwm;
    always #5 clk=~clk;
    pwm_out #(.ENABLE_INHIBIT(1),.PIPELINE_DUTY(1)) dut(
        .clk(clk),.rst_n(rst_n),.duty(duty),.inhibit(inhibit),.pwm(pwm));
    pwm_out #(.ENABLE_INHIBIT(0),.PIPELINE_DUTY(1)) no_protection(
        .clk(clk),.rst_n(rst_n),.duty(duty),.inhibit(inhibit),.pwm(ignored_inhibit_pwm));
    pwm_out #(.PWM_HZ(25000),.ENABLE_INHIBIT(1),.PIPELINE_DUTY(1)) general_scale(
        .clk(clk),.rst_n(rst_n),.duty(duty),.inhibit(inhibit),.pwm(general_pwm));

    integer phase20=0,phase25=0,previous_command=0,previous_unprotected=0;
    integer checks=0,expected20,expected25,expected_unprotected,captured_command;
    integer d,i,j,high_ticks,seed=20261103,random_value,offset;
    reg previous_pwm;
    integer last_rise,cycle;
    // Reference observes only interface inputs. Current inhibit takes priority
    // over the previous edge's clamped command; it is never pipelined.
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            phase20=0;phase25=0;previous_command=0;previous_unprotected=0;
            #1;
            if(pwm!==0 || ignored_inhibit_pwm!==0 || general_pwm!==0)
                $fatal(1,"Asynchronous reset failed");
        end else begin
            expected20=!inhibit && phase20<((previous_command*5000+2000)/4000);
            expected25=!inhibit && phase25<previous_command;
            expected_unprotected=phase20<((previous_unprotected*5000+2000)/4000);
            captured_command=duty>4000 ? 4000:duty;
            previous_command=inhibit ? 0:captured_command;
            previous_unprotected=captured_command;
            phase20=(phase20+1)%5000;phase25=(phase25+1)%4000;
            #1;
            if(pwm!==expected20 || general_pwm!==expected25 || ignored_inhibit_pwm!==expected_unprotected)
                $fatal(1,"Command latency/current-inhibit mismatch check=%0d duty=%0d inhibit=%0d",checks,duty,inhibit);
            checks=checks+1;
        end
    end

    initial begin
        #2;rst_n=0;
        #1.5;
        if(pwm!==0) $fatal(1,"Reset waited for a clock");
        @(negedge clk);rst_n=1;duty=4000;
        @(posedge clk);#2;
        if(pwm!==0) $fatal(1,"Normal command did not have exactly one stage");
        @(posedge clk);#2;
        if(pwm!==1) $fatal(1,"Normal command delayed more than one stage");

        // Inhibit arrives asynchronously 1..4 ns after the falling edge,
        // while a full-duty command and its old staged value are nonzero.
        for(offset=1;offset<=4;offset=offset+1) begin
            @(negedge clk);duty=4000;inhibit=0;
            repeat(3) begin @(posedge clk);#2;end
            if(pwm!==1) $fatal(1,"Directed inhibit setup did not reach high");
            @(negedge clk);#(offset);inhibit=1;duty=65535;
            #0.1;
            if(pwm!==1) $fatal(1,"Registered output changed before its clock");
            @(posedge clk);#2;
            if(pwm!==0) $fatal(1,"Inhibit was delayed by command pipeline");
            @(negedge clk);inhibit=0;duty=4000;
            @(posedge clk);#2;
            if(pwm!==0) $fatal(1,"Stale command revived immediately after inhibit");
            @(posedge clk);#2;
            if(pwm!==1) $fatal(1,"New post-inhibit command failed to start");
        end

        // Sweep every useful command through one entire steady carrier cycle.
        for(d=0;d<=4000;d=d+1) begin
            @(negedge clk);rst_n=0;duty=d;inhibit=0;
            @(negedge clk);rst_n=1;
            @(posedge clk);#2; // Explicitly account for command-stage priming.
            if(pwm!==0) $fatal(1,"Reset did not clear staged duty");
            high_ticks=0;
            for(i=0;i<5000;i=i+1) begin
                @(posedge clk);#2;
                if(pwm) high_ticks=high_ticks+1;
            end
            if(high_ticks!=(d*5000+2000)/4000)
                $fatal(1,"Steady carrier high-time mismatch duty=%0d count=%0d",d,high_ticks);
        end
        for(d=4001;d<=65535;d=d+1) begin
            @(negedge clk);duty=d;
            @(posedge clk);#2;
            if(pwm!==1) $fatal(1,"Pipelined clamp failed");
        end

        // Every edge has a new command; inhibit may change between edges.
        for(i=0;i<40000;i=i+1) begin
            @(negedge clk);random_value=$random(seed);duty=random_value;
            #2;inhibit=(i%3==0);
            @(posedge clk);#2;
        end

        @(negedge clk);inhibit=0;duty=2000;
        repeat(2) begin @(posedge clk);#2;end
        previous_pwm=pwm;last_rise=-1;
        for(cycle=0;cycle<20000;cycle=cycle+1) begin
            @(posedge clk);#2;
            if(pwm && !previous_pwm) begin
                if(last_rise>=0 && cycle-last_rise!=5000) $fatal(1,"Carrier period changed");
                last_rise=cycle;
            end
            previous_pwm=pwm;
        end
        @(negedge clk);duty=4000;
        repeat(2) begin @(posedge clk);#2;end
        #1;rst_n=0;
        #1.5;
        if(pwm!==0) $fatal(1,"Reset during active pulse failed");
        @(negedge clk);duty=0;rst_n=1;
        repeat(3) begin @(posedge clk);#2;if(pwm!==0) $fatal(1,"Old duty survived reset");end
        $display("tb_pwm_pipeline: ALL PASS checks=%0d; 4001 steady duty sweeps, 61535 clamps, 40000 consecutive commands, asynchronous inhibit offsets 1..4ns, exact one-stage command latency, direct next-edge kill and cleared rearm",checks);
        $finish;
    end
    initial begin #220000000;$fatal(1,"tb_pwm_pipeline TIMEOUT");end
endmodule
