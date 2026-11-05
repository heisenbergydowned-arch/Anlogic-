`timescale 1ns/1ps
module tb_edge_features_abort;
    // 4MHz logical time allows the serial arithmetic budget; physical target stays 100MHz.
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0;reg [31:0] now_ms=0;reg [11:0] ms_div=0;
    always @(posedge clk)if(ms_div==3999)begin ms_div<=0;now_ms<=now_ms+1;end else ms_div<=ms_div+1;
    wire sample_new,adc_new,temp_new,fg_new;wire signed [15:0] ax,ay,az,bx,by,bz,ci,pr,tr;
    wire [15:0] seq;wire [31:0] period;
    edge_test_source #(.CLK_HZ(4000000)) source(.clk(clk),.rst_n(rst_n),.sample_new(sample_new),.adc_new(adc_new),.temp_new(temp_new),.fg_new(fg_new),
        .ax(ax),.ay(ay),.az(az),.bx(bx),.by(by),.bz(bz),.sample_seq(seq),.current_raw(ci),.pressure_raw(pr),.temp_raw(tr),.fg_period(period));
    reg run_samples=1;
    reg req=0,we=0;reg [15:0] addr=0;reg [31:0] wd=0;wire response;wire [31:0] rd;wire [7:0] error;wire available,busy;
    edge_features #(.CLK_HZ(4000000),.TEST_MODE(1)) dut(.clk(clk),.rst_n(rst_n),.now_ms(now_ms),
        .a_new(sample_new && run_samples),.b_new(sample_new && run_samples),.ax(ax),.ay(ay),.az(az),.bx(bx),.by(by),.bz(bz),.a_seq(seq),.b_seq(seq),.a_bad(1'b0),.b_bad(1'b0),
        .adc_new(adc_new),.adc_bad(1'b0),.current_raw(ci),.pressure_raw(pr),.temp_new(temp_new),.temp_bad(1'b0),.temp_raw(tr),
        .fg_new(fg_new),.fg_bad(1'b0),.fg_period(period),.control_mode(4'd3),.local_permit(1'b1),.initial_config_permit(1'b0),
        .req(req),.write_en(we),.address(addr),.wdata(wd),.response(response),.rdata(rd),.error(error),.frame_available(available),.busy(busy));
    integer i,checks=0;reg [31:0] value,word;
    task access;input write;input [15:0] address;input [31:0] data;begin
        @(negedge clk);req=1;we=write;addr=address;wd=data;
        @(negedge clk);req=0;
        if(!response || error!=0)$fatal(1,"Abort integration CSR error addr=%h error=%d",address,error);
        value=rd;checks=checks+1;
    end endtask
    initial begin
        repeat(8)@(negedge clk);rst_n=1;
        wait(dut.out_valid && dut.out_index==3);
        // Exercise the real window-overwrite path while a header is partial.
        @(negedge clk);run_samples=0;force dut.windows.overwriting=1'b1;
        @(negedge clk);release dut.windows.overwriting;
        repeat(5)@(negedge clk);
        if(busy || available || dut.mailbox.building || dut.mailbox.dropped!=1)
            $fatal(1,"Window abort did not cancel partial mailbox/engine");
        for(i=0;i<17;i=i+1)begin
            word=i==0 ? 2 : i==1 || i==2 ? 0 : i==7 ? 2 : i<8 ? 1 : i==8 ? 1 : i==16 ? 513 : (i-8)*32;
            access(1,16'h1300+4*i,word);
        end
        access(1,16'h1040,32'h45434d54);
        wait(!dut.configuring);repeat(3)@(negedge clk);
        access(0,16'h1020,0);if(value!=2)$fatal(1,"Configuration recovery not applied");
        run_samples=1;
        wait(available);
        access(0,16'h1010,0);if(value<=1)$fatal(1,"Aborted frame was published");
        access(0,16'h1140,0);if(value!=2)$fatal(1,"Recovered frame has stale configuration ID");
        $display("tb_edge_features_abort ALL PASS %0d CSR checks / real window abort",checks);$finish;
    end
    initial begin #35000000;$fatal(1,"TIMEOUT feature abort recovery");end
endmodule
