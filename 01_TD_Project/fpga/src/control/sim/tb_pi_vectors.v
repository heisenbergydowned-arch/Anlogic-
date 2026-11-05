`timescale 1ns/1ps
module tb_pi_vectors;
    reg clk=0,rst_n=0;always #5 clk=~clk;
    reg enabled=0,step=0,fresh=0;reg [15:0] target=0,rpm=0,applied=0,dmin=0,dmax=0,kp=0,ki=0;
    wire [15:0] duty;wire saturated;
    rpm_pi dut(.clk(clk),.rst_n(rst_n),.enable(enabled),.step(step),.target_rpm(target),.rpm(rpm),.applied_duty(applied),
        .duty_min(dmin),.duty_max(dmax),.kp_q8(kp),.ki_q8(ki),.rpm_new(fresh),.rpm_valid(1'b1),.duty(duty),.saturated(saturated));
    reg [2047:0] input_file,output_file;
    integer fin,fout,rc,k=0;integer en,nf,t,r,a,lo,hi,p,i;
    initial begin
        if(!$value$plusargs("IN=%s",input_file)||!$value$plusargs("OUT=%s",output_file))$fatal(1,"Missing paths");
        fin=$fopen(input_file,"r");fout=$fopen(output_file,"w");if(!fin||!fout)$fatal(1,"File open");
        repeat(4)@(negedge clk);rst_n=1;
        while(!$feof(fin))begin
            rc=$fscanf(fin,"%d %d %d %d %d %d %d %d %d\n",en,nf,t,r,a,lo,hi,p,i);
            if(rc==9)begin
                @(negedge clk);enabled=en;target=t;rpm=r;applied=a;dmin=lo;dmax=hi;kp=p;ki=i;fresh=nf;
                @(negedge clk);fresh=0;repeat(2)@(negedge clk);step=1;
                @(negedge clk);step=0;repeat(5)@(posedge clk);#1;
                $fdisplay(fout,"%0d %0d %0d",k,duty,saturated);k=k+1;
            end else if(rc!=-1)$fatal(1,"Invalid vector");
        end
        $fclose(fin);$fclose(fout);$display("ALL PASS tb_pi_vectors vectors=%0d",k);$finish;
    end
    initial begin #2000000;$fatal(1,"TIMEOUT tb_pi_vectors");end
endmodule
