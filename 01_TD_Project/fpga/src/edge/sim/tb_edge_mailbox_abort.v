`timescale 1ns/1ps
module tb_edge_mailbox_abort;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,inv=0,abort_frame=0,req=0,we=0,busy=0,permit=1;
    reg [5:0] idx=0;reg [31:0] fp=0,wd=0;reg [1023:0] header=0;reg [15:0] addr=0;
    wire response,available,changed;wire [31:0] rd,dropped;wire [7:0] err;wire [543:0] cfg;
    edge_mailbox dut(.clk(clk),.rst_n(rst_n),.engine_busy(busy),.local_permit(permit),.initial_config_permit(1'b0),
        .in_valid(inv),.in_abort(abort_frame),.in_index(idx),.in_fp32(fp),.in_header(header),
        .req(req),.write_en(we),.address(addr),.wdata(wd),.response(response),.rdata(rd),.error(err),
        .config_words(cfg),.config_changed(changed),.frame_available(available),.dropped(dropped));
    integer checks=0,j;reg [31:0] value;reg [7:0] error;
    task access;input write;input [15:0] address;input [31:0] data;begin
        @(negedge clk);req=1;we=write;addr=address;wd=data;
        @(negedge clk);req=0;value=rd;error=err;checks=checks+1;
        if(!response)$fatal(1,"Mailbox CSR response missing");
    end endtask
    task send;input [5:0] index;input [31:0] id;begin
        @(negedge clk);inv=1;idx=index;fp=id*100+index;header[96+:32]=id;
        @(negedge clk);inv=0;
    end endtask
    task frame;input [31:0] id;begin for(j=0;j<39;j=j+1)send(j,id);end endtask
    task stop_partial;begin
        @(negedge clk);abort_frame=1;busy=0;
        @(negedge clk);abort_frame=0;
    end endtask
    task configuration;input [31:0] id;integer k;reg [31:0] word;begin
        for(k=0;k<17;k=k+1)begin
            word=k==0 ? id : k==1 || k==2 ? 0 : k==7 ? 2 : k<8 ? 1 : k==8 ? 1 : k==16 ? 513 : (k-8)*32;
            access(1,16'h1300+4*k,word);
        end
        access(1,16'h1040,32'h45434d54);
        if(error!=0 || cfg[0+:32]!=id)$fatal(1,"Aborted feature frame blocks legal reconfiguration: error=%d",error);
    end endtask
    initial begin
        repeat(4)@(negedge clk);rst_n=1;
        frame(7); // Published slot must survive abort of the other slot.
        busy=1;send(0,8);send(1,8);stop_partial();
        configuration(2);
        if(dropped!=1)$fatal(1,"Partial abort must count once");
        access(0,16'h1010,0);if(value!=7)$fatal(1,"Abort changed committed head");
        for(j=0;j<39;j=j+1)begin
            access(0,16'h1200+4*j,0);if(error || value!=700+j)$fatal(1,"Abort corrupted committed data");
        end
        access(1,16'h1010,7);if(available)$fatal(1,"Partial aborted frame became visible");
        // A repeated abort with no building frame is harmless.
        stop_partial();if(dropped!=1)$fatal(1,"Duplicate abort double-counted");
        // Abort on the potential final index must suppress publish and RAM writes.
        busy=1;for(j=0;j<38;j=j+1)send(j,9);
        @(negedge clk);inv=1;idx=38;abort_frame=1;busy=0;
        @(negedge clk);inv=0;abort_frame=0;
        if(available || dropped!=2)$fatal(1,"Simultaneous abort/index38 published a frame");
        // index0 resynchronization must account for an abandoned partial frame.
        send(0,10);send(1,10);frame(11);
        if(dropped!=3)$fatal(1,"Restart silently lost a partial frame");
        access(0,16'h1010,0);if(value!=11)$fatal(1,"Resynchronized frame not published");
        // ACK of an old slot can coincide with cancellation of the next slot.
        send(0,12);
        @(negedge clk);req=1;we=1;addr=16'h1010;wd=11;abort_frame=1;
        @(negedge clk);req=0;abort_frame=0;
        if(!response || err || available || dropped!=4)$fatal(1,"Abort+ACK count/head broken");
        frame(13);access(0,16'h1010,0);if(value!=13)$fatal(1,"Mailbox did not recover after abort+ACK");
        configuration(3);
        $display("tb_edge_mailbox_abort ALL PASS %0d CSR checks",checks);$finish;
    end
    initial begin #1000000;$fatal(1,"TIMEOUT mailbox abort");end
endmodule
