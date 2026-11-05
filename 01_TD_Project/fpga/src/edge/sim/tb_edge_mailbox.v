`timescale 1ns/1ps
module tb_edge_mailbox;
    reg clk=0;always #5 clk=~clk;reg rst_n=0;
    reg inv=0;reg [5:0] idx=0;reg [31:0] fp=0;reg [1023:0] header=0;
    reg req=0,we=0,permit=0,busy=0;reg [15:0] addr=0;reg [31:0] wd=0;
    wire response,available,changed;wire [31:0] rd,dropped;wire [7:0] error;wire [543:0] cfg;
    edge_mailbox dut(.clk(clk),.rst_n(rst_n),.engine_busy(busy),.local_permit(permit),.initial_config_permit(1'b0),
        .in_valid(inv),.in_abort(1'b0),.in_index(idx),.in_fp32(fp),.in_header(header),.req(req),.write_en(we),.address(addr),.wdata(wd),
        .response(response),.rdata(rd),.error(error),.config_words(cfg),.config_changed(changed),.frame_available(available),.dropped(dropped));
    integer i,checks=0;reg [31:0] value;reg [7:0] got_error;
    task access;input write;input [15:0] address;input [31:0] data;begin
        @(negedge clk);req=1;we=write;addr=address;wd=data;
        @(negedge clk);req=0;value=rd;got_error=error;
        if(!response)$fatal(1,"Missing CSR response");checks=checks+1;
    end endtask
    task frame;input [31:0] id;integer j;begin
        @(negedge clk);for(j=0;j<32;j=j+1)header[j*32+:32]=id*1000+j;header[96+:32]=id;
        for(j=0;j<39;j=j+1)begin inv=1;idx=j;fp=id*100+j;@(negedge clk);header=~header;end
        inv=0;repeat(2)@(negedge clk);
    end endtask
    initial begin
        repeat(8)@(negedge clk);rst_n=1;
        frame(1);
        fork
            frame(2);
            begin
                for(i=0;i<39;i=i+1)begin
                    access(0,16'h1200+i*4,0);
                    if(value!=100+i || got_error!=0)$fatal(1,"Concurrent writer changed frozen reader slot");
                end
            end
        join
        frame(3);
        if(dropped!=1)$fatal(1,"Full mailbox did not drop exactly one new frame");
        access(0,16'h1010,0);if(value!=1)$fatal(1,"Head overwritten");
        for(i=0;i<32;i=i+1)begin
            access(0,16'h1100+i*4,0);
            if(value!=(i==3 ? 1:1000+i))$fatal(1,"Header snapshot changed/serialized incorrectly at %d",i);
        end
        // Adjacent requests alternate RAM/register/error responses without
        // waiting: response/data/error must still describe the same request.
        @(negedge clk);req=1;we=0;addr=16'h1200;
        @(negedge clk);if(!response || rd!=100 || error!=0)$fatal(1,"Back-to-back RAM response");addr=16'h1000;
        @(negedge clk);if(!response || rd!=32'h45444731 || error!=0)$fatal(1,"RAM select leaked into register response");addr=16'h110c;
        @(negedge clk);if(!response || rd!=1 || error!=0)$fatal(1,"Back-to-back header response");addr=16'h1201;
        @(negedge clk);if(!response || error!=1)$fatal(1,"Misaligned RAM access accepted");req=0;
        for(i=0;i<39;i=i+1)begin access(0,16'h1200+i*4,0);if(value!=100+i)$fatal(1,"Mixed/overwritten frame");end
        access(1,16'h1010,9);if(got_error!=4)$fatal(1,"Wrong ACK accepted");
        access(1,16'h1010,1);if(got_error!=0)$fatal(1,"ACK failed");
        access(1,16'h1010,1);if(got_error!=0)$fatal(1,"Duplicate ACK failed");
        access(0,16'h1010,0);if(value!=2)$fatal(1,"Duplicate ACK popped next head");
        for(i=0;i<32;i=i+1)begin
            access(0,16'h1100+i*4,0);
            if(value!=(i==3 ? 2:2000+i))$fatal(1,"Second header slot changed at %d",i);
        end
        access(1,16'h1040,32'h45434d54);if(got_error!=3)$fatal(1,"Missing local permission accepted");
        permit=1;access(1,16'h1040,32'h45434d54);if(got_error!=2)$fatal(1,"Partial config accepted");
        for(i=0;i<17;i=i+1)begin
            access(1,16'h1300+i*4,i==0 ? 2:i==2 ? 0:i==1 ? 0:i==7 ? 2:i<8 ? 1:i==8 ? 1:i==16 ? 513:(i-8)*32);
        end
        busy=1;access(1,16'h1040,32'h45434d54);if(got_error!=5)$fatal(1,"Running config switch accepted");
        busy=0;access(1,16'h1040,32'h45434d54);if(got_error!=0 || cfg[0+:32]!=2)$fatal(1,"Atomic config commit failed");
        access(1,16'h1050,1234);if(got_error!=0)$fatal(1,"Boot cookie initialization failed");
        access(1,16'h1050,4321);if(got_error!=4)$fatal(1,"Boot cookie overwritten");
        access(1,16'h1010,2);if(available)$fatal(1,"Released mailbox not empty");
        $display("tb_edge_mailbox ALL PASS %d operations",checks);$finish;
    end
    initial begin #1000000;$fatal(1,"TIMEOUT mailbox");end
endmodule
