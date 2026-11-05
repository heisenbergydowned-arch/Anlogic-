`timescale 1ns/1ps
module tb_rpm_vectors;
    reg clk=0,rst_n=0;always #5 clk=~clk;
    reg changed=0,tick=0,new_period=0,timeout=0;
    reg [767:0] cfg=0;reg [31:0] period=0;
    wire [15:0] rpm;wire fresh,valid;wire [31:0] age,rejected;
    rpm_measure #(.CLK_FREQ(100_000_000)) dut(.clk(clk),.rst_n(rst_n),.cfg_changed(changed),.tick_ms(tick),.cfg(cfg),
        .period_count(period),.period_new(new_period),.fg_timeout(timeout),.rpm(rpm),.rpm_new(fresh),.valid(valid),.age_ms(age),.rejected_periods(rejected));
    integer observed=0;always @(posedge clk)if(fresh)observed=observed+1;
    reg [2047:0] input_file,output_file;
    integer fin,fout,rc,k=0,before_new;
    reg [31:0] p,minp,maxp;reg [7:0] ppr;
    initial begin
        if(!$value$plusargs("IN=%s",input_file)||!$value$plusargs("OUT=%s",output_file))$fatal(1,"Missing paths");
        fin=$fopen(input_file,"r");fout=$fopen(output_file,"w");if(!fin||!fout)$fatal(1,"File open");
        cfg[32 +:32]=1;cfg[14*32 +:16]=10;
        repeat(4)@(negedge clk);rst_n=1;
        while(!$feof(fin))begin
            rc=$fscanf(fin,"%h %h %h %h\n",p,ppr,minp,maxp);
            if(rc==4)begin
                @(negedge clk);changed=1;cfg[32 +:32]=k+2;cfg[11*32+16 +:8]=ppr;cfg[21*32 +:32]=minp;cfg[22*32 +:32]=maxp;
                @(negedge clk);changed=0;before_new=observed;period=p;new_period=1;
                @(negedge clk);new_period=0;repeat(75)@(posedge clk);#1;
                $fdisplay(fout,"%0d %0d %0d %0d",k,rpm,valid,observed-before_new);k=k+1;
            end else if(rc!=-1)$fatal(1,"Invalid vector");
        end
        timeout=1;repeat(2)@(posedge clk);#1;if(valid)$fatal(1,"Timeout accepted old RPM");timeout=0;
        cfg[14*32 +:16]=1;@(negedge clk);tick=1;repeat(2)@(posedge clk);@(negedge clk);tick=0;
        #1;if(valid)$fatal(1,"Stale RPM remained valid");
        // A config switch while division is in progress must discard its result.
        cfg[11*32+16 +:8]=2;cfg[21*32 +:32]=128;cfg[22*32 +:32]=10000000;
        @(negedge clk);new_period=1;period=500000;@(negedge clk);new_period=0;
        repeat(5)@(negedge clk);changed=1;@(negedge clk);changed=0;before_new=observed;
        repeat(75)@(posedge clk);#1;if(valid || observed!=before_new)$fatal(1,"Old config conversion escaped");
        $fclose(fin);$fclose(fout);$display("ALL PASS tb_rpm_vectors vectors=%0d",k);$finish;
    end
    initial begin #2000000;$fatal(1,"TIMEOUT tb_rpm_vectors");end
endmodule
