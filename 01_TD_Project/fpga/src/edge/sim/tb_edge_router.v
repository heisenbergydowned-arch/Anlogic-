`timescale 1ns/1ps
module tb_edge_router;
    reg clk=0;always #5 clk=~clk;reg rst_n=0;
    reg [31:0] s_awaddr=0,s_wdata=0,s_araddr=0;
    reg [2:0] s_awprot=3,s_arprot=5;reg [3:0] s_wstrb=15;
    reg s_awvalid=0,s_wvalid=0,s_bready=0,s_arvalid=0,s_rready=0;
    wire s_awready,s_wready,s_bvalid,s_arready,s_rvalid;
    wire [1:0] s_bresp,s_rresp;wire [31:0] s_rdata;
    wire [31:0] p_awaddr,p_wdata,p_araddr;wire [2:0] p_awprot,p_arprot;wire [3:0] p_wstrb;
    wire p_awvalid,p_wvalid,p_bready,p_arvalid,p_rready;
    wire [15:0] e_awaddr,e_araddr;wire [31:0] e_wdata;wire [3:0] e_wstrb;
    wire e_awvalid,e_wvalid,e_bready,e_arvalid,e_rready;
    reg p_awready=0,p_wready=0,p_arready=0,e_awready=0,e_wready=0,e_arready=0;
    reg p_bvalid=0,p_rvalid=0,e_bvalid=0,e_rvalid=0;
    reg [31:0] p_rdata=0,e_rdata=0,p_addr=0,p_data=0,e_addr=0,e_data=0;
    reg pa=0,pw=0,ea=0,ew=0;integer p_writes=0,e_writes=0,p_reads=0,e_reads=0;
    edge_axil_router dut(.*,.p_bresp(2'd0),.p_rresp(2'd0),.e_bresp(2'd2),.e_rresp(2'd2));
    always @(posedge clk)if(rst_n)begin
        // Deliberately independent downstream address/data backpressure.
        p_awready<=!p_awready;e_wready<=!e_wready;
        p_wready<=1;e_awready<=1;p_arready<=1;e_arready<=1;
        if(p_awvalid&&p_awready)begin pa<=1;p_addr<=p_awaddr;if(p_awprot!=3)$fatal(1,"AWPROT lost");end
        if(p_wvalid&&p_wready)begin pw<=1;p_data<=p_wdata;if(p_wstrb!=15)$fatal(1,"WSTRB lost");end
        if(e_awvalid&&e_awready)begin ea<=1;e_addr<=e_awaddr;end
        if(e_wvalid&&e_wready)begin ew<=1;e_data<=e_wdata;end
        if(pa&&pw&&!p_bvalid)p_bvalid<=1;
        if(ea&&ew&&!e_bvalid)e_bvalid<=1;
        if(p_bvalid&&p_bready)begin p_bvalid<=0;pa<=0;pw<=0;p_writes<=p_writes+1;end
        if(e_bvalid&&e_bready)begin e_bvalid<=0;ea<=0;ew<=0;e_writes<=e_writes+1;end
        if(p_arvalid&&p_arready)begin p_rvalid<=1;p_rdata<=p_araddr^32'h55aa5500;p_reads<=p_reads+1;if(p_arprot!=5)$fatal(1,"ARPROT lost");end
        if(e_arvalid&&e_arready)begin e_rvalid<=1;e_rdata<={16'hcafe,e_araddr};e_reads<=e_reads+1;end
        if(p_rvalid&&p_rready)p_rvalid<=0;
        if(e_rvalid&&e_rready)e_rvalid<=0;
    end
    task aw;input [31:0] address;begin
        @(negedge clk);s_awaddr=address;s_awvalid=1;
        do @(posedge clk);while(!s_awready);
        @(negedge clk);s_awvalid=0;
    end endtask
    task wd;input [31:0] data;begin
        @(negedge clk);s_wdata=data;s_wvalid=1;
        do @(posedge clk);while(!s_wready);
        @(negedge clk);s_wvalid=0;
    end endtask
    task write;input [31:0] address,data;input integer order;reg [1:0] held;begin
        if(order==0)begin aw(address);repeat(3)@(negedge clk);wd(data);end
        else if(order==1)begin wd(data);repeat(3)@(negedge clk);aw(address);end
        else fork aw(address);wd(data);join
        wait(s_bvalid);held=s_bresp;
        repeat(7)begin @(negedge clk);if(!s_bvalid||s_bresp!=held||s_awready||s_wready)$fatal(1,"Write response backpressure");end
        if(held!=(address[31:16]==16'h8040 ? 2:0))$fatal(1,"B response route");
        if(address[31:16]==16'h8040)begin if(e_addr!=address[15:0]||e_data!=data)$fatal(1,"New page write");end
        else if(p_addr!=address||p_data!=data)$fatal(1,"Legacy write");
        s_bready=1;@(negedge clk);s_bready=0;
    end endtask
    task read;input [31:0] address;reg [31:0] held;begin
        @(negedge clk);s_araddr=address;s_arvalid=1;
        do @(posedge clk);while(!s_arready);
        @(negedge clk);s_arvalid=0;wait(s_rvalid);held=s_rdata;
        repeat(9)begin @(negedge clk);if(!s_rvalid||s_rdata!=held||s_arready)$fatal(1,"Read response backpressure");end
        if(held!=(address[31:16]==16'h8040 ? {16'hcafe,address[15:0]}:address^32'h55aa5500))$fatal(1,"Read route/data");
        if(s_rresp!=(address[31:16]==16'h8040 ? 2:0))$fatal(1,"R response route");
        s_rready=1;@(negedge clk);s_rready=0;
    end endtask
    initial begin
        repeat(5)@(negedge clk);rst_n=1;
        write(32'h80401234,32'habcdef01,1);write(32'h80200100,32'h10203040,0);
        fork read(32'h80401000);write(32'h80300200,32'h55667788,2);join
        fork read(32'h80300000);write(32'h8040fffc,32'h87654321,2);join
        read(32'h80410000);read(32'h803ffffc);
        if(p_writes!=2||e_writes!=2||p_reads!=3||e_reads!=1)$fatal(1,"Unexpected duplicate/misrouted transaction");
        $display("tb_edge_router ALL PASS AW/W ordering, old/new route, simultaneous read/write and backpressure");$finish;
    end
    initial begin #100000;$fatal(1,"TIMEOUT router");end
endmodule
