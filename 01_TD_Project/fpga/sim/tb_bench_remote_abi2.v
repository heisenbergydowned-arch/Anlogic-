`timescale 1ns/1ps
module tb_bench_remote_abi2;
 reg clk=0,rst_n=0,tick_ms=0,local_permit=0,idle_allowed=1;
 reg adc_valid=1,temp_valid=1,fg_new=0;
 reg signed [15:0] current_raw=100,temp_raw=320;
 reg [31:0] fg_period=1000;
 reg req=0,write_en=0;reg [7:0] address=0;reg [31:0] write_data=0;
 wire response,driving,armed,tripped;wire [31:0] read_data;wire [7:0] error;wire [15:0] duty;
 integer checks=0,i,j;
 always #5 clk=~clk;
 commission_bench dut(.*);
 task check;input ok;input [799:0] label;
 begin checks=checks+1;if(ok!==1'b1)$fatal(1,"%0s",label);end endtask
 task reset;
 begin @(negedge clk);rst_n=0;req=0;tick_ms=0;idle_allowed=1;local_permit=0;
 adc_valid=1;temp_valid=1;current_raw=100;temp_raw=320;fg_new=0;fg_period=1000;
 repeat(2)@(negedge clk);rst_n=1;@(posedge clk);#2;end endtask
 task bus;input wr;input [7:0] a;input [31:0] v;input [7:0] e;
 begin @(negedge clk);req=1;write_en=wr;address=a;write_data=v;
 @(posedge clk);#2;check(response,"response");check(error==e,"operation error code");
 @(negedge clk);req=0;end endtask
 task limits;input [31:0] duration;
 begin bus(1,'h10,800,0);bus(1,'h14,100,0);bus(1,'h18,50,0);
 bus(1,'h1c,1120,0);bus(1,'h20,128,0);bus(1,'h24,duration,0);end endtask
 task arm;begin bus(1,'h28,32'h41524d32,0);check(armed&&driving&&duty==0,"remote ARM2 begins at zero");end endtask
 task tick;input integer count;
 begin @(negedge clk);tick_ms=1;repeat(count)begin @(posedge clk);#2;end
 @(negedge clk);tick_ms=0;end endtask
 task stopped;begin check(!armed&&!driving&&duty==0,"fault/stop output remains zero");end endtask
 initial begin
 reset;bus(0,'h00,0,0);check(read_data==32'h424e4331,"block identity");
 bus(0,'h04,0,0);check(read_data==32'h00020000,"ABI2 exact");
 bus(1,'h28,32'h41524d32,3);stopped;
 // All six words must be freshly installed after reset/STOP/trip.
 for(i=0;i<6;i=i+1)begin
  reset;for(j=0;j<6;j=j+1)if(j!=i)begin
   case(j)
    0:bus(1,'h10,800,0);1:bus(1,'h14,100,0);2:bus(1,'h18,50,0);
    3:bus(1,'h1c,1120,0);4:bus(1,'h20,128,0);5:bus(1,'h24,30000,0);
   endcase
  end
  bus(1,'h28,32'h41524d32,3);stopped;
 end
 reset;limits(30000);bus(1,'h28,32'h41524d31,1);stopped;
 arm;check(!local_permit,"no physical permit generated");
 bus(1,'h10,4000,3);bus(1,'h28,32'h41524d32,3);
 bus(1,'h2c,801,3);check(duty==0,"over max command rejected");
 bus(1,'h2c,800,0);check(duty==800,"legal remote duty");
 bus(1,'h30,1,1);check(armed,"malformed STOP is not opcode");
 bus(1,'h30,0,0);stopped;bus(1,'h28,32'h41524d32,3);stopped;
 // Missing health or production/hard-fault ownership blocks fresh ARM.
 for(i=0;i<7;i=i+1)begin
  reset;limits(30000);@(negedge clk);
  case(i)
   0:idle_allowed=0;1:adc_valid=0;2:temp_valid=0;3:current_raw=150;
   4:current_raw=50;5:temp_raw=1120;6:begin fg_new=1;fg_period=127;end
  endcase
  if(i==0)bus(1,'h10,800,3);
  bus(1,'h28,32'h41524d32,3);stopped;
 end
 // Every limit has an actual enforced invalid boundary.
 for(i=0;i<10;i=i+1)begin
  reset;limits(30000);
  case(i)
   0:bus(1,'h10,0,0);1:bus(1,'h10,4001,0);2:bus(1,'h14,65536,0);
   3:bus(1,'h18,0,0);4:bus(1,'h18,65536,0);5:bus(1,'h1c,2001,0);
   6:bus(1,'h1c,16'hfc8f,0);7:bus(1,'h20,127,0);
   8:bus(1,'h24,0,0);9:bus(1,'h24,30001,0);
  endcase
  bus(1,'h28,32'h41524d32,3);stopped;
 end
 // Lease boundary wins over commands received at/after expiry.
 reset;limits(30000);arm;bus(1,'h2c,800,0);tick(500);
 check(!driving,"lease boundary combinational revoke");
 bus(1,'h2c,800,3);stopped;check(tripped,"lease trip latched");
 bus(1,'h28,32'h41524d32,3);stopped;
 // Renewals may refresh lease but never the absolute deadline.
 reset;limits(30000);arm;bus(1,'h2c,800,0);
 for(i=0;i<299;i=i+1)begin tick(100);bus(1,'h2c,800,0);end
 tick(100);check(!driving,"30 second absolute deadline despite heartbeat");
 bus(1,'h2c,800,3);stopped;check(tripped,"absolute deadline trip");
 bus(1,'h28,32'h41524d32,3);stopped;
 // Raw faults immediately inhibit PWM; renewed authorization cannot bypass health.
 reset;limits(30000);arm;bus(1,'h2c,800,0);
 @(negedge clk);current_raw=150;req=1;write_en=1;address='h2c;write_data=800;
 @(posedge clk);#2;check(error==0 && !driving && duty==0 && armed,"heartbeat never bypasses instantaneous inhibit");
 @(negedge clk);req=0;tick(11);stopped;check(tripped,"continuous bad health latched");
 @(negedge clk);current_raw=100;
 bus(1,'h28,32'h41524d32,3);stopped;
 // A fresh bench profile may recover only its own trip, never idle/hard-fault exclusion.
 limits(30000);idle_allowed=0;bus(1,'h28,32'h41524d32,3);stopped;
 idle_allowed=1;arm;bus(1,'h2c,800,0);reset;stopped;
 $display("tb_bench_remote_abi2: ALL PASS checks=%0d; ABI2, ARM1 reject, no KEY, limits, health, owners, non-revival, lease and absolute duration",checks);$finish;
 end
 initial begin #2000000;$fatal(1,"TIMEOUT");end
endmodule
