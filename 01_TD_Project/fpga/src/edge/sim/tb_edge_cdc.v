`timescale 1ns/1ps
module tb_edge_cdc;
    reg sclk=0,dclk=0;always #7 sclk=~sclk;always #5 dclk=~dclk;
    reg srst=0,drst=0,req=0,we=0;reg [15:0] addr=0;reg [31:0] wd=0;
    wire resp;wire [31:0] rd;wire [7:0] err;
    wire dreq,dwe;wire [15:0] da;wire [31:0] dw;reg dresp=0;reg [31:0] dout=0;reg [3:0] delay=0;
    integer delivered=0,i;reg pending=0;
    edge_csr_cdc dut(.s_clk(sclk),.s_rst_n(srst),.s_req(req),.s_write(we),.s_address(addr),.s_wdata(wd),.s_response(resp),.s_rdata(rd),.s_error(err),
        .d_clk(dclk),.d_rst_n(drst),.d_req(dreq),.d_write(dwe),.d_address(da),.d_wdata(dw),.d_response(dresp),.d_rdata(dout),.d_error(8'd0));
    always @(posedge dclk)begin
        dresp<=0;
        if(dreq)begin
            if(pending)$fatal(1,"Duplicate in-flight request");
            pending<=1;delay<=7;dout<=dw ^ {16'd0,da};delivered<=delivered+1;
        end
        if(pending && delay!=0)delay<=delay-1;
        if(pending && delay==0)begin dresp<=1;pending<=0;end
    end
    initial begin
        repeat(8)@(negedge sclk);srst=1;drst=1;
        for(i=0;i<80;i=i+1)begin
            @(negedge sclk);req=1;we=i%2;addr=i*4;wd=32'habc00000+i;
            @(negedge sclk);req=0;
            wait(resp);@(negedge sclk);
            if(err!=0 || rd!=(wd ^ {16'd0,addr}))$fatal(1,"CDC payload mismatch %d",i);
        end
        if(delivered!=80)$fatal(1,"CDC request count");
        $display("tb_edge_cdc ALL PASS 80 asynchronous transactions");$finish;
    end
    initial begin #1000000;$fatal(1,"TIMEOUT CDC");end
endmodule
