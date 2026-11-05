`timescale 1ns/1ps
module tb_cooling_control;
    reg clk=0,rst_n=0;
    always #5 clk=~clk;
    reg adc_on=1,temp_on=1,fg_on=1,icm_on=1;
    reg adc_new=0,temp_new=0,fg_new=0,a_new=0,b_new=0;
    reg adc_error=0,temp_present=1,temp_stale=0,temp_short=0;
    reg signed [15:0] current_raw=20,pressure_raw=40,temp_raw=400;
    reg signed [15:0] ax=20,ay=30,az=40,bx=25,by=35,bz=45;
    reg [31:0] fg_period=5000,fg_pulses=0;
    reg diagnostic_bad=0,auxiliary_bad=0;
    reg manual_step=0,local_silence=0,local_reset=0,local_permit=1;
    reg req=0,write_en=0;
    reg [15:0] address=0;
    reg [31:0] write_data=0;
    wire response;
    wire [31:0] read_data;
    wire [7:0] error;
    wire [15:0] duty;
    wire inhibit,buzzer,red_on,red_flash,stable_run;
    wire [31:0] active,latched;
    wire [1:0] level;
    wire [2:0] fan_action;
    wire [3:0] mode;
    wire [767:0] cfg;
    // Accelerated virtual time. Values below are simulation vectors ONLY.
    cooling_control #(.CLK_FREQ(1_000_000),.GRACE_MS(5),.CONTROL_MS(2),.STARTUP_MS(8)) dut(
        .clk(clk),.rst_n(rst_n),.adc_new(adc_new),.adc_error(adc_error),.current_raw(current_raw),.pressure_raw(pressure_raw),
        .temp_new(temp_new),.temp_present(temp_present),.temp_stale(temp_stale),.temp_short(temp_short),.temp_raw(temp_raw),
        .fg_new(fg_new),.fg_timeout(1'b0),.fg_period(fg_period),.fg_pulses(fg_pulses),
        .a_new(a_new),.b_new(b_new),.ax(ax),.ay(ay),.az(az),.bx(bx),.by(by),.bz(bz),
        .diagnostic_bad(diagnostic_bad),.auxiliary_bad(auxiliary_bad),
        .transport_bad_frames(32'd0),.transport_busy_drops(32'd0),
        .manual_step(manual_step),.local_silence(local_silence),.local_reset(local_reset),.local_permit(local_permit),
        .req(req),.write_en(write_en),.address(address),.write_data(write_data),.response(response),.read_data(read_data),.error(error),
        .applied_duty(duty),.hard_inhibit(inhibit),.buzzer(buzzer),.red_on(red_on),.red_flash(red_flash),
        .active(active),.latched(latched),.alarm_level(level),.fan_action(fan_action),
        .mode(mode),.stable_run(stable_run),.active_config(cfg));
    wire pwm;
    always @(posedge clk) begin
        #2;
        if(rst_n && (dut.monitor_status[2*32+9 +:2] !== 2'b00 ||
                     (dut.monitor_status[31*32 +:32] & 32'h0000fffb) !== 0))
            $fatal(1,"Removed power-control status bits must stay zero");
    end

    pwm_out #(.CLK_FREQ(100_000_000),.PWM_HZ(20000),.ENABLE_INHIBIT(1)) u_pwm(
        .clk(clk),.rst_n(rst_n),.duty(duty),.inhibit(inhibit),.pwm(pwm));
    integer sample_count=0;
    always @(negedge clk) begin
        if(!rst_n)begin adc_new<=0;temp_new<=0;fg_new<=0;a_new<=0;b_new<=0;sample_count<=0;fg_pulses<=0;end
        else begin
            sample_count<=sample_count+1;
            adc_new<=adc_on && sample_count%100==0;
            temp_new<=temp_on && sample_count%1000==0;
            fg_new<=fg_on && sample_count%5000==0;
            if(fg_on && sample_count%5000==0)fg_pulses<=fg_pulses+1'b1;
            a_new<=icm_on && sample_count%100==0;b_new<=icm_on && sample_count%100==50;
        end
    end
    integer checks=0;
    task check;
        input good;input [639:0] name;
        begin checks=checks+1;if(good!==1'b1)$fatal(1,"FAIL %0s time=%0t mode=%0d level=%0d active=%h latch=%h duty=%0d",name,$time,mode,level,active,latched,duty);end
    endtask
    task wait_ms;input integer ms;begin repeat(ms*1000)@(posedge clk);#1;end endtask
    task bus;
        input wr;input [15:0] addr;input [31:0] data;input [7:0] expected;
        begin
            @(negedge clk);req=1;write_en=wr;address=addr;write_data=data;
            @(posedge clk);#1;check(response,"CSR response");check(error==expected,"CSR status");
            @(negedge clk);req=0;@(posedge clk);#1;
        end
    endtask
    reg [31:0] cid=0;
    task command;
        input [7:0] op;input [31:0] payload;input [7:0] expected;
        begin cid=cid+1;bus(1,16'hc,cid,0);bus(1,16'h10,payload,0);bus(1,16'h14,op,expected);end
    endtask
    task pulse_reset;
        input expected;
        begin @(negedge clk);local_reset=1;@(posedge clk);#1;
            check(dut.reset_accepted==expected,"Local reset permission");
            check(dut.reset_rejected==!expected,"Local reset refusal");
            @(negedge clk);local_reset=0;
        end
    endtask
    reg [31:0] words[0:23];
    integer i;
    task init_words;
        begin
            words[0]=31;words[1]=1;words[2]={16'd1400,16'd1800};words[3]={16'd900,16'd3000};
            words[4]={16'd4000,16'd500};words[5]={16'd7000,16'd500};words[6]={16'd64,16'd256};
            words[7]={16'd100,16'd0};words[8]={16'd50,16'd200};words[9]={16'd1120,16'd800};
            words[10]={16'd1000,16'd640};words[11]={8'd0,8'd2,16'd2000};
            words[12]={16'd300,16'd500};words[13]={16'd10,16'd5};words[14]={16'd3,16'd6};
            words[15]={16'd5,16'd8};words[16]={16'd10,16'd8};words[17]={16'd8,16'd10};
            words[18]={16'd3,16'd3};words[19]={16'd3,16'd3};words[20]={16'd5,16'd5};
            words[21]=128;words[22]=1000000;words[23]=9000;
        end
    endtask
    task stage_words;begin for(i=0;i<24;i=i+1)bus(1,16'h300+i*4,words[i],0);end endtask
    task boot;
        begin
            rst_n=0;req=0;adc_on=1;temp_on=1;fg_on=1;icm_on=1;adc_error=0;temp_present=1;temp_short=0;temp_stale=0;
            current_raw=20;pressure_raw=40;temp_raw=400;ax=20;bx=25;fg_period=5000;
            diagnostic_bad=0;auxiliary_bad=0;local_permit=1;local_reset=0;local_silence=0;manual_step=0;cid=0;
            repeat(5)@(negedge clk);rst_n=1;wait_ms(2);init_words;stage_words;bus(1,16'h18,32'h434f4d54,0);wait_ms(9);
            check(cfg[3:0]==15,"Qualified simulation config");check(level==0,"Healthy manual mode has no alarm");
        end
    endtask
    task alive;
        input integer ms;input renew_target;
        integer j;
        begin for(j=0;j<ms;j=j+1)begin command(3,0,0);if(renew_target)command(1,6000,0);wait_ms(1);end end
    endtask
    reg [31:0] old_age,old_seq,head_seq,summary;
    initial begin
        // Reset + commissioning prerequisites, including partial/invalid writes.
        repeat(5)@(negedge clk);rst_n=1;wait_ms(2);
        command(3,0,0);command(1,6000,2);
        bus(1,16'h300,15,0);bus(1,16'h18,32'h434f4d54,2);check(cfg[32 +:32]==0,"Partial config not committed");
        init_words;stage_words;local_permit=0;bus(1,16'h18,32'h434f4d54,3);local_permit=1;
        bus(1,16'h310,{16'd400,16'd500},0);bus(1,16'h18,32'h434f4d54,2);check(cfg[32 +:32]==0,"Invalid bounds keep active config");
        bus(1,16'h310,words[4],0);bus(1,16'h18,32'h434f4d54,0);wait_ms(9);
        command(3,0,0);command(1,6000,0);alive(3,1);
        bus(1,16'h300,0,0);bus(1,16'h18,32'h434f4d54,3);
        check(cfg[3:0]==15,"Maintenance cannot disable qualified protection while running");
        check(level==0 && !buzzer && !inhibit,"Normal PI is silent");check(fan_action==0,"Normal PI action");
        // Identical retry is idempotent; changing payload under that ID is rejected.
        old_age=dut.cmd_age;wait_ms(1);bus(1,16'h14,1,0);
        check(dut.cmd_age>old_age,"Duplicate target does not refresh lease");
        bus(1,16'h14,32'h00010001,1);
        check(dut.cmd_age>old_age,"Cached success does not accept reserved execution bits");
        bus(1,16'h10,6100,0);bus(1,16'h14,1,4);
        command(1,6000,0);alive(12,0);
        check(active[13] && fan_action==4 && duty==1400,"Heartbeat cannot renew expired target");
        command(1,6000,0);alive(2,1);wait_ms(12);
        check(active[12] && active[13] && level==2,"PS pause -> bounded fallback");
        current_raw=250;@(posedge adc_new);repeat(2)@(posedge clk);#1;
        check(latched[0] && inhibit && duty==0 && pwm==0,"Hard OC reaches PWM within two clocks, independent of PS");
        pulse_reset(0);
        // Expired local ownership must not block a later legitimate PS lease.
        boot;@(negedge clk);manual_step=1;@(negedge clk);manual_step=0;repeat(3)@(posedge clk);#1;
        command(3,0,0);command(1,6000,8);wait_ms(12);
        check(active[13] && fan_action==4,"Local manual ownership has a finite lease");
        command(3,0,0);command(1,6000,0);alive(3,1);
        check(!dut.manual_expired && !active[13] && fan_action==0,"Fresh PS handover clears expired manual ownership");
        // Heat keeps cooling; ACK and model 'normal' do not clear it.
        boot;temp_raw=1200;wait_ms(5);
        check(latched[3] && level==3 && !inhibit && duty==3000,"Severe heat boosts cooling and raises L3 alarm");
        command(3,0,0);command(2,0,3);
        check(latched[3] && duty==3000,"STOP cannot override a thermal latch");
        bus(0,16'h13c,0,0);old_seq=read_data;command(4,old_seq,0);
        check(latched[3] && buzzer,"ACK does not silence or unlatch");
        command(3,0,0);command(5,32'h00000100,0);check(level==3 && duty==3000,"Soft normal cannot override physical heat");
        pulse_reset(0);
        @(negedge clk);local_silence=1;@(posedge clk);@(negedge clk);local_silence=0;repeat(3)@(posedge clk);#1;
        check(!buzzer && red_on && latched[3],"Local silence leaves red light and latch");
        current_raw=250;repeat(110)@(posedge clk);#1;
        check(latched[0] && latched[3] && duty==0,"Compound heat/OC preserves both causes; electrical limit wins");
        check(buzzer,"New cause cancels silence");
        current_raw=20;temp_raw=400;wait_ms(12);pulse_reset(1);repeat(8)@(posedge clk);#1;
        check(latched==0,"Valid stable recovery permits LOCAL latch release");
        // Critical acquisition failure is not zero current or motor overcurrent.
        boot;adc_on=0;wait_ms(7);
        check(active[4] && latched[4] && level==3 && !inhibit && duty==1400,"Lost current protection -> qualified fallback and L3 alarm");
        pulse_reset(0);adc_on=1;wait_ms(8);pulse_reset(1);
        // DS bus fault is invalid, while a genuine zero-degree conversion works.
        boot;command(3,0,0);command(1,6000,0);alive(8,1);
        check(stable_run && mode==3,"Healthy automatic control is qualified stable RUN");
        temp_short=1;temp_on=0;temp_raw=0;wait_ms(2);
        check(active[5] && !dut.temp_valid && duty==1400 && level==2 && mode==8 && !stable_run,
            "Shorted DS18B20 cannot become valid zero C or a stable control mode");
        command(3,0,0);command(2,0,3);
        temp_short=0;temp_on=1;wait_ms(2);check(dut.temp_valid && !active[5],"Genuine zero C is valid");
        // Feedback loss alone does not claim a proven mechanical stall.
        boot;fg_on=0;wait_ms(10);
        check(active[6] && !latched[8] && !inhibit && duty==1400,"FG loss -> feedback fallback, no invented hard stall");
        current_raw=150;wait_ms(5);
        check(latched[8] && inhibit && !latched[0],"Sustained high current corroborates stall protection");
        // Qualified vibration versus saturated measurement.
        boot;ax=16'sh8000;wait_ms(1);
        check(active[14] && !latched[11] && level==1 && !buzzer,"Saturation is quality loss, not mechanical proof");
        ax=2200;wait_ms(1);check(latched[11] && inhibit,"Qualified hard vibration protection");
        boot;fg_period=2000;wait_ms(6);check(latched[9] && inhibit,"Trusted overspeed protection");
        // Ordinary diagnostic failures and soft model reports do not move PWM.
        boot;diagnostic_bad=1;wait_ms(1);check(level==1 && !buzzer && duty==2000,"ICM-only failure leaves control and stays silent");
        diagnostic_bad=0;command(3,0,0);command(5,32'h00420102,0);
        check(level==2 && !buzzer && duty==2000,"Model/soft L2 cannot drive fan or make physical sound");
        wait_ms(6);check(active[20] && level==1 && !buzzer,"Expired soft result becomes unavailable");
        command(9,0,3);command(10,0,3);check(latched==0,"Remote reset/silence opcodes rejected");
        // Authorized stop, quiet-time confirmation, and re-start prerequisites.
        boot;command(3,0,0);command(1,6000,0);
        local_permit=0;command(2,0,3);local_permit=1;
        command(6,1,3);command(6,0,3);command(6,2,3);
        command(2,0,0);fg_on=0;alive(6,0);
        command(2,0,0);alive(4,0);
        check(mode==1 && duty==0 && !active[6],"Authorized PWM stop needs no external power receipt");
        command(3,0,0);command(2,0,0);
        adc_on=0;wait_ms(6);check(!active[4] && level<=1,"Known off loses start qualification, not active hard protection");
        command(3,0,0);command(1,6000,5);
        // Repeated starts cannot extend the finite spinup deadline.
        boot;fg_on=0;wait_ms(10); // Already ran: restore reset then suppress feedback before grace.
        rst_n=0;repeat(5)@(negedge clk);rst_n=1;cid=0;fg_on=0;adc_on=1;temp_on=1;
        wait_ms(2);init_words;stage_words;bus(1,16'h18,32'h434f4d54,0);
        command(3,0,0);command(1,6000,0);
        alive(10,1);wait_ms(3);
        check(latched[7] && inhibit && mode==7,"Start deadline cannot be extended by repeated commands");
        // Event backpressure never blocks a protection decision; overflow visible.
        boot;
        for(i=0;i<15;i=i+1)begin diagnostic_bad=!diagnostic_bad;wait_ms(1);end
        check(dut.lost_events>0 && dut.q_count<=6,"L1 queue is bounded and leaves priority slots");
        current_raw=250;wait_ms(1);check(latched[0] && dut.q_count>6,"L3 event uses reserved capacity during L1 flood");
        bus(0,16'h080,0,0);head_seq=read_data;command(8,head_seq,0);
        bus(1,16'h14,8,0); // Duplicate pop cannot consume the next event.
        bus(0,16'h080,0,0);check(read_data!=head_seq,"Exactly one event popped");
        command(7,0,0);bus(0,16'h704,0,0);summary=read_data;wait_ms(2);
        bus(0,16'h704,0,0);check(read_data==summary,"Status snapshot remains coherent while live time advances");
        $display("ALL PASS tb_cooling_control checks=%0d",checks);$finish;
    end
    initial begin #20000000;$fatal(1,"TIMEOUT tb_cooling_control");end
endmodule
