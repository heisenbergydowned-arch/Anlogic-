`timescale 1ns/1ps
module tb_control_edges;
    reg clk=0,rst_n=0;
    always #5 clk=~clk;
    reg enable=1,sample=0,valid=1,enter_cond=0,recover_cond=0;
    reg tick=0;
    reg [31:0] now_ms=0;
    wire active;
    fault_filter u_filter(.clk(clk),.rst_n(rst_n),.tick_ms(tick),.enable(enable),.sample(sample),.valid(valid),
        .enter_cond(enter_cond),.recover_cond(recover_cond),.now_ms(now_ms),.enter_ms(16'd10),.recover_ms(16'd8),.active(active));
    reg key1=1,key2=1;
    wire manual,silence,reset,permit;
    cooling_buttons #(.DEBOUNCE_MS(2),.HOLD_MS(4),.PERMIT_MS(8)) u_buttons(
        .clk(clk),.rst_n(rst_n),.tick_ms(tick),.key1_n(key1),.key2_n(key2),
        .manual_step(manual),.local_silence(silence),.local_reset(reset),.local_permit(permit));
    integer manual_count=0,silence_count=0,reset_count=0;
    always @(negedge clk)begin if(manual)manual_count=manual_count+1;if(silence)silence_count=silence_count+1;if(reset)reset_count=reset_count+1;end
    integer checks=0;
    task check;input ok;input [511:0] name;begin checks=checks+1;if(ok!==1'b1)$fatal(1,"FAIL %0s",name);end endtask
    task observation;input [31:0] t;begin @(negedge clk);now_ms=t;sample=1;@(posedge clk);#1;@(negedge clk);sample=0;end endtask
    task ms;input integer n;integer i;begin for(i=0;i<n;i=i+1)begin @(negedge clk);tick=1;now_ms=now_ms+1;@(posedge clk);@(negedge clk);tick=0;repeat(3)@(posedge clk);end #1;end endtask
    initial begin
        repeat(3)@(negedge clk);rst_n=1;
        enter_cond=1;observation(32'hfffffff8);check(!active,"First suspicious sample is a candidate");
        ms(12);check(!active,"Elapsed entry time alone is not another fresh observation");
        observation(32'h00000004);check(active,"Confirmation survives global uptime wrap");
        enter_cond=0;recover_cond=1;observation(5);ms(95);
        check(active,"Old held value does not provide another recovery observation");
        valid=0;observation(101);check(active,"Invalid data cannot clear a fault");
        valid=1;observation(102);check(active,"Recovery confirmation restarts after invalid data");
        ms(8);observation(110);check(!active,"Two fresh, stable recovery observations clear the cause");
        // Bouncing/held keys produce one action, and short/long functions differ.
        key1=0;ms(1);key1=1;ms(3);check(manual_count==0,"KEY1 bounce ignored");
        key1=0;ms(8);check(manual_count==1,"Held KEY1 steps once");key1=1;ms(3);
        key2=0;ms(3);key2=1;ms(4);check(silence_count==1 && reset_count==0,"KEY2 short is silence only");
        key2=0;ms(9);check(reset_count==1 && permit,"KEY2 hold grants local maintenance and one reset request");
        ms(2);check(reset_count==1,"Long key does not repeatedly reset");key2=1;ms(10);
        check(silence_count==1 && !permit,"Long release is not silence; maintenance lease expires");
        $display("ALL PASS tb_control_edges checks=%0d",checks);$finish;
    end
    initial begin #100000;$fatal(1,"TIMEOUT tb_control_edges");end
endmodule
