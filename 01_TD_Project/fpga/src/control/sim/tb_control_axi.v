`timescale 1ns/1ps
module tb_control_axi;
    reg clk=0,rst_n=0;always #5 clk=~clk;
    reg [15:0] awaddr=0,araddr=0;reg awvalid=0,arvalid=0,wvalid=0,bready=0,rready=0;
    reg [31:0] wdata=0;reg [3:0] wstrb=15;
    wire awready,arready,wready,bvalid,rvalid;wire [1:0] bresp,rresp;wire [31:0] rdata;
    wire req,wr;wire [15:0] addr;wire [31:0] wd;
    reg response=0;reg [31:0] rd=0;reg [7:0] error=0;
    reg [31:0] memory[0:15];integer writes=0,checks=0,i;
    cooling_axi_lite dut(.clk(clk),.rst_n(rst_n),.awaddr(awaddr),.awvalid(awvalid),.awready(awready),
        .wdata(wdata),.wstrb(wstrb),.wvalid(wvalid),.wready(wready),.bresp(bresp),.bvalid(bvalid),.bready(bready),
        .araddr(araddr),.arvalid(arvalid),.arready(arready),.rdata(rdata),.rresp(rresp),.rvalid(rvalid),.rready(rready),
        .req(req),.write_en(wr),.address(addr),.write_data(wd),.response(response),.read_data(rd),.error(error));
    always @(posedge clk)begin
        response<=rst_n && req;
        if(rst_n && req)begin
            error<=addr[1:0]!=0 ? 1:0;
            if(wr && addr[1:0]==0)begin memory[addr[5:2]]<=wd;writes<=writes+1;end
            rd<=memory[addr[5:2]];
        end
    end
    task check;input ok;input [511:0] name;begin checks=checks+1;if(ok!==1'b1)$fatal(1,"FAIL %0s",name);end endtask
    task aw;input [15:0] a;begin @(negedge clk);awaddr=a;awvalid=1;do @(posedge clk);while(!awready);@(negedge clk);awvalid=0;end endtask
    task wd_send;input [31:0] d;input [3:0] s;begin @(negedge clk);wdata=d;wstrb=s;wvalid=1;do @(posedge clk);while(!wready);@(negedge clk);wvalid=0;end endtask
    task write_reply;input [1:0] expected;integer k;begin
        wait(bvalid);#1;check(bresp==expected,"Write response");
        for(k=0;k<12;k=k+1)begin @(posedge clk);#1;check(bvalid && bresp==expected,"BVALID survives backpressure");end
        @(negedge clk);bready=1;@(posedge clk);@(negedge clk);bready=0;
    end endtask
    task read;
        input [15:0] a;input [31:0] expected;input [1:0] expected_error;integer k;
        begin @(negedge clk);araddr=a;arvalid=1;do @(posedge clk);while(!arready);@(negedge clk);arvalid=0;
            wait(rvalid);#1;check(rdata==expected && rresp==expected_error,"Read value/response");
            for(k=0;k<10;k=k+1)begin @(posedge clk);#1;check(rvalid && rdata==expected && rresp==expected_error,"RVALID and data survive backpressure");end
            @(negedge clk);rready=1;@(posedge clk);@(negedge clk);rready=0;
        end
    endtask
    initial begin
        for(i=0;i<16;i=i+1)memory[i]=0;repeat(4)@(negedge clk);rst_n=1;
        aw(4);repeat(5)@(posedge clk);check(writes==0,"AW alone does not write");wd_send(32'h12345678,15);write_reply(0);read(4,32'h12345678,0);
        wd_send(32'habcd9876,15);repeat(5)@(posedge clk);check(writes==1,"W alone does not write");aw(8);write_reply(0);read(8,32'habcd9876,0);
        fork aw(12);wd_send(32'hfeedbeef,15);join write_reply(0);read(12,32'hfeedbeef,0);
        fork aw(4);wd_send(32'hffffffff,3);join write_reply(2);check(writes==3,"Partial configuration write refused");read(4,32'h12345678,0);
        read(5,32'h12345678,2);
        // A stalled read reply does not corrupt a concurrent write.
        fork read(8,32'habcd9876,0);begin aw(16);wd_send(32'h10203040,15);write_reply(0);end join
        read(16,32'h10203040,0);
        aw(20);rst_n=0;repeat(3)@(negedge clk);rst_n=1;repeat(5)@(posedge clk);#1;
        check(!bvalid && !rvalid && writes==4,"Reset drops partial transaction without a ghost write");
        $display("ALL PASS tb_control_axi checks=%0d",checks);$finish;
    end
    initial begin #100000;$fatal(1,"TIMEOUT tb_control_axi");end
endmodule
