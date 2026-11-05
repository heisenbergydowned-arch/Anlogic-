`timescale 1ns/1ps
module tb_math;
    localparam CASES=40;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,div_start=0,root_start=0;
    reg [159:0] numerator=0,denominator=0;reg [63:0] radicand=0;
    wire div_busy,div_done,div_zero,root_busy,root_done;
    wire [159:0] quotient;wire [31:0] root;
    feature_udiv #(.WIDTH(160)) divider(.clk(clk),.rst_n(rst_n),.start(div_start),.numerator(numerator),
        .denominator(denominator),.busy(div_busy),.done(div_done),.div_zero(div_zero),.quotient(quotient));
    feature_isqrt square_root(.clk(clk),.rst_n(rst_n),.start(root_start),.radicand(radicand),
        .busy(root_busy),.done(root_done),.root(root));
    reg signed [31:0] q16;wire [31:0] fp32;
    feature_q16_float convert(.*);
    reg [159:0] dividends[0:CASES-1],divisors[0:CASES-1];
    reg [63:0] radicands[0:CASES-1];reg [31:0] fixeds[0:CASES-1];
    reg [1023:0] n_path,d_path,r_path,q_path,output_path;
    integer fd,c,cycle=0;reg [31:0] saved_root;
    always @(posedge clk) begin cycle=cycle+1;if(cycle>8000)$fatal(1,"Math timeout");end
    initial begin
        if (!$value$plusargs("NUM=%s",n_path) || !$value$plusargs("DEN=%s",d_path) ||
            !$value$plusargs("RAD=%s",r_path) || !$value$plusargs("FIX=%s",q_path) ||
            !$value$plusargs("OUT=%s",output_path)) $fatal(1,"Missing paths");
        $readmemh(n_path,dividends);$readmemh(d_path,divisors);$readmemh(r_path,radicands);$readmemh(q_path,fixeds);
        fd=$fopen(output_path,"w");if(!fd)$fatal(1,"Output open failed");
        repeat(4)@(negedge clk);rst_n=1;@(negedge clk);
        for(c=0;c<CASES;c=c+1)begin
            numerator=dividends[c];denominator=divisors[c];radicand=radicands[c];q16=fixeds[c];
            div_start=1;root_start=1;@(negedge clk);div_start=0;root_start=0;
            while(!root_done)@(negedge clk);saved_root=root;
            // div_zero can complete before sqrt: quotient and flag stay latched.
            while(div_busy)@(negedge clk);
            $fdisplay(fd,"%0d %040h %0d %0d %08h",c,quotient,saved_root,div_zero,fp32);
            @(negedge clk);
        end
        $fclose(fd);$display("PASS integer math: %0d vectors",CASES);$finish;
    end
endmodule
