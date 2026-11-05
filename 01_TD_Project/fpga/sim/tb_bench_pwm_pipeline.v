`timescale 1ns/1ps
// Actual BNC ABI2 guard plus pipelined PWM in the unqualified, idle-owner profile.
module tb_bench_pwm_pipeline;
    reg clk=0,rst_n=1,tick_ms=0,local_permit=0,idle_allowed=1;
    reg adc_valid=1,temp_valid=1,fg_new=0;
    reg signed [15:0] current_raw=100,temp_raw=320;
    reg [31:0] fg_period=1000;
    reg req=0,write_en=1;
    reg [7:0] address=0;
    reg [31:0] write_data=0;
    wire response,driving,armed,tripped,pwm;
    wire [31:0] read_data;
    wire [7:0] error;
    wire [15:0] duty;
    integer kind,checks=0,i;
    always #5 clk=~clk;
    commission_bench bench(.clk(clk),.rst_n(rst_n),.tick_ms(tick_ms),.local_permit(local_permit),.idle_allowed(idle_allowed),
        .adc_valid(adc_valid),.temp_valid(temp_valid),.fg_new(fg_new),.current_raw(current_raw),.temp_raw(temp_raw),.fg_period(fg_period),
        .req(req),.write_en(write_en),.address(address),.write_data(write_data),.response(response),.read_data(read_data),.error(error),
        .driving(driving),.duty(duty),.armed(armed),.tripped(tripped));
    // In production BNC ABI2 can run only with !configured, so unqualified_hold
    // is true and cooling_control's hard_inhibit reduces to !bench_driving.
    pwm_out #(.ENABLE_INHIBIT(1),.PIPELINE_DUTY(1)) output_stage(
        .clk(clk),.rst_n(rst_n),.duty(duty),.inhibit(!driving),.pwm(pwm));
    always @(posedge clk) if(rst_n && !driving) begin
        #1;if(pwm!==0) $fatal(1,"Bench revoke did not cut PWM at next edge");checks=checks+1;
    end
    task write_register;
        input [7:0] a;input [31:0] v;
        begin
            @(negedge clk);address=a;write_data=v;req=1;
            @(posedge clk);#2;if(!response || error) $fatal(1,"BNC ABI2 write rejected address=%x error=%x",a,error);
            @(negedge clk);req=0;
        end
    endtask
    task start_trial;
        input integer duration;
        begin
            @(negedge clk);rst_n=0;tick_ms=0;idle_allowed=1;adc_valid=1;temp_valid=1;
            current_raw=100;temp_raw=320;fg_new=0;fg_period=1000;req=0;
            @(negedge clk);rst_n=1;
            write_register('h10,4000);write_register('h14,100);write_register('h18,50);
            write_register('h1c,1120);write_register('h20,128);write_register('h24,duration);
            write_register('h28,32'h41524d32);write_register('h2c,4000);
            repeat(3) begin @(posedge clk);#2;end
            if(!driving || pwm!==1) $fatal(1,"Trial did not drive full duty");
        end
    endtask
    initial begin
        #2;rst_n=0;
        for(kind=0;kind<9;kind=kind+1) begin
            start_trial(kind==8 ? 5:30000);
            if(kind>=7) begin
                @(negedge clk);tick_ms=1;
                for(i=0;i<(kind==7 ? 500:5);i=i+1) begin @(posedge clk);#2;end
                if(driving) $fatal(1,"Lease/duration expiry did not revoke");
            end else begin
                @(negedge clk);#2;
                case(kind)
                    0:current_raw=150; // Exactly positive trip boundary.
                    1:current_raw=50;  // Exactly negative trip boundary.
                    2:temp_raw=1120;
                    3:adc_valid=0;
                    4:temp_valid=0;
                    5:begin fg_new=1;fg_period=127;end
                    6:idle_allowed=0;
                endcase
                #0.1;if(driving) $fatal(1,"Health predicate failed to revoke");
            end
            @(posedge clk);#2;
            if(pwm!==0) $fatal(1,"Immediate PWM inhibit failed kind=%0d",kind);
            if(kind<6)begin
                if(!armed || tripped)$fatal(1,"Transient health fault prematurely latched");
                @(negedge clk);tick_ms=1;
                repeat(11)begin @(posedge clk);#2;end
                @(negedge clk);tick_ms=0;
            end
            if(armed || !tripped) $fatal(1,"Confirmed/immediate fault handling failed kind=%0d",kind);
            @(negedge clk);tick_ms=0;idle_allowed=1;adc_valid=1;temp_valid=1;current_raw=100;temp_raw=320;fg_new=0;
            repeat(3) begin @(posedge clk);#2;if(pwm!==0 || driving) $fatal(1,"Fault clear revived a stale command");end
        end
        start_trial(30000);write_register('h30,0);
        @(posedge clk);#2;if(pwm!==0 || driving || armed) $fatal(1,"Explicit stop failed");
        $display("tb_bench_pwm_pipeline: ALL PASS checks=%0d; +/-current boundary, temperature, sensor validity, overspeed, owner revoke, lease/duration expiry and explicit stop; current inhibit next-edge priority",checks);
        $finish;
    end
    initial begin #100000;$fatal(1,"tb_bench_pwm_pipeline TIMEOUT");end
endmodule
