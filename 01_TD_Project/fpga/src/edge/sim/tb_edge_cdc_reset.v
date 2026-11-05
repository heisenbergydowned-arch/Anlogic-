`timescale 1ns/1ps
module tb_edge_cdc_reset;
    reg sc=0,dc=0;always #7 sc=~sc;always #5 dc=~dc;
    reg sr=0,dr=0,req=0,we=0;reg [31:0] wd=0;reg [15:0] addr=0;
    wire response,dreq,dwe;wire [31:0] rd,dw;wire [15:0] da;wire [7:0] error;
    reg dresp=0,pending=0;reg [31:0] data=0;integer delay=0,delivered=0,checks=0,i;
    edge_csr_cdc dut(.s_clk(sc),.s_rst_n(sr),.s_req(req),.s_write(we),.s_address(addr),.s_wdata(wd),
        .s_response(response),.s_rdata(rd),.s_error(error),.d_clk(dc),.d_rst_n(dr),
        .d_req(dreq),.d_write(dwe),.d_address(da),.d_wdata(dw),.d_response(dresp),.d_rdata(data),.d_error(8'd0));
    always @(posedge dc or negedge dr)begin
        if(!dr)begin pending<=0;dresp<=0;delay<=0;data<=0;end
        else begin
            dresp<=0;
            if(dreq)begin
                if(pending)$fatal(1,"CDC delivered a new request before the old target response drained");
                if(dwe!==dw[1])$fatal(1,"Read/write flag crossed epochs");
                pending<=1;delay<=30;data<=dw ^ {16'd0,da};delivered<=delivered+1;
            end
            if(pending && delay>0)delay<=delay-1;
            if(pending && delay==0)begin pending<=0;dresp<=1;end
        end
    end
    task issue;input [31:0] v;begin
        @(negedge sc);wd=v;we=v[1];addr=16'h1234;req=1;
        @(negedge sc);req=0;
    end endtask
    task successful;input [31:0] v;begin
        issue(v);wait(response);@(negedge sc);
        if(error || rd!=(v ^ 32'h1234))$fatal(1,"Stale/mismatched response after source-only reset: expected=%h got=%h err=%h",v^32'h1234,rd,error);
        checks=checks+1;
    end endtask
    initial begin
        repeat(6)@(negedge sc);sr=1;dr=1;
        successful(32'h11110000);
        for(i=0;i<12;i=i+1)begin
            issue(32'ha0000000+i);wait(pending);
            repeat(i%6)@(negedge sc);
            sr=0;@(negedge sc);sr=1;
            successful(32'hb0000000+i);
        end
        // Reset at the source after ACK is raised but before cleanup completes.
        issue(32'hc0000000);wait(dut.ack_level);#1;sr=0;#1;sr=1;
        successful(32'hd0000000);
        // Destination reset while waiting must return a transport error, never
        // silently replay an already issued write/read in a new destination epoch.
        issue(32'he0000000);wait(pending);@(negedge dc);dr=0;
        #1;dr=1;
        wait(response);@(negedge sc);if(error!=8'hff)$fatal(1,"Destination reset did not return link-reset error");
        checks=checks+1;
        successful(32'hf0000000);
        if(delivered!=29)$fatal(1,"Destination reset replayed a request: count=%0d",delivered);
        $display("tb_edge_cdc_reset ALL PASS %0d reset/recovery transactions",checks);$finish;
    end
    initial begin #200000;$fatal(1,"TIMEOUT CDC reset");end
endmodule
