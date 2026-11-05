`timescale 1ns/1ps
module division_check #(parameter W=160)(output reg passed=0);
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,start=0;reg [W-1:0] numerator=0,denominator=0;
    wire busy,done,zero;wire [W-1:0] quotient;
    feature_udiv #(.WIDTH(W)) dut(clk,rst_n,start,numerator,denominator,busy,done,zero,quotient);
    reg [W-1:0] expected,previous,original_n,original_d;
    reg [31:0] seed=32'h703992a1;integer i,k,clocks;
    function [31:0] random_word;
        input [31:0] value;
        begin random_word=value^(value<<13);random_word=random_word^(random_word>>17);random_word=random_word^(random_word<<5);end
    endfunction
    initial begin
        repeat(3)@(negedge clk);rst_n=1;
        for(i=0;i<520;i=i+1)begin
            numerator=0;denominator=0;
            for(k=0;k<W;k=k+32)begin
                seed=random_word(seed);numerator=(numerator<<32)|seed;
                seed=random_word(seed);denominator=(denominator<<32)|seed;
            end
            case(i)
                0:begin numerator=0;denominator=0;end
                1:begin numerator={W{1'b1}};denominator=1;end
                2:begin numerator=0;denominator=1;end
                3:begin numerator={W{1'b1}};denominator={W{1'b1}};end
                4:begin numerator=1;denominator={W{1'b1}};end
                5:begin numerator=1;denominator=0;end
                6:begin numerator={W{1'b1}};denominator=({W{1'b1}}>>1)+1'b1;end
                7:begin numerator=({W{1'b1}}>>1);denominator=({W{1'b1}}>>1)+1'b1;end
            endcase
            original_n=numerator;original_d=denominator;
            expected=denominator==0 ? 0:numerator/denominator;
            previous=quotient;start=1;@(negedge clk);start=0;clocks=0;
            while(!done)begin
                if(!busy || quotient!==previous)$fatal(1,"W=%d busy/output stability",W);
                // Inputs and a redundant start while busy must be ignored.
                numerator=~numerator;denominator=~denominator;start=(clocks==3);
                @(negedge clk);start=0;clocks=clocks+1;
                if(clocks>W+1)$fatal(1,"W=%d timeout",W);
            end
            if(quotient!==expected || zero!==(original_d==0) || busy || clocks!=(original_d==0 ? 0:W))
                $fatal(1,"W=%d n=%h d=%h q=%h expected=%h cycles=%d",W,original_n,original_d,quotient,expected,clocks);
            previous=quotient;repeat(2)@(negedge clk);
            if(done || quotient!==previous)$fatal(1,"W=%d done/output hold",W);
        end
        numerator={W{1'b1}};denominator=3;start=1;@(negedge clk);start=0;
        rst_n=0;@(negedge clk);if(busy || done || quotient!==0)$fatal(1,"Reset did not abort W=%d",W);
        passed=1;$display("DIV equivalence PASS W=%0d vectors=520",W);
    end
endmodule
module tb_udiv_equivalence;
    wire [5:0] passed;
    division_check #(.W(1)) a(passed[0]);
    division_check #(.W(16)) b(passed[1]);
    division_check #(.W(64)) c(passed[2]);
    division_check #(.W(96)) d(passed[3]);
    division_check #(.W(160)) e(passed[4]);
    division_check #(.W(140)) f(passed[5]);
    initial begin wait(&passed);$display("DIV equivalence ALL PASS 3120 vectors/reset/busy/stability");$finish;end
    initial begin #10000000;$fatal(1,"Global division timeout");end
endmodule
